"""Scraper for the Foodist Istanbul Expo exhibitor directory.

Site: https://www.foodistexpo.com/en/exhibitor-list

Data model discovered on the site
---------------------------------
The exhibitor list is paginated (``?page=N``) with 12 companies per page.
Each list card exposes only: company name, country, hall, booth and a link to
the company's detail page (``.../brand/<slug>``).

The detail page carries the contact information we want:

* phone        - ``<li>`` with a ``fa-phone`` icon
* address      - ``<li>`` with a ``fa-location-dot`` icon
* website      - ``<li>`` with a ``fa-globe`` icon wrapping an ``<a href>``
* sector       - the company's "Products" list (the closest thing the site has
                 to a business area / "תחום עיסוק")

Note on e-mail: the site deliberately does **not** publish per-company e-mail
addresses - it hides them behind a "Send Message" popup. The only e-mail in
the page markup is the fair's own footer address. We therefore leave the
``email`` field empty unless a company explicitly links a ``mailto:``.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, Exhibitor
from scrapers.email_finder import find_email

logger = logging.getLogger(__name__)


def _clean(text: str) -> str:
    """Collapse whitespace and drop stray combining marks left in the markup."""
    if not text:
        return ""
    # Some product titles carry a trailing combining dot (U+0307); strip
    # lone combining marks that aren't attached to a base letter.
    text = "".join(
        ch for ch in text if not unicodedata.combining(ch) or ch.isspace()
    )
    return re.sub(r"\s+", " ", text).strip()


class FoodistExpoScraper(BaseScraper):
    site_key = "foodist"
    base_url = "https://www.foodistexpo.com"
    list_url = "https://www.foodistexpo.com/en/exhibitor-list"

    def __init__(self, *args, find_emails: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # When True, follow each company's own website to recover an e-mail the
        # directory doesn't publish.
        self.find_emails = find_emails

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def scrape(self, max_pages: Optional[int] = None) -> List[Exhibitor]:
        last_page = self._detect_last_page()
        if max_pages is not None:
            last_page = min(last_page, max_pages)
        logger.info("Scraping %d list page(s) from Foodist Expo", last_page)

        exhibitors: List[Exhibitor] = []
        for page in range(1, last_page + 1):
            cards = self._scrape_list_page(page)
            logger.info("Page %d/%d: %d exhibitors", page, last_page, len(cards))
            for ex in cards:
                self._enrich_from_detail(ex)
                if self.find_emails and not ex.email and ex.website:
                    ex.email = find_email(ex.website, self.fetch_external)
                    if ex.email:
                        logger.debug("Found e-mail for %s: %s", ex.name, ex.email)
                exhibitors.append(ex)
        return exhibitors

    # ------------------------------------------------------------------
    # List page
    # ------------------------------------------------------------------

    def _detect_last_page(self) -> int:
        """Read the pagination on page 1 to find the highest page number."""
        html = self.get(f"{self.list_url}?page=1")
        if not html:
            return 1
        pages = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
        return max(pages) if pages else 1

    def _scrape_list_page(self, page: int) -> List[Exhibitor]:
        html = self.get(f"{self.list_url}?page={page}")
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")
        exhibitors: List[Exhibitor] = []

        for item in soup.select("div.brand-item"):
            link = item.select_one("a.brand-link[href]")
            name_el = item.select_one(".brand-name")
            name = _clean(name_el.get_text(strip=True)) if name_el else ""
            if not name and not link:
                continue

            ex = Exhibitor(name=name, source=self.site_key)

            country_el = item.select_one(".brand-country")
            if country_el:
                ex.country = _clean(country_el.get_text(strip=True))

            ex.booth = self._extract_booth(item)

            if link:
                ex.detail_url = urljoin(self.list_url + "/", link["href"])

            exhibitors.append(ex)

        return exhibitors

    @staticmethod
    def _extract_booth(item) -> str:
        """Combine the Hall / Booth location items into one string."""
        parts = []
        for loc in item.select(".brand-location-info .location-item span"):
            text = _clean(loc.get_text(" ", strip=True))
            if text:
                parts.append(text)
        return " | ".join(parts)

    # ------------------------------------------------------------------
    # Detail page
    # ------------------------------------------------------------------

    def _enrich_from_detail(self, ex: Exhibitor) -> None:
        if not ex.detail_url:
            return
        html = self.get(ex.detail_url)
        if not html:
            return
        soup = BeautifulSoup(html, "lxml")

        title = soup.select_one("h1.company-title")
        if title:
            ex.name = title.get_text(strip=True) or ex.name

        self._parse_contact(soup, ex)
        ex.sector = self._parse_sector(soup)

    def _parse_contact(self, soup: BeautifulSoup, ex: Exhibitor) -> None:
        """Pull phone / address / website / email out of the Contact widget."""
        widget = self._find_widget(soup, "Contact")
        if widget is None:
            return

        for li in widget.select("li"):
            icon = li.select_one("i")
            icon_classes = " ".join(icon.get("class", [])) if icon else ""
            link = li.select_one("a[href]")

            if "fa-phone" in icon_classes:
                ex.phone = _clean(li.get_text(" ", strip=True))
            elif "fa-location" in icon_classes or "fa-map" in icon_classes:
                ex.address = _clean(li.get_text(" ", strip=True))
            elif "fa-globe" in icon_classes:
                if link:
                    href = link.get("href", "").strip()
                    ex.website = href or _clean(link.get_text(strip=True))
                else:
                    ex.website = _clean(li.get_text(" ", strip=True))
            elif "fa-envelope" in icon_classes:
                email = self._extract_email(li)
                if email:
                    ex.email = email

    def _parse_sector(self, soup: BeautifulSoup) -> str:
        """Use the company's product titles as the business sector."""
        widget = self._find_widget(soup, "Products")
        if widget is None:
            return ""
        products = []
        for el in widget.select(".brand-product-title"):
            text = _clean(el.get_text(" ", strip=True))
            if text and text not in products:
                products.append(text)
        return "; ".join(products)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_widget(soup: BeautifulSoup, title: str):
        """Return the ``.widget`` whose ``.widget-title`` matches ``title``."""
        for widget in soup.select(".widget"):
            wt = widget.select_one(".widget-title")
            if wt and wt.get_text(strip=True).lower() == title.lower():
                return widget
        return None

    @staticmethod
    def _extract_email(node) -> str:
        """Extract an e-mail, decoding Cloudflare-obfuscated addresses."""
        # Direct mailto link.
        link = node.select_one("a[href^='mailto:']")
        if link:
            return link["href"].split(":", 1)[1].split("?")[0].strip()

        # Cloudflare email protection: data-cfemail holds a hex-encoded address.
        cf = node.select_one("[data-cfemail]")
        if cf:
            return FoodistExpoScraper._decode_cfemail(cf["data-cfemail"])
        return ""

    @staticmethod
    def _decode_cfemail(encoded: str) -> str:
        try:
            key = int(encoded[:2], 16)
            return "".join(
                chr(int(encoded[i : i + 2], 16) ^ key)
                for i in range(2, len(encoded), 2)
            )
        except (ValueError, IndexError):
            return ""
