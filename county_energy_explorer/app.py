"""
County Energy Permit Explorer — main Streamlit entry point.

Page 1 of 3: interactive US county map.
Clicking a county sets ?fips=XXXXX in the URL so the view is shareable.
The county profile panel is shown below the map when a county is selected.
"""
from __future__ import annotations

import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
import json

from db.database import init_db
from utils.fips import display_name, short_name, resolve_fips, all_counties, fips_from_display
from components.county_panel import render_county_panel

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="County Energy Permit Explorer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# DB boot
# ---------------------------------------------------------------------------
@st.cache_resource
def _init():
    init_db()

_init()

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    .main .block-container { padding-top: 1rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 6px; }
    .stTabs [data-baseweb="tab"] { padding: 6px 16px; }
    .confidence-verified   { background:#d4edda; color:#155724; padding:2px 8px; border-radius:4px; font-size:12px; }
    .confidence-pending    { background:#fff3cd; color:#856404; padding:2px 8px; border-radius:4px; font-size:12px; }
    .confidence-low        { background:#f8d7da; color:#721c24; padding:2px 8px; border-radius:4px; font-size:12px; }
    .review-flag           { background:#cce5ff; color:#004085; padding:2px 8px; border-radius:4px; font-size:12px; }
    h1 { font-size: 1.6rem !important; }
    h2 { font-size: 1.3rem !important; }
    h3 { font-size: 1.1rem !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar — county search + app info
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("⚡ Energy Permit Explorer")
    st.caption("Click any county on the map, or search below.")
    st.divider()

    # Search by name
    all_cty = all_counties()
    display_names = [c["display_name"] for c in all_cty]
    selected_display = st.selectbox(
        "Search county",
        options=[""] + display_names,
        format_func=lambda x: x if x else "— select a county —",
        key="county_search",
    )

    if selected_display:
        found_fips = fips_from_display(selected_display)
        if found_fips:
            st.query_params["fips"] = found_fips

    st.divider()
    st.markdown("""
**About**

This tool aggregates publicly available county-level documents for energy
project permitting:

- 🗺️ **Ordinances & setbacks** — solar, wind, BESS
- 📋 **Permit history** — SUPs, CUPs, hearing dates
- 🗳️ **Voting records** — member-level votes
- 📄 **Documents** — staff reports, resolutions, minutes
""")
    st.divider()
    st.page_link("pages/2_Admin_Review.py",  label="🔍 Admin Review Dashboard")
    st.page_link("pages/3_Search.py",        label="🔎 Full-Text Document Search")

# ---------------------------------------------------------------------------
# Resolve active FIPS from URL query param
# ---------------------------------------------------------------------------
active_fips: str | None = st.query_params.get("fips")

# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def _load_geojson() -> dict:
    """Load US county GeoJSON from the Census Bureau (cached 24 h)."""
    url = (
        "https://raw.githubusercontent.com/plotly/datasets/master/"
        "geojson-counties-fips.json"
    )
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {"type": "FeatureCollection", "features": []}


st.subheader("Select a County")

if active_fips:
    county_label = display_name(active_fips)
    st.markdown(
        f"**Selected:** {county_label} &nbsp;&nbsp;"
        f"<small style='color:gray'>FIPS {active_fips} · "
        f"[Share this view](?fips={active_fips})</small>",
        unsafe_allow_html=True,
    )

# Build folium map
m = folium.Map(
    location=[38.5, -96],
    zoom_start=4,
    tiles="CartoDB positron",
    attr="CartoDB",
)

with st.spinner("Loading county boundaries..."):
    geojson = _load_geojson()

if geojson.get("features"):
    folium.GeoJson(
        geojson,
        name="US Counties",
        style_function=lambda feature: {
            "fillColor": (
                "#2196F3" if feature["id"] == active_fips else "#ffffff"
            ),
            "fillOpacity": (
                0.5 if feature["id"] == active_fips else 0.05
            ),
            "color":       "#444444",
            "weight":      0.4,
        },
        highlight_function=lambda _: {
            "fillColor":   "#FF9800",
            "fillOpacity": 0.6,
            "weight":      1.5,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["NAME"],
            aliases=["County:"],
            sticky=True,
        ),
    ).add_to(m)

map_data = st_folium(m, height=420, use_container_width=True, returned_objects=["last_active_drawing", "last_clicked"])

# Handle map click — extract FIPS from clicked feature
clicked_fips = None
if map_data and map_data.get("last_active_drawing"):
    props = map_data["last_active_drawing"].get("properties", {})
    clicked_fips = props.get("GEOID") or props.get("fips")

if clicked_fips and clicked_fips != active_fips:
    st.query_params["fips"] = clicked_fips
    st.rerun()

# ---------------------------------------------------------------------------
# County profile panel — shown when a FIPS is active
# ---------------------------------------------------------------------------
if active_fips:
    info = resolve_fips(active_fips)
    if info:
        st.divider()
        render_county_panel(active_fips)
    else:
        st.error(f"Unknown FIPS code: {active_fips}. Please select a valid county.")
        if st.button("Clear selection"):
            st.query_params.clear()
            st.rerun()
elif not active_fips:
    st.info("Click a county on the map or search by name to view its energy permit data.")
