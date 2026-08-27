# GoFundMe Scraper

A small Windows GUI tool to look up **any public GoFundMe campaign**: paste a link, get campaign info, and export the donation list to CSV.

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

## What it does

- **Campaign info** — title, organizer, beneficiary, charity (if applicable), location, raised vs. goal (with %), donation count, created date, status, and a description excerpt
- **Donation export** — pages through the donation list (oldest first) with live progress and saves a CSV: `donated_at, name, amount, currency, is_anonymous, donation_id`
- **Flexible input** — accepts full campaign URLs (`gofundme.com/f/...`), `gofund.me` short links (resolves the redirect), or bare campaign slugs
- **Download cap** — grab the first 100 / 500 / 1,000 / 5,000 donations, or all of them

## Usage

1. Download or build `scraper.exe` (below) and run it — no Python or installation needed
2. Paste a campaign link
3. Pick a donation cap and click **Fetch**
4. Optionally click **Save donations as CSV…**

## Building from source

Requires Python 3.10+ on Windows (uses only the standard library plus PyInstaller for packaging):

```bash
pip install pyinstaller
python -m PyInstaller --onefile --windowed --noconfirm --name scraper scraper_app.py
```

The executable lands in `dist/scraper.exe`. To run from source instead: `python scraper_app.py`.

## How it works

The tool calls the same public, unauthenticated GraphQL endpoint (`graphql.gofundme.com/graphql`) that the GoFundMe website itself calls in your browser. It only returns what is publicly displayed on the campaign page — anonymous donations appear only as "Anonymous".

## Notes & disclaimer

- This is an unofficial tool, not affiliated with GoFundMe. Donations are fetched 50 per request, so "All" on very large campaigns can take a few minutes.
- Data availability is subject to GoFundMe's site and API; if they change their frontend, this may need updating.
- Please respect GoFundMe's Terms of Service and use reasonable request rates. Only public data is accessed — no authentication, and no private information is retrievable.
