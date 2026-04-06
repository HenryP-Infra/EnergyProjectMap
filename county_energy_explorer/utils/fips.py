"""
FIPS code resolution utilities.

Loads a bundled lookup table (data/fips_lookup.json) and provides helper
functions used throughout the UI so raw FIPS codes are never shown to users.

The lookup table is a dict of:
  { "48113": {"county_name": "Dallas County", "state_name": "Texas", "state_abbr": "TX"}, ... }

If the bundled file is missing, a minimal fallback of well-known counties is used
so the app still runs in demo mode.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

_LOOKUP_PATH = Path(__file__).parent.parent / "data" / "fips_lookup.json"

# Minimal fallback so the app boots without the full data file
_FALLBACK: dict[str, dict] = {
    "06037": {"county_name": "Los Angeles County", "state_name": "California", "state_abbr": "CA"},
    "48113": {"county_name": "Dallas County",       "state_name": "Texas",      "state_abbr": "TX"},
    "17031": {"county_name": "Cook County",         "state_name": "Illinois",   "state_abbr": "IL"},
    "36061": {"county_name": "New York County",     "state_name": "New York",   "state_abbr": "NY"},
    "04013": {"county_name": "Maricopa County",     "state_name": "Arizona",    "state_abbr": "AZ"},
    "19153": {"county_name": "Polk County",         "state_name": "Iowa",       "state_abbr": "IA"},
    "39049": {"county_name": "Franklin County",     "state_name": "Ohio",       "state_abbr": "OH"},
    "53033": {"county_name": "King County",         "state_name": "Washington", "state_abbr": "WA"},
}


@lru_cache(maxsize=1)
def _load_lookup() -> dict[str, dict]:
    if _LOOKUP_PATH.exists():
        try:
            with open(_LOOKUP_PATH, encoding="utf-8") as f:
                data = json.load(f)
            log.info("Loaded %d FIPS entries from %s", len(data), _LOOKUP_PATH)
            return data
        except Exception as exc:
            log.warning("Could not load fips_lookup.json: %s — using fallback", exc)
    return _FALLBACK


def resolve_fips(fips: str) -> dict | None:
    """
    Return {"county_name", "state_name", "state_abbr"} for the given FIPS code,
    or None if the FIPS is unknown.
    """
    return _load_lookup().get(str(fips).zfill(5))


def display_name(fips: str) -> str:
    """
    Human-readable label for a county, e.g. "Dallas County, Texas".
    Falls back to "County {fips}" if the FIPS is not in the lookup.
    """
    info = resolve_fips(fips)
    if info:
        return f"{info['county_name']}, {info['state_name']}"
    return f"County {fips}"


def short_name(fips: str) -> str:
    """
    Abbreviated label, e.g. "Dallas County, TX".
    """
    info = resolve_fips(fips)
    if info:
        return f"{info['county_name']}, {info['state_abbr']}"
    return f"County {fips}"


def all_counties() -> list[dict]:
    """
    Return a list of all counties as dicts with keys: fips, county_name,
    state_name, state_abbr, display_name.  Sorted by state then county name.
    """
    lookup = _load_lookup()
    result = []
    for fips, info in lookup.items():
        result.append({
            "fips": fips,
            **info,
            "display_name": f"{info['county_name']}, {info['state_name']}",
        })
    return sorted(result, key=lambda x: (x["state_name"], x["county_name"]))


def fips_from_display(display: str) -> str | None:
    """Reverse lookup: given 'Dallas County, Texas', return '48113'."""
    for fips, info in _load_lookup().items():
        if f"{info['county_name']}, {info['state_name']}" == display:
            return fips
    return None
