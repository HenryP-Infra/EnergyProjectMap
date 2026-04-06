"""
County profile panel — renders the full county data view with tabs:
  Ordinances & Setbacks | Permit History | Voting History | Documents | Run Scraper
"""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from db.database import get_db
from db.models import (
    County, Ordinance, Setback, Permit, Hearing, Vote, Document
)
from extractors.confidence import confidence_emoji, format_confidence, confidence_badge
from utils.fips import display_name, short_name


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_county_panel(fips: str) -> None:
    name = display_name(fips)
    st.header(f"📍 {name}")
    st.caption(f"FIPS {fips} · Share: `?fips={fips}`")

    tab_setbacks, tab_permits, tab_voting, tab_docs, tab_scraper = st.tabs([
        "🏗️ Ordinances & Setbacks",
        "📋 Permit History",
        "🗳️ Voting History",
        "📄 Documents",
        "⚙️ Run Scraper",
    ])

    with tab_setbacks:
        _render_setbacks(fips)
    with tab_permits:
        _render_permits(fips)
    with tab_voting:
        _render_voting(fips)
    with tab_docs:
        _render_documents(fips)
    with tab_scraper:
        _render_scraper(fips)


# ---------------------------------------------------------------------------
# Tab: Ordinances & Setbacks
# ---------------------------------------------------------------------------

def _render_setbacks(fips: str) -> None:
    with get_db() as db:
        ordinances = db.query(Ordinance).filter_by(county_fips=fips).all()
        setbacks   = db.query(Setback).filter_by(county_fips=fips).all()

        # Detach from session before we leave context
        ordinance_data = [
            {
                "Ordinance #":    o.ordinance_number or "—",
                "Title":          o.title or "—",
                "Energy Type":    (o.energy_type or "—").title(),
                "Adopted":        o.adopted_date.strftime("%Y-%m-%d") if o.adopted_date else "—",
                "Amended":        o.amended_date.strftime("%Y-%m-%d") if o.amended_date else "—",
                "Energy Overlay": "✅ Yes" if o.has_energy_overlay else "No",
                "Document":       o.doc_url or "",
            }
            for o in ordinances
        ]
        setback_data = [
            {
                "Project Type":  (s.project_type or "—").upper(),
                "Setback Type":  (s.setback_type or "—").replace("_", " ").title(),
                "Distance (ft)": s.distance_ft if s.distance_ft is not None else "—",
                "Source":        s.source_section or "—",
                "Notes":         s.notes or "",
                "Confidence":    format_confidence(s.confidence_score),
                "_confidence":   s.confidence_score,
                "Review":        "⚑ Pending" if s.needs_human_review else "✓",
                "Action":        s.review_action or "",
            }
            for s in setbacks
        ]

    # Ordinances
    st.subheader("Ordinances")
    if ordinance_data:
        st.dataframe(
            pd.DataFrame(ordinance_data),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No ordinance records found for this county yet. Use the **Run Scraper** tab to ingest documents.")

    st.divider()

    # Setbacks table
    st.subheader("Setback Requirements")

    if setback_data:
        # Project type filter
        types_available = sorted({r["Project Type"] for r in setback_data})
        selected_type = st.selectbox(
            "Filter by project type",
            ["All"] + types_available,
            key=f"sb_type_{fips}",
        )
        filtered = setback_data if selected_type == "All" else [
            r for r in setback_data if r["Project Type"] == selected_type
        ]

        # Render with confidence colour coding
        display_cols = [
            "Project Type", "Setback Type", "Distance (ft)",
            "Source", "Confidence", "Review"
        ]
        df = pd.DataFrame(filtered)[display_cols]

        st.dataframe(
            df.style.apply(
                lambda row: _confidence_row_style(filtered[row.name]["_confidence"]),
                axis=1,
            ),
            hide_index=True,
            use_container_width=True,
        )

        # Legend
        st.caption("✅ ≥90% verified · ⚠️ 75–89% pending review · 🔴 <75% low confidence")

        # Setback comparison chart
        numeric = [r for r in filtered if isinstance(r["Distance (ft)"], (int, float))]
        if numeric:
            fig = px.bar(
                pd.DataFrame(numeric),
                x="Setback Type",
                y="Distance (ft)",
                color="Project Type",
                barmode="group",
                title="Setback distances by type",
                height=350,
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_layout(margin=dict(t=40, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No setback records found. Run the scraper to extract setback data from county ordinances.")


def _confidence_row_style(score: float | None):
    if score is None:
        return [""] * 6
    if score >= 0.90:
        return ["background-color: #d4edda"] * 6
    if score >= 0.75:
        return ["background-color: #fff3cd"] * 6
    return ["background-color: #f8d7da"] * 6


# ---------------------------------------------------------------------------
# Tab: Permit History
# ---------------------------------------------------------------------------

def _render_permits(fips: str) -> None:
    with get_db() as db:
        permits = db.query(Permit).filter_by(county_fips=fips).order_by(
            Permit.application_date.desc()
        ).all()

        permit_rows = []
        for p in permits:
            hearings = db.query(Hearing).filter_by(permit_id=p.id).all()
            first_hearing = min(
                (h.hearing_date for h in hearings if h.hearing_date),
                default=None,
            )
            permit_rows.append({
                "Project":        p.project_name or "—",
                "Applicant":      p.applicant or "—",
                "Type":           p.permit_type or "—",
                "Energy":         (p.energy_type or "—").title(),
                "MW":             p.capacity_mw or "—",
                "Acres":          p.acreage or "—",
                "Applied":        p.application_date.strftime("%Y-%m-%d") if p.application_date else "—",
                "First Hearing":  first_hearing.strftime("%Y-%m-%d") if first_hearing else "—",
                "Outcome":        _outcome_emoji(p.outcome),
                "Appeal":         p.appeal_outcome or "—",
                "_outcome_raw":   p.outcome or "",
            })

    st.subheader("Permit History")

    if not permit_rows:
        st.info("No permit records found for this county. Run the scraper to import permit history.")
        return

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        energy_opts = sorted({r["Energy"] for r in permit_rows})
        energy_f = st.selectbox("Energy type", ["All"] + energy_opts, key=f"pe_{fips}")
    with col2:
        outcome_opts = sorted({r["_outcome_raw"] for r in permit_rows if r["_outcome_raw"]})
        outcome_f = st.selectbox("Outcome", ["All"] + outcome_opts, key=f"po_{fips}")
    with col3:
        type_opts = sorted({r["Type"] for r in permit_rows})
        type_f = st.selectbox("Permit type", ["All"] + type_opts, key=f"pt_{fips}")

    filtered = permit_rows
    if energy_f  != "All": filtered = [r for r in filtered if r["Energy"] == energy_f]
    if outcome_f != "All": filtered = [r for r in filtered if r["_outcome_raw"] == outcome_f]
    if type_f    != "All": filtered = [r for r in filtered if r["Type"] == type_f]

    display_cols = ["Project", "Applicant", "Type", "Energy", "MW",
                    "Applied", "First Hearing", "Outcome", "Appeal"]
    st.dataframe(pd.DataFrame(filtered)[display_cols], hide_index=True, use_container_width=True)
    st.caption(f"Showing {len(filtered)} of {len(permit_rows)} permits")

    # Outcome pie chart
    if permit_rows:
        outcome_counts = {}
        for r in permit_rows:
            o = r["_outcome_raw"] or "unknown"
            outcome_counts[o] = outcome_counts.get(o, 0) + 1

        fig = px.pie(
            names=list(outcome_counts.keys()),
            values=list(outcome_counts.values()),
            title="Permit outcomes",
            color_discrete_sequence=px.colors.qualitative.Pastel,
            height=300,
        )
        fig.update_layout(margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)


def _outcome_emoji(outcome: str | None) -> str:
    mapping = {
        "approved":  "✅ Approved",
        "denied":    "❌ Denied",
        "withdrawn": "↩️ Withdrawn",
        "appealed":  "⚖️ Appealed",
        "pending":   "⏳ Pending",
    }
    return mapping.get(outcome or "", "— Unknown")


# ---------------------------------------------------------------------------
# Tab: Voting History
# ---------------------------------------------------------------------------

def _render_voting(fips: str) -> None:
    with get_db() as db:
        permits = db.query(Permit).filter_by(county_fips=fips).all()
        hearing_rows = []
        for p in permits:
            hearings = db.query(Hearing).filter_by(permit_id=p.id).all()
            for h in hearings:
                votes = db.query(Vote).filter_by(hearing_id=h.id).all()
                hearing_rows.append({
                    "Date":    h.hearing_date.strftime("%Y-%m-%d") if h.hearing_date else "—",
                    "Project": p.project_name or "—",
                    "Energy":  (p.energy_type or "—").title(),
                    "Yes":     h.vote_yes,
                    "No":      h.vote_no,
                    "Abstain": h.vote_abstain,
                    "Margin":  h.vote_yes - h.vote_no,
                    "Outcome": _outcome_emoji(p.outcome),
                    "Member votes": ", ".join(
                        f"{v.member_name} ({v.vote})" for v in votes
                    ) or "—",
                    "_date_raw": h.hearing_date,
                })

    st.subheader("Voting History")

    if not hearing_rows:
        st.info("No hearing records found for this county.")
        return

    hearing_rows.sort(key=lambda r: r["_date_raw"] or datetime.min, reverse=True)
    df = pd.DataFrame(hearing_rows).drop(columns=["_date_raw"])
    st.dataframe(df, hide_index=True, use_container_width=True)

    # Trend chart
    if hearing_rows:
        trend_data = [r for r in hearing_rows if r["Date"] != "—"]
        if trend_data:
            fig = go.Figure()
            dates  = [r["Date"] for r in trend_data]
            yes_v  = [r["Yes"] for r in trend_data]
            no_v   = [r["No"] for r in trend_data]

            fig.add_trace(go.Bar(name="Yes", x=dates, y=yes_v, marker_color="#4CAF50"))
            fig.add_trace(go.Bar(name="No",  x=dates, y=no_v,  marker_color="#F44336"))
            fig.update_layout(
                barmode="group",
                title="Vote counts by hearing date",
                height=300,
                margin=dict(t=40, b=20, l=20, r=20),
            )
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Tab: Documents
# ---------------------------------------------------------------------------

def _render_documents(fips: str) -> None:
    with get_db() as db:
        docs = db.query(Document).filter_by(county_fips=fips).order_by(
            Document.extracted_at.desc()
        ).all()

        doc_rows = [
            {
                "Title":      d.title or d.source_url.split("/")[-1][:80],
                "Type":       (d.doc_type or "—").replace("_", " ").title(),
                "Provider":   d.provider or "—",
                "Extracted":  d.extracted_at.strftime("%Y-%m-%d") if d.extracted_at else "—",
                "Confidence": format_confidence(d.document_confidence),
                "Review":     "⚑ Flagged" if d.needs_human_review else "✓",
                "Source URL": d.source_url or "",
                "Trace ID":   d.langfuse_trace_id or "",
                "_conf":      d.document_confidence,
            }
            for d in docs
        ]

    st.subheader("Document Index")

    if not doc_rows:
        st.info("No documents ingested yet. Run the scraper to fetch county documents.")
        return

    # Filter
    type_opts = sorted({r["Type"] for r in doc_rows})
    type_f = st.selectbox("Filter by type", ["All"] + type_opts, key=f"dt_{fips}")
    review_f = st.checkbox("Show flagged only", key=f"dr_{fips}")

    filtered = doc_rows
    if type_f   != "All": filtered = [r for r in filtered if r["Type"] == type_f]
    if review_f:           filtered = [r for r in filtered if "⚑" in r["Review"]]

    for row in filtered:
        with st.expander(f"**{row['Title']}** — {row['Type']} ({row['Extracted']})"):
            col1, col2, col3 = st.columns(3)
            col1.metric("Provider",   row["Provider"])
            col2.metric("Confidence", row["Confidence"])
            col3.metric("Review",     row["Review"])

            if row["Source URL"]:
                st.markdown(f"[📄 View source document]({row['Source URL']})")
            if row["Trace ID"]:
                from config import settings
                trace_url = f"{settings.langfuse_host}/traces/{row['Trace ID']}"
                st.markdown(f"[🔍 View Langfuse trace]({trace_url})")


# ---------------------------------------------------------------------------
# Tab: Run Scraper
# ---------------------------------------------------------------------------

def _render_scraper(fips: str) -> None:
    from config import settings

    st.subheader("Run Document Scraper")
    name = display_name(fips)

    st.markdown(f"""
Triggers the full scraping pipeline for **{name}**:

1. Fetches documents from all configured providers
2. Computes SHA-256 hash — skips unchanged documents
3. Extracts structured data with Claude API
4. Flags setbacks with confidence < 90% for human review
5. Traces every extraction in Langfuse
""")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Anthropic API", "✅ Configured" if settings.anthropic_enabled else "❌ Not configured")
    with col2:
        st.metric("Langfuse tracing", "✅ Enabled" if settings.langfuse_enabled else "⚠️ Disabled")

    if not settings.anthropic_enabled:
        st.warning("Set ANTHROPIC_API_KEY in your .env file to enable Claude extraction.")

    if st.button(f"🚀 Scrape {short_name(fips)}", type="primary", key=f"scrape_{fips}"):
        from scrapers.runner import run_county

        status_box = st.empty()
        log_lines:  list[str] = []

        def _progress(msg: str):
            log_lines.append(msg)
            status_box.code("\n".join(log_lines[-20:]), language=None)

        with st.spinner("Running scraper..."):
            try:
                summary = run_county(fips, progress_cb=_progress)
                st.success(
                    f"✅ Complete — "
                    f"fetched: {summary['fetched']}, "
                    f"skipped: {summary['skipped']}, "
                    f"extracted: {summary['extracted']}, "
                    f"errors: {summary['errors']}"
                )
            except Exception as exc:
                st.error(f"Scraper error: {exc}")
