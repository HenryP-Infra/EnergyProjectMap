"""
CivicPlusProvider — scrapes CivicPlus/CivicWeb county portal sites.
GenericPortalProvider — fallback scraper using a simple HTTP crawl of the county
                        government domain to find energy-related PDFs.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScrapedDocument

log = logging.getLogger(__name__)


class CivicPlusProvider(BaseScraper):
    """
    CivicPlus (formerly CivicWeb) varies significantly by county but usually
    exposes an agenda/minutes search endpoint at /sirepub/ or /AgendaOnline/.
    This implementation covers the most common CivicPlus pattern.
    For counties that require JS rendering, fall back to GenericPortalProvider.
    """
    provider_name    = "civicplus"
    supported_states = []

    def fetch_documents(self, fips: str) -> list[ScrapedDocument]:
        from db.database import get_db
        from db.models import CountyProvider

        with get_db() as db:
            cp = (
                db.query(CountyProvider)
                .filter_by(fips=fips, provider=self.provider_name)
                .first()
            )
            if not cp:
                return []
            config = json.loads(cp.config_json or "{}")
            base_url = cp.base_url or config.get("base_url", "")
            if not base_url:
                return []

        return self._crawl_civicplus(base_url)

    def _crawl_civicplus(self, base_url: str) -> list[ScrapedDocument]:
        docs: list[ScrapedDocument] = []
        # Common CivicPlus search endpoints
        search_paths = [
            "/sirepub/agdocs.aspx",
            "/AgendaOnline/Meetings/Search",
            "/BoardDocs/bhlink.asp",
        ]
        for path in search_paths:
            url = urljoin(base_url, path)
            try:
                resp = self._get(url)
                found = self._extract_pdf_links(resp.content, base_url)
                for link, title in found:
                    if not self._is_energy_related(title):
                        continue
                    try:
                        pdf_resp = self._get(link)
                        docs.append(ScrapedDocument(
                            source_url=link,
                            raw_bytes=pdf_resp.content,
                            doc_type=self._classify(title),
                            title=title,
                        ))
                    except Exception:
                        pass
            except Exception:
                continue
        return docs

    def _extract_pdf_links(
        self, html: bytes, base_url: str
    ) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True) or href
            if ".pdf" in href.lower() or "pdf" in text.lower():
                full = href if href.startswith("http") else urljoin(base_url, href)
                results.append((full, text))
        return results

    def _classify(self, title: str) -> str:
        lower = title.lower()
        if "minutes" in lower:
            return "minutes"
        if "agenda" in lower:
            return "minutes"
        if "ordinance" in lower:
            return "ordinance"
        if "resolution" in lower:
            return "resolution"
        if "staff" in lower:
            return "staff_report"
        return "other"


class GenericPortalProvider(BaseScraper):
    """
    Fallback provider for counties not served by Municode, Legistar, or CivicPlus.

    Strategy:
      1. Start from the county's official government website (stored in base_url).
      2. Crawl up to MAX_PAGES pages, collecting links.
      3. Download PDFs whose titles or surrounding text contain energy keywords.

    This is necessarily imprecise. All results should be reviewed by a human.
    """
    provider_name    = "generic"
    supported_states = []

    MAX_PAGES = 30
    MAX_PDF_SIZE_MB = 20

    def fetch_documents(self, fips: str) -> list[ScrapedDocument]:
        from db.database import get_db
        from db.models import CountyProvider

        with get_db() as db:
            cp = (
                db.query(CountyProvider)
                .filter_by(fips=fips, provider=self.provider_name)
                .first()
            )
            if not cp or not cp.base_url:
                log.warning("No base_url for generic provider on FIPS %s", fips)
                return []
            base_url = cp.base_url

        return self._crawl(base_url)

    def _crawl(self, start_url: str) -> list[ScrapedDocument]:
        visited: set[str] = set()
        queue = [start_url]
        domain = urlparse(start_url).netloc
        pdf_links: list[tuple[str, str]] = []  # (url, context_text)

        while queue and len(visited) < self.MAX_PAGES:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                resp = self._get(url)
                soup = BeautifulSoup(resp.content, "lxml")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    text = a.get_text(strip=True)
                    full = href if href.startswith("http") else urljoin(start_url, href)
                    parsed = urlparse(full)
                    if parsed.netloc != domain:
                        continue
                    if full.lower().endswith(".pdf"):
                        context = text + " " + (a.find_parent().get_text(" ", strip=True) if a.find_parent() else "")
                        if self._is_energy_related(context):
                            pdf_links.append((full, text))
                    elif full not in visited and len(visited) < self.MAX_PAGES:
                        queue.append(full)
            except Exception as exc:
                log.debug("Generic crawl error at %s: %s", url, exc)

        docs: list[ScrapedDocument] = []
        for pdf_url, title in dict.fromkeys([(u, t) for u, t in pdf_links]):
            try:
                resp = self._get(pdf_url, stream=True)
                content_length = int(resp.headers.get("content-length", 0))
                if content_length > self.MAX_PDF_SIZE_MB * 1024 * 1024:
                    log.debug("Skipping oversized PDF: %s", pdf_url)
                    continue
                docs.append(ScrapedDocument(
                    source_url=pdf_url,
                    raw_bytes=resp.content,
                    doc_type="other",
                    title=title or pdf_url.split("/")[-1],
                ))
            except Exception as exc:
                log.debug("Generic PDF download failed %s: %s", pdf_url, exc)

        log.info("Generic provider: %d PDFs found for %s", len(docs), start_url)
        return docs
