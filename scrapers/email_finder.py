"""Discover a company's e-mail address from its own website.

Many exhibitor directories (Foodist Expo included) don't publish e-mail
addresses, but they do link to each company's website. This module follows
that website, looks for e-mails on the home page, and - if none are found -
follows the "Contact" / "İletişim" page and looks there.

It is intentionally site-agnostic so it can be reused by any scraper: pass a
``fetch`` callable (e.g. :meth:`scrapers.base.BaseScraper.fetch_external`) and
a website URL, and get back the single best e-mail (or ``""``).
"""

from __future__ import annotations

import logging
import re
from typing import Callable, List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Anchor text / href fragments that point at a contact page (multi-language,
# Turkish first since most exhibitors are Turkish).
CONTACT_HINTS = (
    "iletisim",
    "iletişim",
    "contact",
    "kontak",
    "contacto",
    "contato",
    "get-in-touch",
    "getintouch",
    "reach-us",
    "bize-ulasin",
)

# Common contact paths to probe when no contact link is found on the home page.
FALLBACK_PATHS = ("/iletisim", "/iletisim/", "/contact", "/contact-us", "/en/contact", "/en/iletisim")

# File "extensions" that look like e-mail TLDs but are really asset references.
_ASSET_TLDS = {
    "png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js", "ico",
    "mp4", "webm", "pdf", "woff", "woff2", "ttf", "eot",
}

# Placeholder / third-party domains that are never the company's real e-mail.
_BAD_DOMAIN_HINTS = (
    "example.", "domain.com", "yourdomain", "yoursite", "mysite.",
    "sentry.", "wix.com", "wixpress.com", "godaddy", "email.com",
    "sentry.io", "wordpress.", "w3.org", "schema.org",
)

_BAD_LOCALPARTS = ("noreply", "no-reply", "donotreply", "do-not-reply")

# Preferred mailbox names, best first (Turkish + English business inboxes).
_PREFERRED_LOCALPARTS = (
    "export", "ihracat", "sales", "satis", "satış",
    "info", "iletisim", "contact", "bilgi", "kurumsal",
)


def _deobfuscate(html: str) -> str:
    """Turn common anti-scrape e-mail obfuscations into plain text."""
    html = html.replace("&#64;", "@").replace("&commat;", "@")
    html = re.sub(r"\s*[\(\[\{]\s*at\s*[\)\]\}]\s*", "@", html, flags=re.I)
    html = re.sub(r"\s*[\(\[\{]\s*dot\s*[\)\]\}]\s*", ".", html, flags=re.I)
    return html


def _decode_cf_emails(soup: BeautifulSoup) -> List[str]:
    """Decode Cloudflare ``data-cfemail`` obfuscated addresses."""
    out = []
    for node in soup.select("[data-cfemail]"):
        encoded = node.get("data-cfemail", "")
        try:
            key = int(encoded[:2], 16)
            email = "".join(
                chr(int(encoded[i : i + 2], 16) ^ key) for i in range(2, len(encoded), 2)
            )
            if email:
                out.append(email)
        except (ValueError, IndexError):
            continue
    return out


def _brand_token(netloc: str) -> str:
    """A rough brand label from a host, e.g. ``adafood.com.tr`` -> ``adafood``."""
    host = netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    return labels[0] if labels else host


def _is_valid_email(email: str) -> bool:
    email = email.lower()
    domain = email.split("@", 1)[1]
    tld = domain.rsplit(".", 1)[-1]
    if tld in _ASSET_TLDS:
        return False
    if any(bad in domain for bad in _BAD_DOMAIN_HINTS):
        return False
    local = email.split("@", 1)[0]
    if any(bad in local for bad in _BAD_LOCALPARTS):
        return False
    # Filenames such as logo@2x.png already excluded by TLD; also drop ones with
    # no real dot in the domain.
    return "." in domain


def _extract_emails(html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")

    found: List[str] = []
    seen: Set[str] = set()

    def add(email: str) -> None:
        email = email.strip().strip(".").lower()
        if email and email not in seen and _is_valid_email(email):
            seen.add(email)
            found.append(email)

    # mailto: links are the most reliable signal.
    for a in soup.select("a[href^='mailto:']"):
        addr = a["href"].split(":", 1)[1].split("?")[0]
        for piece in addr.split(","):
            if piece.strip():
                add(piece)

    for email in _decode_cf_emails(soup):
        add(email)

    # Fall back to a regex sweep over the de-obfuscated text.
    text = _deobfuscate(soup.get_text(" "))
    for match in EMAIL_RE.findall(text):
        add(match)

    return found


def _rank(emails: List[str], brand: str) -> List[str]:
    """Order candidates: brand-domain matches first, then preferred mailboxes."""

    def score(email: str) -> tuple:
        local, domain = email.split("@", 1)
        domain_match = brand and brand in domain
        try:
            pref = _PREFERRED_LOCALPARTS.index(local)
        except ValueError:
            pref = len(_PREFERRED_LOCALPARTS)
        return (0 if domain_match else 1, pref, len(email))

    return sorted(emails, key=score)


def _find_contact_links(html: str, base: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    base_host = urlparse(base).netloc.lower()
    links: List[str] = []
    seen: Set[str] = set()
    for a in soup.select("a[href]"):
        href = a["href"]
        text = (a.get_text(" ") or "").lower()
        haystack = (href + " " + text).lower()
        if not any(hint in haystack for hint in CONTACT_HINTS):
            continue
        url = urljoin(base, href)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        # Stay on the same site.
        if parsed.netloc and base_host and parsed.netloc.lower() != base_host:
            continue
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def find_email(
    website: str,
    fetch: Callable[[str], Optional[str]],
    max_contact_pages: int = 3,
) -> str:
    """Return the best e-mail for ``website`` (or ``""`` if none found).

    ``fetch`` is a ``url -> html | None`` callable used for every request so
    the caller controls the HTTP session, headers and rate limiting.
    """
    if not website:
        return ""
    if not website.startswith(("http://", "https://")):
        website = "https://" + website

    parsed = urlparse(website)
    home = f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}"
    brand = _brand_token(parsed.netloc)

    candidates: List[str] = []

    home_html = fetch(home)
    if home_html:
        candidates.extend(_extract_emails(home_html))
        contact_links = _find_contact_links(home_html, home)
    else:
        contact_links = []

    # If the home page already gave us a brand-domain e-mail, that's enough.
    ranked = _rank(candidates, brand)
    if ranked and brand and brand in ranked[0].split("@", 1)[1]:
        return ranked[0]

    # Otherwise visit contact pages (discovered links first, then fallbacks).
    base = f"{parsed.scheme}://{parsed.netloc}"
    targets = contact_links[:max_contact_pages]
    if not targets:
        targets = [base + p for p in FALLBACK_PATHS]

    for url in targets[:max_contact_pages]:
        html = fetch(url)
        if not html:
            continue
        new = _extract_emails(html)
        if new:
            candidates.extend(new)
            ranked = _rank(candidates, brand)
            if brand and brand in ranked[0].split("@", 1)[1]:
                return ranked[0]

    ranked = _rank(candidates, brand)
    return ranked[0] if ranked else ""
