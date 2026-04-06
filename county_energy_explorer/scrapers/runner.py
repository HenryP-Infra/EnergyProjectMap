"""
Pipeline runner — orchestrates scraping → hash gating → extraction → DB write.

Can be run manually (python -m scrapers.runner <fips>) or called from the
Streamlit admin panel's "Trigger Scrape" button.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Callable

import fitz  # PyMuPDF

from config import settings
from db.database import get_db
from db.models import County, Document, Ordinance, Permit, Hearing, Vote, Setback
from extractors.hash_gate import compute_hash, should_extract, upsert_document
from extractors.claude_extractor import extract_document
from scrapers.registry import get_providers
from scrapers.base import ScrapedDocument
from utils.fips import resolve_fips

log = logging.getLogger(__name__)


def run_county(
    fips: str,
    progress_cb: Callable[[str], None] | None = None,
) -> dict:
    """
    Full pipeline for a single county:
      1. Ensure the county record exists in DB.
      2. Retrieve all configured providers.
      3. For each provider, fetch documents.
      4. Hash-gate each document.
      5. Extract changed/new documents with Claude.
      6. Persist results.

    progress_cb — optional callable(message) for Streamlit progress updates.

    Returns a summary dict with counts.
    """
    def _log(msg: str):
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    summary = {"fetched": 0, "skipped": 0, "extracted": 0, "errors": 0}

    info = resolve_fips(fips)
    if not info:
        _log(f"Unknown FIPS: {fips}")
        return summary

    _ensure_county(fips, info)
    providers = get_providers(fips)
    _log(f"Running {len(providers)} provider(s) for {info['county_name']}, {info['state_abbr']}")

    for provider in providers:
        _log(f"Fetching from {provider.provider_name}...")
        try:
            scraped_docs = provider.fetch_documents(fips)
            _log(f"  → {len(scraped_docs)} documents found")
        except Exception as exc:
            log.error("Provider %s failed: %s", provider.provider_name, exc)
            summary["errors"] += 1
            continue

        for sdoc in scraped_docs:
            summary["fetched"] += 1
            new_hash = compute_hash(sdoc.raw_bytes)

            with get_db() as db:
                do_extract, doc_id = should_extract(fips, sdoc.source_url, new_hash, db)

            if not do_extract:
                summary["skipped"] += 1
                _log(f"  Skipped (unchanged): {sdoc.source_url[:80]}")
                continue

            # Extract text from PDF bytes
            raw_text = _extract_pdf_text(sdoc.raw_bytes)

            if not settings.anthropic_enabled:
                _log("  [ANTHROPIC_API_KEY not set — skipping Claude extraction]")
                with get_db() as db:
                    upsert_document(
                        fips=fips,
                        source_url=sdoc.source_url,
                        raw_bytes=sdoc.raw_bytes,
                        doc_type=sdoc.doc_type,
                        title=sdoc.title,
                        provider=provider.provider_name,
                        db=db,
                    )
                continue

            try:
                _log(f"  Extracting: {sdoc.title[:70]}...")
                result = extract_document(
                    raw_text=raw_text,
                    fips=fips,
                    doc_id=doc_id,
                    source_url=sdoc.source_url,
                    doc_type=sdoc.doc_type,
                    provider=provider.provider_name,
                )
                _persist_extraction(fips, sdoc, raw_text, result, provider.provider_name)
                summary["extracted"] += 1
            except Exception as exc:
                log.error("Extraction failed for %s: %s", sdoc.source_url, exc)
                summary["errors"] += 1

    _log(
        f"Done — fetched: {summary['fetched']}, "
        f"skipped: {summary['skipped']}, "
        f"extracted: {summary['extracted']}, "
        f"errors: {summary['errors']}"
    )
    return summary


def _ensure_county(fips: str, info: dict) -> None:
    with get_db() as db:
        existing = db.query(County).filter_by(fips=fips).first()
        if not existing:
            db.add(County(
                fips=fips,
                name=info["county_name"],
                state_name=info["state_name"],
                state_abbr=info["state_abbr"],
            ))


def _extract_pdf_text(raw_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception:
        # If not a PDF, try to decode as UTF-8 text
        try:
            return raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            return ""


def _persist_extraction(
    fips: str,
    sdoc: ScrapedDocument,
    raw_text: str,
    result: dict,
    provider_name: str,
) -> None:
    with get_db() as db:
        # Upsert Document record
        doc = upsert_document(
            fips=fips,
            source_url=sdoc.source_url,
            raw_bytes=sdoc.raw_bytes,
            doc_type=result.get("document_type", sdoc.doc_type),
            title=result.get("project_name") or sdoc.title,
            provider=provider_name,
            db=db,
        )
        doc.raw_text = raw_text[:500_000]   # guard against huge text
        doc.extracted_at = datetime.utcnow()
        doc.document_confidence = result.get("document_confidence")
        doc.needs_human_review = result.get("needs_human_review", False)
        doc.langfuse_trace_id = result.get("_langfuse_trace_id")
        doc.extracted_json = json.dumps(result)

        db.flush()  # get doc.id

        doc_type = result.get("document_type", "other")

        if doc_type == "ordinance":
            _persist_ordinance(fips, result, db)
        elif doc_type in ("SUP", "CUP"):
            _persist_permit(fips, result, doc.id, db)


def _persist_ordinance(fips: str, result: dict, db) -> None:
    from datetime import datetime

    def _parse_date(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None

    ord_obj = Ordinance(
        county_fips=fips,
        ordinance_number=result.get("ordinance_number"),
        title=result.get("project_name"),
        energy_type=result.get("energy_type"),
        adopted_date=_parse_date(result.get("ordinance_adoption_date")),
        doc_url=None,
    )
    db.add(ord_obj)
    db.flush()

    for sb in result.get("setbacks") or []:
        db.add(Setback(
            ordinance_id=ord_obj.id,
            county_fips=fips,
            project_type=sb.get("project_type"),
            setback_type=sb.get("setback_type"),
            distance_ft=sb.get("distance_ft"),
            source_section=sb.get("source_section"),
            notes=sb.get("notes"),
            confidence_score=sb.get("confidence_score", 1.0),
            confidence_reason=sb.get("confidence_reason"),
            needs_human_review=sb.get("needs_human_review", False),
        ))


def _persist_permit(fips: str, result: dict, doc_id: int, db) -> None:
    from datetime import datetime

    def _parse_date(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None

    permit = Permit(
        county_fips=fips,
        project_name=result.get("project_name"),
        applicant=result.get("applicant_name"),
        permit_type=result.get("document_type"),
        energy_type=result.get("energy_type"),
        capacity_mw=result.get("capacity_mw"),
        acreage=result.get("acreage"),
        application_date=_parse_date(result.get("application_date")),
        outcome=result.get("outcome"),
        doc_url=None,
    )
    db.add(permit)
    db.flush()

    for hearing_date_str in result.get("hearing_dates") or []:
        hearing = Hearing(
            permit_id=permit.id,
            hearing_date=_parse_date(hearing_date_str),
            vote_yes=sum(1 for v in result.get("vote_record") or [] if v.get("vote") == "yes"),
            vote_no=sum(1 for v in result.get("vote_record") or [] if v.get("vote") == "no"),
            vote_abstain=sum(1 for v in result.get("vote_record") or [] if v.get("vote") in ("abstain", "recuse")),
            conditions=json.dumps(result.get("conditions_of_approval") or []),
            denial_reasons=json.dumps(result.get("denial_reasons") or []),
        )
        db.add(hearing)
        db.flush()

        for vote_entry in result.get("vote_record") or []:
            db.add(Vote(
                hearing_id=hearing.id,
                member_name=vote_entry.get("member"),
                vote=vote_entry.get("vote"),
            ))


if __name__ == "__main__":
    import sys
    from db.database import init_db

    logging.basicConfig(level=logging.INFO)
    init_db()

    fips_arg = sys.argv[1] if len(sys.argv) > 1 else "48113"
    run_county(fips_arg, progress_cb=print)
