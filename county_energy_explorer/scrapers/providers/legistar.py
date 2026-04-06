"""
LegistarProvider — fetches meeting records and documents from the Legistar REST API.

Legistar is used by many county and city governments.
API base: https://webapi.legistar.com/v1/{client}/
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from urllib.parse import quote

from scrapers.base import BaseScraper, ScrapedDocument

log = logging.getLogger(__name__)

_API_BASE = "https://webapi.legistar.com/v1/{client}"


class LegistarProvider(BaseScraper):
    provider_name    = "legistar"
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
            client = config.get("client", "")
            if not client:
                return []

        return self._fetch_for_client(client)

    def _fetch_for_client(self, client: str) -> list[ScrapedDocument]:
        base = _API_BASE.format(client=client)
        docs: list[ScrapedDocument] = []

        # Search matters (agenda items) for energy keywords
        for keyword in ["solar", "wind", "energy", "special use", "conditional use",
                        "battery storage", "photovoltaic", "turbine"]:
            try:
                url = (
                    f"{base}/Matters"
                    f"?$filter=contains(MatterTitle,'{quote(keyword)}')"
                    f"&$top=100&$select=MatterId,MatterTitle,MatterTypeName"
                )
                resp = self._get(url)
                matters = resp.json()
                for matter in matters:
                    mid = matter.get("MatterId")
                    title = matter.get("MatterTitle", "")
                    if not mid or not self._is_energy_related(title):
                        continue
                    # Fetch attachments for each matter
                    attach_docs = self._fetch_matter_attachments(base, mid, title)
                    docs.extend(attach_docs)
            except Exception as exc:
                log.warning("Legistar keyword '%s' fetch failed: %s", keyword, exc)

        # Deduplicate by source_url
        seen: set[str] = set()
        unique: list[ScrapedDocument] = []
        for d in docs:
            if d.source_url not in seen:
                seen.add(d.source_url)
                unique.append(d)

        log.info("Legistar: fetched %d unique docs for client %s", len(unique), client)
        return unique

    def _fetch_matter_attachments(
        self, base: str, matter_id: int, matter_title: str
    ) -> list[ScrapedDocument]:
        docs: list[ScrapedDocument] = []
        try:
            url = f"{base}/Matters/{matter_id}/Attachments"
            resp = self._get(url)
            attachments = resp.json()
            for att in attachments:
                file_url = att.get("MatterAttachmentHyperlink")
                att_name = att.get("MatterAttachmentName", "attachment")
                if not file_url:
                    continue
                doc_type = self._classify_doc_type(att_name)
                try:
                    file_resp = self._get(file_url)
                    docs.append(ScrapedDocument(
                        source_url=file_url,
                        raw_bytes=file_resp.content,
                        doc_type=doc_type,
                        title=f"{matter_title} — {att_name}",
                        extra_meta={"matter_id": matter_id},
                    ))
                except Exception as exc:
                    log.debug("Attachment download failed %s: %s", file_url, exc)
        except Exception as exc:
            log.debug("Attachments fetch failed for matter %s: %s", matter_id, exc)
        return docs

    def _classify_doc_type(self, name: str) -> str:
        lower = name.lower()
        if "minutes" in lower:
            return "minutes"
        if "resolution" in lower:
            return "resolution"
        if "staff" in lower or "report" in lower:
            return "staff_report"
        if "ordinance" in lower:
            return "ordinance"
        return "other"
