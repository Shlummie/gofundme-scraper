"""GoFundMe Scraper - a small GUI tool to look up any GoFundMe campaign.

Paste a campaign link (gofundme.com/f/... or a gofund.me short link),
fetch campaign info and donations, and export them to CSV.
"""
import csv
import json
import re
import threading
import queue
import time
import urllib.request
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
from datetime import datetime

API = "https://graphql.gofundme.com/graphql"
HEADERS = {
    "content-type": "application/json",
    "accept": "application/json",
    "origin": "https://www.gofundme.com",
    "client-name": "SSR Frontend",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "accept-encoding": "identity",
}
PAGE_SIZE = 50  # API maximum

INFO_QUERY = """
query GetInfo($slug: ID!) {
  fundraiser(slug: $slug) {
    id
    title
    description(excerpt: true)
    createdAt
    publishedAt
    status
    state
    donationsEnabled
    donationCount
    currentAmount { amount currencyCode }
    goalAmount { amount currencyCode }
    organizer { firstName lastName }
    beneficiary { firstName lastName facebookName }
    location { city countryCode postalCode statePrefix }
    charity { name city state country }
  }
}
"""

DONATIONS_QUERY = """
query GetDonations($slug: ID!, $first: Int, $after: String) {
  fundraiser(slug: $slug) {
    donations(first: $first, after: $after) {
      edges { node {
        amount { amount currencyCode }
        createdAt
        id
        isAnonymous
        name
      } }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""


def gql(query, variables, attempt=1):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(API, data=body, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        if attempt < 4:
            time.sleep(2 * attempt)
            return gql(query, variables, attempt + 1)
        raise RuntimeError(f"Network error: {exc}") from exc
    if data.get("errors"):
        msgs = "; ".join(e.get("message", "?") for e in data["errors"])
        raise RuntimeError(f"API error: {msgs}")
    return data["data"]


def extract_slug(text):
    """Accept a full URL, short link, or bare slug."""
    text = text.strip()
    m = re.search(r"gofundme\.com/(?:f|c)/([A-Za-z0-9-]+)", text)
    if m:
        return m.group(1)
    if re.match(r"^https?://(www\.)?gofund\.me/", text, re.I):
        req = urllib.request.Request(text, headers={"user-agent": HEADERS["user-agent"]})
        with urllib.request.urlopen(req, timeout=20) as resp:
            final = resp.geturl()
        m = re.search(r"gofundme\.com/(?:f|c)/([A-Za-z0-9-]+)", final)
        if m:
            return m.group(1)
        raise RuntimeError(f"Short link resolved to {final}, which has no campaign slug.")
    if re.match(r"^[A-Za-z0-9-]+$", text):
        return text
    raise RuntimeError("Could not find a campaign slug in that input.")


def fetch_info(slug):
    data = gql(INFO_QUERY, {"slug": slug})
    fr = data.get("fundraiser")
    if not fr:
        raise RuntimeError("Campaign not found (it may be private, removed, or a charity page).")
    return fr


def fetch_donations(slug, limit, log):
    """Fetch up to `limit` donations (None = all). Oldest first."""
    out = {}
    after = None
    page = 0
    while True:
        conn = gql(DONATIONS_QUERY, {"slug": slug, "first": PAGE_SIZE, "after": after})["fundraiser"]["donations"]
        for edge in conn["edges"]:
            node = edge["node"]
            out[node["id"]] = node
            if limit and len(out) >= limit:
                break
        page += 1
        got = len(out)
        if page % 5 == 0 or got >= (limit or float("inf")):
            log(f"  ...{got} donations (page {page})")
        if limit and got >= limit:
            break
        info = conn["pageInfo"]
        if not info["hasNextPage"] or not info["endCursor"]:
            break
        after = info["endCursor"]
        time.sleep(0.05)
    rows = sorted(out.values(), key=lambda d: d["createdAt"])
    return rows


def fmt_money(amt_obj):
    if not amt_obj or amt_obj.get("amount") is None:
        return "n/a"
    return f"{amt_obj['amount']:,.2f} {amt_obj.get('currencyCode', '')}".strip()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GoFundMe Scraper")
        self.geometry("680x640")
        self.minsize(560, 520)
        self.busy = False
        self.results = []
        self.slug = None
        self.q = queue.Queue()

        pad = {"padx": 10, "pady": 6}
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Campaign link:").pack(anchor="w")
        row = ttk.Frame(top)
        row.pack(fill="x")
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(row, textvariable=self.url_var)
        self.url_entry.pack(side="left", fill="x", expand=True)
        self.fetch_btn = ttk.Button(row, text="Fetch", command=self.start_fetch)
        self.fetch_btn.pack(side="left", padx=(8, 0))

        opts = ttk.Frame(self)
        opts.pack(fill="x", padx=10)
        ttk.Label(opts, text="Max donations:").pack(side="left")
        self.limit_var = tk.StringVar(value="500")
        self.limit_box = ttk.Combobox(opts, textvariable=self.limit_var, width=8,
                                      values=["100", "500", "1000", "5000", "All"], state="readonly")
        self.limit_box.pack(side="left", padx=(6, 0))
        self.csv_btn = ttk.Button(opts, text="Save donations as CSV…", command=self.save_csv, state="disabled")
        self.csv_btn.pack(side="right")

        ttk.Label(self, text="Summary:").pack(anchor="w", padx=10, pady=(10, 0))
        self.summary = scrolledtext.ScrolledText(self, height=13, wrap="word", state="disabled")
        self.summary.pack(fill="both", expand=True, padx=10)

        ttk.Label(self, text="Log:").pack(anchor="w", padx=10, pady=(8, 0))
        self.logbox = scrolledtext.ScrolledText(self, height=8, wrap="word", state="disabled")
        self.logbox.pack(fill="both", padx=10, pady=(0, 10))
        self.logbox.tag_config("err", foreground="#b3261e")
        self.logbox.tag_config("dim", foreground="#65676b")

        self.after(100, self.poll)

    def log(self, text, tag=""):
        self.q.put(("log", text, tag))

    def start_fetch(self):
        if self.busy:
            return
        raw = self.url_var.get().strip()
        if not raw:
            self._log("Paste a GoFundMe link first.", "err")
            return
        self.busy = True
        self.results = []
        self.slug = None
        self.fetch_btn.config(state="disabled")
        self.csv_btn.config(state="disabled")
        self._clear_log()
        self._set_summary("Working…")
        limit_text = self.limit_var.get()
        limit = None if limit_text == "All" else int(limit_text)
        threading.Thread(target=self._worker, args=(raw, limit), daemon=True).start()

    def _worker(self, raw, limit):
        try:
            slug = extract_slug(raw)
            self.log(f"Campaign slug: {slug}")
            self.slug = slug
            info = fetch_info(slug)
            self._emit_info(info)
            n_total = info.get("donationCount")
            self.log(f"Fetching donations ({limit if limit else 'all'} of {n_total})…")
            rows = fetch_donations(slug, limit, self.log)
            self.results = rows
            if rows:
                usd = [r["amount"]["amount"] for r in rows if r["amount"].get("currencyCode") == "USD"]
                total = sum(usd) if usd else sum(r["amount"]["amount"] for r in rows)
                span = f"{rows[0]['createdAt'][:10]} → {rows[-1]['createdAt'][:10]}"
                self.log(f"Fetched {len(rows)} donations spanning {span}; sum {total:,.2f}")
            self.log("Done.", "dim")
            self.q.put(("done", None, None))
        except Exception as exc:
            self.log(str(exc), "err")
            self.q.put(("done", None, None))

    def _emit_info(self, fr):
        def name(p):
            if not p:
                return "n/a"
            return (p.get("firstName", "") + " " + p.get("lastName", "")).strip() or p.get("facebookName") or "n/a"
        lines = []
        lines.append(f"TITLE      {fr.get('title') or 'n/a'}")
        lines.append(f"ORGANIZER  {name(fr.get('organizer'))}")
        lines.append(f"BENEFICIARY {name(fr.get('beneficiary'))}")
        ch = fr.get("charity")
        if ch:
            lines.append(f"CHARITY    {ch.get('name')} ({ch.get('city')}, {ch.get('state')} {ch.get('country')})")
        loc = fr.get("location") or {}
        where = ", ".join(x for x in [loc.get("city"), loc.get("statePrefix"), loc.get("countryCode")] if x)
        if where:
            lines.append(f"LOCATION   {where}")
        raised = fr.get("currentAmount")
        goal = fr.get("goalAmount")
        lines.append(f"RAISED     {fmt_money(raised)}")
        if goal and goal.get("amount"):
            pct = raised["amount"] / goal["amount"] * 100 if raised and raised.get("amount") else 0
            lines.append(f"GOAL       {fmt_money(goal)}  ({pct:.1f}%)")
        lines.append(f"DONATIONS  {fr.get('donationCount'):,}" if fr.get("donationCount") is not None else "DONATIONS  n/a")
        created = fr.get("createdAt", "")[:10]
        lines.append(f"CREATED    {created}")
        lines.append(f"STATUS     {fr.get('status')} / {fr.get('state')} / donations {'on' if fr.get('donationsEnabled') else 'off'}")
        desc = (fr.get("description") or "").strip()
        if desc:
            desc = re.sub(r"\s+", " ", desc)[:400] + ("…" if len(desc) > 400 else "")
            lines.append("")
            lines.append(f"ABOUT      {desc}")
        self.q.put(("summary", "\n".join(lines), None))

    def _log(self, text, tag=""):
        self.logbox.config(state="normal")
        self.logbox.insert("end", text + "\n", tag)
        self.logbox.see("end")
        self.logbox.config(state="disabled")

    def _clear_log(self):
        self.logbox.config(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.config(state="disabled")

    def _set_summary(self, text):
        self.summary.config(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.insert("1.0", text)
        self.summary.config(state="disabled")

    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._log(item[1], item[2])
                elif kind == "summary":
                    self._set_summary(item[1])
                elif kind == "done":
                    self.busy = False
                    self.fetch_btn.config(state="normal")
                    if self.results:
                        self.csv_btn.config(state="normal")
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def save_csv(self):
        if not self.results:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=f"{self.slug or 'gofundme'}-donations.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["donated_at", "name", "amount", "currency", "is_anonymous", "donation_id"])
            for r in self.results:
                w.writerow([r["createdAt"], r["name"], f'{r["amount"]["amount"]:.2f}',
                            r["amount"].get("currencyCode"), r["isAnonymous"], r["id"]])
        self._log(f"Saved {len(self.results)} donations to {path}")


if __name__ == "__main__":
    App().mainloop()
