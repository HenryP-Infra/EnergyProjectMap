"""
BaseScraper — abstract base class for all county data providers.

Every provider must:
  1. Set provider_name (str) as a class attribute.
  2. Implement fetch_documents(fips) → list[ScrapedDocument].

The runner (scrapers/runner.py) calls only this interface, so new providers
can be added by subclassing without touching the pipeline logic.
"""
from __future__ import annotations

import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import settings

log = logging.getLogger(__name__)


@dataclass
class ScrapedDocument:
    """Raw output from a provider's fetch_documents() call."""
    source_url:  str
    raw_bytes:   bytes
    doc_type:    str       # ordinance | minutes | resolution | staff_report | other
    fetched_at:  datetime = field(default_factory=datetime.utcnow)
    title:       str = ""
    extra_meta:  dict = field(default_factory=dict)


class BaseScraper(ABC):
    """
    Abstract base for all county data scrapers.

    Subclasses must set:
        provider_name: str          — unique identifier, e.g. "municode"
        supported_states: list[str] — USPS abbreviations, e.g. ["TX", "CA"]
                                      Empty list means all states are supported.
    """

    provider_name:    str       = "base"
    supported_states: list[str] = []

    def __init__(self):
        self._session = self._build_session()
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch_documents(self, fips: str) -> list[ScrapedDocument]:
        """
        Fetch all energy-related documents for the county identified by `fips`.
        Returns a list of ScrapedDocument instances.
        Implementations should call self._get() for HTTP requests so that
        rate limiting and retries are applied uniformly.
        """

    # ------------------------------------------------------------------
    # Optional overrides
    # ------------------------------------------------------------------

    def get_county_url(self, fips: str) -> str | None:
        """
        Override to compute the county-specific landing URL.
        Returns None if the provider cannot determine the URL automatically.
        """
        return None

    def supports(self, fips: str, state_abbr: str) -> bool:
        """Return True if this provider should be used for this county."""
        if not self.supported_states:
            return True
        return state_abbr.upper() in [s.upper() for s in self.supported_states]

    # ------------------------------------------------------------------
    # Shared HTTP helpers
    # ------------------------------------------------------------------

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({
            "User-Agent": (
                "CountyEnergyPermitExplorer/1.0 "
                "(research tool; contact: admin@example.com)"
            )
        })
        return session

    def _rate_limit(self) -> None:
        """Enforce the configured requests-per-second limit."""
        min_interval = 1.0 / settings.scrape_rate_limit_rps
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.monotonic()

    def _get(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited GET with configured timeout."""
        self._rate_limit()
        kwargs.setdefault("timeout", settings.request_timeout_seconds)
        log.debug("[%s] GET %s", self.provider_name, url)
        resp = self._session.get(url, **kwargs)
        resp.raise_for_status()
        return resp

    def _post(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited POST with configured timeout."""
        self._rate_limit()
        kwargs.setdefault("timeout", settings.request_timeout_seconds)
        log.debug("[%s] POST %s", self.provider_name, url)
        resp = self._session.post(url, **kwargs)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Keyword filtering helper
    # ------------------------------------------------------------------

    ENERGY_KEYWORDS = [
        "solar", "wind", "turbine", "photovoltaic", "battery", "bess",
        "energy storage", "energy facility", "special use", "conditional use",
        "setback", "energy overlay", "renewable", "transmission", "substation",
    ]

    def _is_energy_related(self, text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in self.ENERGY_KEYWORDS)
