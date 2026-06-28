"""Offline tests for the Foodist Expo parser (no network access)."""

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.base import Exhibitor  # noqa: E402
from scrapers.email_finder import find_email  # noqa: E402
from scrapers.foodist_expo import FoodistExpoScraper, _clean  # noqa: E402

DETAIL_HTML = """
<h1 class="company-title">  ACME  FOODS  A.Ş. </h1>
<div class="widget">
  <h4 class="widget-title">Contact</h4>
  <div class="schedule-list"><ul>
    <li><i class="far fa-phone"></i> +905551234567</li>
    <li><i class="far fa-location-dot"></i> Some Street No:1 Istanbul / Türkiye </li>
    <li><i class="far fa-globe"></i> <a href="https://acme.example/" target="_blank">www.acme.example</a></li>
  </ul></div>
</div>
<div class="widget">
  <h4 class="widget-title">Products</h4>
  <div class="products">
    <div class="product-item"><h2 class="brand-product-title">Olive Oil\ṅ</h2></div>
    <div class="product-item"><h2 class="brand-product-title">Black Olives</h2></div>
  </div>
</div>
"""


def test_clean_collapses_whitespace_and_combining_marks():
    assert _clean("Olive Oil\ṅ") == "Olive Oil"
    assert _clean("  a   b  ") == "a b"
    assert _clean("") == ""


def test_decode_cfemail():
    # "test@example.com" encoded with key 0x7a (standard Cloudflare scheme).
    key = 0x7A
    plain = "test@example.com"
    encoded = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in plain)
    assert FoodistExpoScraper._decode_cfemail(encoded) == plain


def test_parse_detail_fields():
    scraper = FoodistExpoScraper(delay=0)
    soup = BeautifulSoup(DETAIL_HTML, "lxml")
    ex = Exhibitor(name="old name", source="foodist")

    title = soup.select_one("h1.company-title")
    ex.name = title.get_text(strip=True)
    scraper._parse_contact(soup, ex)
    ex.sector = scraper._parse_sector(soup)

    assert ex.phone == "+905551234567"
    assert ex.address == "Some Street No:1 Istanbul / Türkiye"
    assert ex.website == "https://acme.example/"
    assert ex.sector == "Olive Oil; Black Olives"


HOME_HTML = """
<html><body>
  <header>Welcome to ACME Foods</header>
  <a href="/en/iletisim/">İletişim</a>
  <a href="https://facebook.com/acme">Facebook</a>
</body></html>
"""

CONTACT_HTML = """
<html><body>
  <h1>İletişim</h1>
  <p>Phone: +90 555 000 0000</p>
  <p>E-mail: info (at) acmefoods (dot) com</p>
  <a href="mailto:export@acmefoods.com">export@acmefoods.com</a>
  <a href="mailto:noreply@acmefoods.com">noreply</a>
</body></html>
"""


def test_find_email_follows_contact_page_and_ranks():
    pages = {
        "https://acmefoods.com/": HOME_HTML,
        "https://acmefoods.com/en/iletisim/": CONTACT_HTML,
    }

    def fake_fetch(url):
        return pages.get(url)

    # export@ is preferred over info@/noreply@, and the brand domain matches.
    assert find_email("acmefoods.com", fake_fetch) == "export@acmefoods.com"


def test_find_email_empty_when_no_site():
    assert find_email("", lambda url: None) == ""


if __name__ == "__main__":
    test_clean_collapses_whitespace_and_combining_marks()
    test_decode_cfemail()
    test_parse_detail_fields()
    test_find_email_follows_contact_page_and_ranks()
    test_find_email_empty_when_no_site()
    print("All tests passed.")
