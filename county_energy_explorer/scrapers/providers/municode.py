"""
MunicodeProvider — scrapes county ordinances from Municode.com.

Municode exposes a predictable URL structure and a JSON TOC API.
We traverse the table of contents, find energy-related chapters,
then download the corresponding PDF or HTML documents.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScrapedDocument

log = logging.getLogger(__name__)

# Municode uses a consistent pattern: /library/{client_id}/...
# The client_id is stored in county_providers.config_json as {"client_id": "..."}
_BASE = "https://library.municode.com"
_TOC_API = "https://library.municode.com/api/tocs/{client_id}"


class MunicodeProvider(BaseScraper):
    provider_name    = "municode"
    supported_states = []  # Municode is used nationwide

    def fetch_documents(self, fips: str) -> list[ScrapedDocument]:
        from db.database import get_db
        from db.models import CountyProvider
        import json

        with get_db() as db:
            cp = (
                db.query(CountyProvider)
                .filter_by(fips=fips, provider=self.provider_name)
                .first()
            )
            if not cp:
                log.warning("No Municode config for FIPS %s", fips)
                return []
            config = json.loads(cp.config_json or "{}")
            client_id = config.get("client_id", "")
            if not client_id:
                log.warning("Missing client_id in Municode config for FIPS %s", fips)
                return []

        return self._fetch_for_client(client_id)

    def _fetch_for_client(self, client_id: str) -> list[ScrapedDocument]:
        docs: list[ScrapedDocument] = []

        try:
            toc_url = _TOC_API.format(client_id=client_id)
            resp = self._get(toc_url)
            toc = resp.json()
        except Exception as exc:
            log.error("Municode TOC fetch failed for client %s: %s", client_id, exc)
            return []

        # Walk TOC nodes recursively, collect energy-related chapter URLs
        chapter_urls = []
        self._walk_toc(toc, chapter_urls)
        log.info("Municode: found %d energy-related chapters for client %s",
                 len(chapter_urls), client_id)

        for url in chapter_urls:
            try:
                resp = self._get(url)
                raw_bytes = resp.content
                title = self._extract_title(raw_bytes)
                docs.append(ScrapedDocument(
                    source_url=url,
                    raw_bytes=raw_bytes,
                    doc_type="ordinance",
                    title=title,
                    extra_meta={"client_id": client_id},
                ))
            except Exception as exc:
                log.warning("Municode chapter fetch failed %s: %s", url, exc)

        return docs

    def _walk_toc(self, node: dict | list, urls: list[str]) -> None:
        """Recursively walk the TOC JSON tree and collect energy-related URLs."""
        if isinstance(node, list):
            for item in node:
                self._walk_toc(item, urls)
            return

        if isinstance(node, dict):
            title = node.get("title", "") or node.get("name", "")
            if self._is_energy_related(title):
                url = node.get("url") or node.get("href")
                if url:
                    full_url = url if url.startswith("http") else urljoin(_BASE, url)
                    urls.append(full_url)
            # Recurse into children regardless (energy content may be in sub-chapters)
            for child_key in ("children", "items", "nodes"):
                if child_key in node:
                    self._walk_toc(node[child_key], urls)

    def _extract_title(self, raw_bytes: bytes) -> str:
        try:
            soup = BeautifulSoup(raw_bytes, "lxml")
            h1 = soup.find("h1") or soup.find("h2")
            if h1:
                return h1.get_text(strip=True)[:300]
        except Exception:
            pass
        return "Ordinance"
