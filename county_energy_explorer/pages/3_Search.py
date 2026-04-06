"""
Full-Text Document Search — page 3 of 3.

Searches raw_text across all ingested documents using:
  - PostgreSQL: native tsvector GIN index (ts_rank ordering)
  - SQLite: LIKE-based fallback

Results include highlighted snippets and links to county profiles.
"""
from __future__ import annotations

import re

import streamlit as st

from config import settings
from db.database import get_db, engine
from db.models import Document
from utils.fips import display_name, short_name

st.set_page_config(
    page_title="Document Search — Energy Permit Explorer",
    page_icon="🔎",
    layout="wide",
)

st.title("🔎 Full-Text Document Search")
st.caption("Search across all ingested county ordinances, staff reports, resolutions, and meeting minutes.")

# ---------------------------------------------------------------------------
# Search input
# ---------------------------------------------------------------------------

col1, col2, col3 = st.columns([3, 1, 1])

with col1:
    query = st.text_input(
        "Search keywords",
        placeholder="e.g.  solar setback 500 feet  or  wind turbine special use",
        key="search_query",
    )
with col2:
    county_filter = st.text_input("FIPS filter (optional)", placeholder="48113", key="fips_filter")
with col3:
    doc_type_filter = st.selectbox(
        "Doc type",
        ["All", "Ordinance", "Staff Report", "Minutes", "Resolution", "Other"],
        key="doc_type_filter",
    )

max_results = st.slider("Max results", min_value=10, max_value=100, value=25, step=5)

# ---------------------------------------------------------------------------
# Search execution
# ---------------------------------------------------------------------------

def _highlight(text: str, query: str, window: int = 200) -> str:
    """
    Extract a snippet of `text` around the first occurrence of any query term,
    and wrap matches in <mark> tags for display.
    """
    terms = [t for t in query.lower().split() if len(t) > 2]
    if not terms or not text:
        return text[:window] + "…" if text and len(text) > window else (text or "")

    lower_text = text.lower()
    first_pos  = len(text)
    for term in terms:
        pos = lower_text.find(term)
        if 0 <= pos < first_pos:
            first_pos = pos

    start   = max(0, first_pos - 80)
    end     = min(len(text), first_pos + window)
    snippet = ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")

    for term in terms:
        snippet = re.sub(
            f"({re.escape(term)})",
            r"<mark>\1</mark>",
            snippet,
            flags=re.IGNORECASE,
        )
    return snippet


def _search_postgres(query: str, fips: str | None, doc_type: str | None, limit: int) -> list[dict]:
    from sqlalchemy import text

    type_map = {
        "Ordinance":    "ordinance",
        "Staff Report": "staff_report",
        "Minutes":      "minutes",
        "Resolution":   "resolution",
        "Other":        "other",
    }
    dtype = type_map.get(doc_type) if doc_type and doc_type != "All" else None

    sql_parts = [
        """
        SELECT
            d.id,
            d.county_fips,
            d.title,
            d.doc_type,
            d.source_url,
            d.extracted_at,
            d.document_confidence,
            d.needs_human_review,
            d.langfuse_trace_id,
            ts_headline(
                'english',
                coalesce(d.raw_text, ''),
                plainto_tsquery('english', :q),
                'StartSel=<mark>, StopSel=</mark>, MaxWords=40, MinWords=15'
            ) AS snippet,
            ts_rank(d.raw_text_tsv, plainto_tsquery('english', :q)) AS rank
        FROM documents d
        WHERE d.raw_text_tsv @@ plainto_tsquery('english', :q)
        """
    ]
    params: dict = {"q": query, "limit": limit}

    if fips:
        sql_parts.append("AND d.county_fips = :fips")
        params["fips"] = fips.zfill(5)
    if dtype:
        sql_parts.append("AND d.doc_type = :dtype")
        params["dtype"] = dtype

    sql_parts.append("ORDER BY rank DESC LIMIT :limit")
    sql = " ".join(sql_parts)

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    return [dict(r._mapping) for r in rows]


def _search_sqlite(query: str, fips: str | None, doc_type: str | None, limit: int) -> list[dict]:
    """LIKE-based fallback for SQLite."""
    with get_db() as db:
        q = db.query(Document).filter(Document.raw_text.isnot(None))

        terms = [t for t in query.split() if len(t) > 2]
        for term in terms:
            q = q.filter(Document.raw_text.ilike(f"%{term}%"))

        if fips:
            q = q.filter(Document.county_fips == fips.zfill(5))

        type_map = {
            "Ordinance":    "ordinance",
            "Staff Report": "staff_report",
            "Minutes":      "minutes",
            "Resolution":   "resolution",
            "Other":        "other",
        }
        dtype = type_map.get(doc_type) if doc_type and doc_type != "All" else None
        if dtype:
            q = q.filter(Document.doc_type == dtype)

        docs = q.limit(limit).all()
        return [
            {
                "id":                  d.id,
                "county_fips":         d.county_fips,
                "title":               d.title,
                "doc_type":            d.doc_type,
                "source_url":          d.source_url,
                "extracted_at":        d.extracted_at,
                "document_confidence": d.document_confidence,
                "needs_human_review":  d.needs_human_review,
                "langfuse_trace_id":   d.langfuse_trace_id,
                "snippet":             _highlight(d.raw_text or "", query),
                "rank":                0,
            }
            for d in docs
        ]


def _do_search(query: str, fips: str, doc_type: str, limit: int) -> list[dict]:
    is_postgres = settings.database_url.startswith("postgresql")
    fips_val    = fips.strip() if fips.strip() else None
    if is_postgres:
        return _search_postgres(query, fips_val, doc_type, limit)
    return _search_sqlite(query, fips_val, doc_type, limit)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

if query and len(query.strip()) >= 2:
    with st.spinner("Searching..."):
        try:
            results = _do_search(query.strip(), county_filter, doc_type_filter, max_results)
        except Exception as exc:
            st.error(f"Search error: {exc}")
            results = []

    if not results:
        st.info("No documents matched your query. Try different keywords or run the scraper to ingest more documents.")
    else:
        is_pg = settings.database_url.startswith("postgresql")
        st.success(
            f"Found **{len(results)}** document(s)"
            + (" using PostgreSQL full-text search (GIN index)" if is_pg else " (SQLite keyword match)")
        )

        # Group by county
        by_county: dict[str, list[dict]] = {}
        for r in results:
            fips_key = r["county_fips"]
            by_county.setdefault(fips_key, []).append(r)

        for fips_key, county_results in by_county.items():
            county_label = display_name(fips_key)
            st.subheader(f"📍 {county_label}")

            for r in county_results:
                doc_type_label = (r.get("doc_type") or "document").replace("_", " ").title()
                conf           = r.get("document_confidence")
                conf_str       = f"{conf*100:.0f}%" if conf is not None else "—"
                review_flag    = " · ⚑ Needs review" if r.get("needs_human_review") else ""
                ext_date       = (
                    r["extracted_at"].strftime("%Y-%m-%d")
                    if r.get("extracted_at") else "—"
                )

                title = r.get("title") or (r.get("source_url", "").split("/")[-1]) or "Untitled"

                with st.expander(
                    f"**{title}** — {doc_type_label} · confidence {conf_str}{review_flag}"
                ):
                    # Highlighted snippet
                    snippet = r.get("snippet", "")
                    if snippet:
                        st.markdown(
                            f"<div style='background:#f8f9fa;padding:10px 14px;"
                            f"border-left:3px solid #0d6efd;border-radius:4px;"
                            f"font-size:14px;line-height:1.6'>{snippet}</div>",
                            unsafe_allow_html=True,
                        )

                    st.markdown("")  # spacer
                    col_a, col_b, col_c = st.columns(3)
                    col_a.markdown(f"**Extracted:** {ext_date}")
                    col_b.markdown(f"**Provider:** {r.get('provider', '—')}")
                    col_c.markdown(f"**Confidence:** {conf_str}")

                    link_col1, link_col2, link_col3 = st.columns(3)
                    if r.get("source_url"):
                        link_col1.markdown(f"[📄 Source document]({r['source_url']})")
                    link_col2.page_link(
                        "app.py",
                        label=f"🗺️ {short_name(fips_key)}",
                        icon=None,
                    )
                    if r.get("langfuse_trace_id"):
                        trace_url = f"{settings.langfuse_host}/traces/{r['langfuse_trace_id']}"
                        link_col3.markdown(f"[🔍 Langfuse trace]({trace_url})")

elif query:
    st.warning("Please enter at least 2 characters.")
else:
    # Show recent documents as a default view
    with get_db() as db:
        recent = (
            db.query(Document)
            .filter(Document.raw_text.isnot(None))
            .order_by(Document.extracted_at.desc())
            .limit(10)
            .all()
        )

    if recent:
        st.markdown("#### Recently ingested documents")
        for d in recent:
            ext = d.extracted_at.strftime("%Y-%m-%d") if d.extracted_at else "—"
            st.markdown(
                f"- **{display_name(d.county_fips)}** · "
                f"{(d.doc_type or '').replace('_', ' ').title()} · "
                f"{d.title or 'Untitled'} · _{ext}_"
            )
    else:
        st.info("No documents ingested yet. Use the **Run Scraper** tab on a county profile to begin.")
