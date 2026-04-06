"""
Scraper provider registry.

Maps provider_name strings to BaseScraper subclasses and handles
the lookup of which providers serve a given county FIPS.
"""
from __future__ import annotations

import logging
from typing import Type

from scrapers.base import BaseScraper
from scrapers.providers.municode import MunicodeProvider
from scrapers.providers.legistar import LegistarProvider
from scrapers.providers.civicplus_generic import CivicPlusProvider, GenericPortalProvider

log = logging.getLogger(__name__)

PROVIDER_MAP: dict[str, Type[BaseScraper]] = {
    MunicodeProvider.provider_name:    MunicodeProvider,
    LegistarProvider.provider_name:    LegistarProvider,
    CivicPlusProvider.provider_name:   CivicPlusProvider,
    GenericPortalProvider.provider_name: GenericPortalProvider,
}


def get_providers(fips: str) -> list[BaseScraper]:
    """
    Return instantiated provider(s) configured for this county.
    If no providers are registered in the DB, fall back to GenericPortalProvider.
    """
    from db.database import get_db
    from db.models import CountyProvider

    with get_db() as db:
        rows = db.query(CountyProvider).filter_by(fips=fips).all()

    if not rows:
        log.info("No providers registered for FIPS %s — using generic fallback", fips)
        return [GenericPortalProvider()]

    providers = []
    for row in rows:
        cls = PROVIDER_MAP.get(row.provider)
        if cls:
            providers.append(cls())
        else:
            log.warning("Unknown provider '%s' for FIPS %s", row.provider, fips)

    return providers or [GenericPortalProvider()]


def register_provider(fips: str, provider_name: str, base_url: str = "",
                      config_json: str = "{}") -> None:
    """Register a provider for a county in the database."""
    from db.database import get_db
    from db.models import CountyProvider

    with get_db() as db:
        existing = (
            db.query(CountyProvider)
            .filter_by(fips=fips, provider=provider_name)
            .first()
        )
        if existing:
            existing.base_url = base_url
            existing.config_json = config_json
        else:
            db.add(CountyProvider(
                fips=fips,
                provider=provider_name,
                base_url=base_url,
                config_json=config_json,
            ))
