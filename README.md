# Exhibitor Data Scraper

A small, extensible Python project that scrapes trade-fair **exhibitor
directories** and extracts, for every company:

| Field        | Description                                  |
|--------------|----------------------------------------------|
| `name`       | Company name                                 |
| `website`    | Company website                              |
| `email`      | E-mail address (when published — see note)   |
| `phone`      | Phone number                                 |
| `address`    | Postal address                               |
| `sector`     | Business area / products ("תחום עיסוק")      |
| `country`    | Country                                       |
| `booth`      | Hall / booth location at the fair            |
| `detail_url` | Link to the company's detail page            |
| `source`     | Which site the row came from                  |

Results are written to **CSV** (Excel-friendly, UTF-8 BOM) and **JSON**.

## First supported site: Foodist Istanbul Expo

<https://www.foodistexpo.com/en/exhibitor-list>

The exhibitor list is paginated (~41 pages × 12 companies ≈ 490 companies).
The list page gives the name, country and booth; the per-company detail page
(`.../brand/<slug>`) provides phone, address, website and the product list we
use as the business sector.

> **Note on e-mail:** this site does **not** publish per-company e-mail
> addresses — it hides them behind a "Send Message" popup, so the directory
> page never carries an e-mail. To recover one, the scraper can follow each
> company's **own website** to its "Contact" / "İletişim" page and pull the
> e-mail from there — enable it with `--find-emails` (see below).

### E-mail discovery (`--find-emails`)

Because the directory withholds e-mails, the scraper instead visits the
company website it *does* list, scans the home page, and — if needed —
follows the contact page (`iletişim` / `contact`, multi-language) to extract
the address. It handles `mailto:` links, Cloudflare-obfuscated addresses, and
common `name (at) domain (dot) com` obfuscation, then prefers an address on
the company's own domain (e.g. `export@`, `info@`).

It's best-effort: some company sites are down, return the wrong URL, or sit
behind bot protection, so a few rows will still have no e-mail. On a sample
page this recovered e-mails for ~75% of companies that list a website.

## Setup

```bash
pip install -r requirements.txt
```

Requires Python 3.9+.

## Usage

```bash
# Scrape the whole Foodist Expo site -> output/foodist.csv + output/foodist.json
python main.py --site foodist

# Quick test: only the first 2 list pages
python main.py --site foodist --max-pages 2

# Also recover e-mails from each company's website (slower)
python main.py --site foodist --find-emails

# List supported sites
python main.py --list-sites
```

Useful flags:

| Flag           | Default  | Meaning                                      |
|----------------|----------|----------------------------------------------|
| `--site`       | —        | Site to scrape (see `--list-sites`)          |
| `--max-pages`  | all      | Limit the number of list pages               |
| `--delay`      | `1.0`    | Seconds between HTTP requests (be polite)    |
| `--find-emails`| off      | Recover e-mails via each company's website   |
| `--format`     | `both`   | `csv`, `json`, or `both`                      |
| `--out-dir`    | `output` | Output directory                              |
| `-v/--verbose` | off      | Debug logging                                 |

A full run takes a few minutes because it fetches every detail page with a
polite delay. Lower `--delay` to speed it up, but keep it reasonable.

## Project layout

```
main.py                  CLI entry point
scrapers/
  __init__.py            site registry (SCRAPERS)
  base.py                BaseScraper (HTTP session, retries, rate limit) + Exhibitor + CSV/JSON writers
  email_finder.py        reusable e-mail discovery from a company website
  foodist_expo.py        Foodist Istanbul Expo scraper
output/                  generated CSV/JSON (git-ignored)
```

## Adding another site

1. Create `scrapers/<site>.py` with a class that subclasses
   `BaseScraper`, sets `site_key` / `base_url`, and implements
   `scrape(max_pages) -> list[Exhibitor]`.
2. Register it in `scrapers/__init__.py` (add it to `SCRAPERS`).

The shared `BaseScraper` already handles the browser User-Agent (the target
sites reject the default one with HTTP 403), retries with exponential backoff,
and rate limiting, so a new site only needs its page-parsing logic.

## Responsible use

This tool is for collecting publicly listed exhibitor information. Keep the
request delay reasonable, respect each site's terms of service, and use the
contact data in line with applicable privacy/anti-spam regulations.
