#!/usr/bin/env python3
"""CLI entry point for the exhibitor data scraper.

Examples
--------
Scrape all of Foodist Expo into output/foodist.csv and output/foodist.json::

    python main.py --site foodist

Quick test run (first 2 list pages only)::

    python main.py --site foodist --max-pages 2

List the available sites::

    python main.py --list-sites
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from scrapers import SCRAPERS
from scrapers.base import save_csv, save_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape trade-fair exhibitor directories.")
    parser.add_argument(
        "--site",
        choices=sorted(SCRAPERS),
        help="Which site to scrape.",
    )
    parser.add_argument(
        "--list-sites",
        action="store_true",
        help="List supported sites and exit.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit the number of list pages (handy for testing).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between HTTP requests (default: 1.0).",
    )
    parser.add_argument(
        "--out-dir",
        default="output",
        help="Directory for the CSV/JSON output (default: output).",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "json", "both"],
        default="both",
        help="Output format (default: both).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list_sites:
        print("Supported sites:")
        for key, cls in sorted(SCRAPERS.items()):
            print(f"  {key:10s} {cls.base_url}")
        return 0

    if not args.site:
        build_parser().error("--site is required (or use --list-sites)")

    scraper = SCRAPERS[args.site](delay=args.delay)
    exhibitors = scraper.scrape(max_pages=args.max_pages)

    if not exhibitors:
        logging.error("No exhibitors scraped.")
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    base = os.path.join(args.out_dir, args.site)

    if args.format in ("csv", "both"):
        n = save_csv(exhibitors, base + ".csv")
        logging.info("Wrote %d rows to %s.csv", n, base)
    if args.format in ("json", "both"):
        n = save_json(exhibitors, base + ".json")
        logging.info("Wrote %d rows to %s.json", n, base)

    # Brief summary of field coverage.
    with_site = sum(1 for e in exhibitors if e.website)
    with_phone = sum(1 for e in exhibitors if e.phone)
    with_addr = sum(1 for e in exhibitors if e.address)
    logging.info(
        "Coverage: %d total | website %d | phone %d | address %d",
        len(exhibitors),
        with_site,
        with_phone,
        with_addr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
