"""Exhibitor data-scraping package.

Each supported trade-fair / directory site gets its own scraper module that
subclasses :class:`scrapers.base.BaseScraper`. The first implemented site is
Foodist Istanbul Expo (:mod:`scrapers.foodist_expo`).
"""

from scrapers.base import BaseScraper, Exhibitor
from scrapers.foodist_expo import FoodistExpoScraper

# Registry of available site scrapers, keyed by a short slug used on the CLI.
SCRAPERS = {
    FoodistExpoScraper.site_key: FoodistExpoScraper,
}

__all__ = ["BaseScraper", "Exhibitor", "FoodistExpoScraper", "SCRAPERS"]
