"""
Admin Review Dashboard — page 2 of 3.

Shows all setback records flagged for human review (needs_human_review=True).
Reviewers can confirm, edit, or reject each value.
Links to the Langfuse trace for each extraction that produced a low-confidence flag.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from db.database import get_db
from db.models import Setback, Document
from extractors.confidence import confidence_badge, format_confidence
from utils.fips import display_name

st.set_page_config(
    page_title="Admin Review — Energy Permit Explorer",
    page_icon="🔍",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Auth — simple password gate
# ---------------------------------------------------------------------------
from config import settings

if "admin_authed" not in st.session_state:
    st.session_state.admin_authed = False

if not st.session_state.admin_authed:
    st.title("🔍 Admin Review Dashboard")
    pwd = st.text_input("Admin password", type="password")
    if st.button("Log in"):
        if pwd == settings.admin_password:
            st.session_state.admin_authed = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------

st.title("🔍 Admin Review Dashboard")
st.caption("Review and approve AI-extracted setback values with confidence < 90%.")

# ---------------------------------------------------------------------------
# Load flagged records
# ---------------------------------------------------------------------------

with get_db() as db:
    flagged = (
        db.query(Setback)
        .filter(
            Setback.needs_human_review == True,
            Setback.review_action == None,
        )
        .order_by(Setback.confidence_score.asc())
        .all()
    )

    # Build display rows — detach from session
    rows = []
    for s in flagged:
        # Get the document's Langfuse trace via the ordinance → county path
        doc = (
            db.query(Document)
            .filter_by(county_fips=s.county_fips)
            .filter(Document.needs_human_review == True)
            .first()
        )
        trace_id = doc.langfuse_trace_id if doc else None

        rows.append({
            "id":               s.id,
            "county":           display_name(s.county_fips),
            "fips":             s.county_fips,
            "project_type":     (s.project_type or "—").upper(),
            "setback_type":     (s.setback_type or "—").replace("_", " ").title(),
            "distance_ft":      s.distance_ft,
            "confidence_score": s.confidence_score,
            "confidence_reason":s.confidence_reason or "",
            "source_section":   s.source_section or "",
            "trace_id":         trace_id,
        })

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

col1, col2, col3 = st.columns(3)

with col1:
    counties_avail = sorted({r["county"] for r in rows})
    county_f = st.selectbox("County", ["All"] + counties_avail)

with col2:
    band_f = st.selectbox("Confidence band", [
        "All", "< 50%", "50–75%", "75–90%"
    ])

with col3:
    type_f = st.selectbox("Project type", ["All", "SOLAR", "WIND", "BESS"])

filtered = rows
if county_f != "All":
    filtered = [r for r in filtered if r["county"] == county_f]
if type_f != "All":
    filtered = [r for r in filtered if r["project_type"] == type_f]
if band_f != "All":
    if band_f == "< 50%":
        filtered = [r for r in filtered if (r["confidence_score"] or 0) < 0.50]
    elif band_f == "50–75%":
        filtered = [r for r in filtered if 0.50 <= (r["confidence_score"] or 0) < 0.75]
    else:
        filtered = [r for r in filtered if 0.75 <= (r["confidence_score"] or 0) < 0.90]

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------

mcol1, mcol2, mcol3 = st.columns(3)
mcol1.metric("Total flagged", len(rows))
mcol2.metric("Shown (filtered)", len(filtered))
avg_conf = (
    sum(r["confidence_score"] or 0 for r in filtered) / len(filtered)
    if filtered else 0
)
mcol3.metric("Avg confidence", f"{avg_conf*100:.0f}%")

st.divider()

# ---------------------------------------------------------------------------
# Review cards
# ---------------------------------------------------------------------------

if not filtered:
    st.success("🎉 No records require review with the current filters.")
    st.stop()

for row in filtered:
    label, color = confidence_badge(row["confidence_score"])

    with st.expander(
        f"**{row['county']}** — {row['project_type']} · {row['setback_type']} "
        f"· {row['distance_ft']} ft · :{color}[{label} {format_confidence(row['confidence_score'])}]",
        expanded=False,
    ):
        col_info, col_actions = st.columns([2, 1])

        with col_info:
            st.markdown(f"**County:** {row['county']} (FIPS `{row['fips']}`)")
            st.markdown(f"**Project type:** {row['project_type']}")
            st.markdown(f"**Setback type:** {row['setback_type']}")
            st.markdown(f"**Extracted value:** {row['distance_ft']} ft")
            st.markdown(f"**Confidence:** {format_confidence(row['confidence_score'])}")
            if row["confidence_reason"]:
                st.info(f"⚠️ **Reason for uncertainty:** {row['confidence_reason']}")
            if row["source_section"]:
                st.caption(f"Source section: {row['source_section']}")
            if row["trace_id"]:
                trace_url = f"{settings.langfuse_host}/traces/{row['trace_id']}"
                st.markdown(f"[🔍 View Langfuse trace]({trace_url})")
            # Link back to county view
            st.markdown(f"[🗺️ View county profile](?fips={row['fips']})")

        with col_actions:
            st.markdown("**Review action**")
            new_value = st.number_input(
                "Correct value (ft)",
                value=float(row["distance_ft"] or 0),
                step=1.0,
                key=f"val_{row['id']}",
            )
            reviewer = st.text_input(
                "Your name / ID",
                placeholder="reviewer123",
                key=f"rev_{row['id']}",
            )

            bcol1, bcol2, bcol3 = st.columns(3)

            if bcol1.button("✅ Confirm", key=f"confirm_{row['id']}"):
                _apply_review(row["id"], "confirmed", row["distance_ft"], reviewer)

            if bcol2.button("✏️ Edit", key=f"edit_{row['id']}"):
                _apply_review(row["id"], "edited", new_value, reviewer)

            if bcol3.button("🗑️ Reject", key=f"reject_{row['id']}"):
                _apply_review(row["id"], "rejected", None, reviewer)


def _apply_review(setback_id: int, action: str, value, reviewer: str) -> None:
    with get_db() as db:
        s = db.query(Setback).filter_by(id=setback_id).first()
        if s:
            s.review_action     = action
            s.reviewed_by       = reviewer or "admin"
            s.reviewed_at       = datetime.utcnow()
            s.needs_human_review = False
            if action == "edited" and value is not None:
                s.distance_ft   = value
                s.confidence_score = 1.0   # human-confirmed
            elif action == "rejected":
                s.distance_ft   = None
    st.success(f"Saved: {action}")
    st.rerun()

# ---------------------------------------------------------------------------
# Bulk export
# ---------------------------------------------------------------------------

st.divider()
if st.button("📥 Export flagged records as CSV"):
    df = pd.DataFrame(filtered).drop(columns=["id", "fips", "trace_id"])
    csv = df.to_csv(index=False)
    st.download_button(
        "Download CSV",
        data=csv,
        file_name="flagged_setbacks.csv",
        mime="text/csv",
    )
