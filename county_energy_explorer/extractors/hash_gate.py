"""
Document hash gating.

Before running Claude extraction on any document, compute the SHA-256 hash
of its raw bytes and compare with the stored hash.  Extraction is only
triggered when the document has changed (or is new).

This prevents re-extracting documents that haven't changed since the last
scrape, keeping API costs low on scheduled re-runs.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def compute_hash(raw_bytes: bytes) -> str:
    """Return the SHA-256 hex digest of raw_bytes."""
    return hashlib.sha256(raw_bytes).hexdigest()


def should_extract(
    fips: str,
    source_url: str,
    new_hash: str,
    db: Session,
) -> tuple[bool, int | None]:
    """
    Check whether this document needs (re-)extraction.

    Returns:
        (True, None)         — new document, extraction needed
        (True, document_id)  — existing document with changed content
        (False, document_id) — existing document, hash unchanged, skip

    Always updates hash_checked_at.  Updates doc_hash only when changed.
    """
    from db.models import Document

    doc = db.query(Document).filter_by(county_fips=fips, source_url=source_url).first()

    now = datetime.utcnow()

    if doc is None:
        # Brand new document — will be inserted by the runner after extraction
        log.info("New document detected: %s", source_url)
        return True, None

    doc.hash_checked_at = now

    if doc.doc_hash != new_hash:
        log.info("Document changed, re-extracting: %s", source_url)
        doc.doc_hash = new_hash
        db.commit()
        return True, doc.id

    log.debug("Document unchanged, skipping: %s", source_url)
    db.commit()
    return False, doc.id


def upsert_document(
    fips: str,
    source_url: str,
    raw_bytes: bytes,
    doc_type: str,
    title: str,
    provider: str,
    db: Session,
) -> "Document":  # noqa: F821
    """
    Insert or update a Document record.  Sets doc_hash from raw_bytes.
    Returns the Document ORM object (not yet committed).
    """
    from db.models import Document

    doc_hash = compute_hash(raw_bytes)
    now = datetime.utcnow()

    doc = db.query(Document).filter_by(county_fips=fips, source_url=source_url).first()
    if doc is None:
        doc = Document(county_fips=fips, source_url=source_url)
        db.add(doc)

    doc.doc_type = doc_type
    doc.title = title
    doc.provider = provider
    doc.doc_hash = doc_hash
    doc.hash_checked_at = now

    return doc
