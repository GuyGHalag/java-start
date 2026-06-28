"""Shared building blocks for all site scrapers.

This module defines:

* :class:`Exhibitor` - the normalized record every scraper produces, with the
  fields the project cares about (name, website, email, phone, address,
  business sector).
* :class:`BaseScraper` - a small base class that owns an HTTP session with a
  browser-like User-Agent, polite retry/backoff and rate limiting, so each
  site scraper only has to implement the page parsing.

Adding a new site is therefore a matter of subclassing :class:`BaseScraper`
and implementing :meth:`BaseScraper.scrape`.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

import requests

logger = logging.getLogger(__name__)

# A realistic desktop User-Agent. The target sites return HTTP 403 for the
# default ``python-requests`` agent, so a browser-like one is required.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class Exhibitor:
    """A single company/exhibitor record.

    ``source`` records which site the row came from, which keeps the output
    usable once several sites feed into the same CSV/JSON file.
    """

    name: str = ""
    website: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    sector: str = ""  # business area / "תחום עיסוק"
    country: str = ""
    booth: str = ""
    detail_url: str = ""
    source: str = ""

    # Column order used for CSV export.
    CSV_FIELDS = [
        "name",
        "website",
        "email",
        "phone",
        "address",
        "sector",
        "country",
        "booth",
        "detail_url",
        "source",
    ]

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


class BaseScraper:
    """Base class providing a polite, resilient HTTP client.

    Subclasses must set :attr:`site_key` / :attr:`base_url` and implement
    :meth:`scrape`, which returns the list of :class:`Exhibitor` records.
    """

    #: Short identifier used on the CLI and stored in ``Exhibitor.source``.
    site_key: str = ""
    #: Site root, used for resolving relative links.
    base_url: str = ""

    def __init__(
        self,
        delay: float = 1.0,
        timeout: float = 30.0,
        max_retries: int = 4,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._last_request_ts = 0.0

    # -- HTTP helpers ----------------------------------------------------

    def get(self, url: str) -> Optional[str]:
        """Fetch ``url`` and return the response text.

        Rate-limits between requests and retries with exponential backoff on
        network errors / 5xx / 429. Returns ``None`` if all retries fail.
        """
        self._respect_rate_limit()

        backoff = 2.0
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                self._last_request_ts = time.monotonic()
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        "GET %s -> HTTP %s (attempt %d/%d)",
                        url,
                        resp.status_code,
                        attempt,
                        self.max_retries,
                    )
                else:
                    logger.error("GET %s -> HTTP %s (giving up)", url, resp.status_code)
                    return None
            except requests.RequestException as exc:
                logger.warning(
                    "GET %s failed: %s (attempt %d/%d)",
                    url,
                    exc,
                    attempt,
                    self.max_retries,
                )

            if attempt < self.max_retries:
                time.sleep(backoff)
                backoff *= 2

        logger.error("GET %s failed after %d attempts", url, self.max_retries)
        return None

    def fetch_external(self, url: str, timeout: float = 15.0) -> Optional[str]:
        """Best-effort fetch of an *external* (company) site.

        Unlike :meth:`get`, this makes a single attempt with a short timeout and
        no long backoff, so a slow or dead company website cannot stall a run.
        Follows redirects and returns the response text on HTTP 200, else None.
        """
        self._respect_rate_limit()
        try:
            resp = self.session.get(url, timeout=timeout, allow_redirects=True)
            self._last_request_ts = time.monotonic()
            if resp.status_code == 200 and resp.text:
                return resp.text
        except requests.RequestException as exc:
            logger.debug("external GET %s failed: %s", url, exc)
        return None

    def _respect_rate_limit(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    # -- To be implemented by subclasses ---------------------------------

    def scrape(self, max_pages: Optional[int] = None) -> List[Exhibitor]:
        raise NotImplementedError


# -- Output helpers ------------------------------------------------------


def save_csv(exhibitors: Iterable[Exhibitor], path: str) -> int:
    rows = list(exhibitors)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=Exhibitor.CSV_FIELDS)
        writer.writeheader()
        for ex in rows:
            writer.writerow({k: ex.as_dict().get(k, "") for k in Exhibitor.CSV_FIELDS})
    return len(rows)


def save_json(exhibitors: Iterable[Exhibitor], path: str) -> int:
    rows = [ex.as_dict() for ex in exhibitors]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    return len(rows)
