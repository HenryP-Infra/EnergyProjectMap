"""
SQLAlchemy ORM models for the County Energy Permit Explorer.
Supports SQLite (dev) and PostgreSQL (production).
The GIN index on raw_text_tsv is PostgreSQL-only and skipped for SQLite.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class County(Base):
    __tablename__ = "counties"

    fips        = Column(String(5), primary_key=True)
    name        = Column(String(120), nullable=False)
    state_name  = Column(String(60), nullable=False)
    state_abbr  = Column(String(2), nullable=False)

    providers   = relationship("CountyProvider", back_populates="county", cascade="all, delete-orphan")
    ordinances  = relationship("Ordinance", back_populates="county", cascade="all, delete-orphan")
    permits     = relationship("Permit", back_populates="county", cascade="all, delete-orphan")
    documents   = relationship("Document", back_populates="county", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<County {self.fips}: {self.name}, {self.state_name}>"


class CountyProvider(Base):
    """Maps counties to their scraper provider(s)."""
    __tablename__ = "county_providers"
    __table_args__ = (UniqueConstraint("fips", "provider"),)

    id          = Column(Integer, primary_key=True, autoincrement=True)
    fips        = Column(String(5), ForeignKey("counties.fips"), nullable=False)
    provider    = Column(String(40), nullable=False)  # matches BaseScraper.provider_name
    base_url    = Column(String(500))
    config_json = Column(Text)  # JSON blob for provider-specific auth/params

    county      = relationship("County", back_populates="providers")


class Ordinance(Base):
    __tablename__ = "ordinances"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    county_fips      = Column(String(5), ForeignKey("counties.fips"), nullable=False)
    ordinance_number = Column(String(80))
    title            = Column(String(500))
    energy_type      = Column(String(40))     # solar | wind | BESS | general
    adopted_date     = Column(DateTime)
    amended_date     = Column(DateTime)
    doc_url          = Column(String(1000))
    has_energy_overlay = Column(Boolean, default=False)

    county   = relationship("County", back_populates="ordinances")
    setbacks = relationship("Setback", back_populates="ordinance", cascade="all, delete-orphan")


class Setback(Base):
    __tablename__ = "setbacks"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    ordinance_id       = Column(Integer, ForeignKey("ordinances.id"))
    county_fips        = Column(String(5), ForeignKey("counties.fips"), nullable=False)
    project_type       = Column(String(20))   # solar | wind | BESS
    setback_type       = Column(String(40))   # property_line | residence | road | wetland | other
    distance_ft        = Column(Float)
    source_section     = Column(String(200))
    notes              = Column(Text)

    # Confidence / review fields
    confidence_score   = Column(Float, default=1.0)
    confidence_reason  = Column(Text)
    needs_human_review = Column(Boolean, default=False)
    reviewed_by        = Column(String(120))
    reviewed_at        = Column(DateTime)
    review_action      = Column(String(20))   # confirmed | edited | rejected

    ordinance          = relationship("Ordinance", back_populates="setbacks")


class Permit(Base):
    __tablename__ = "permits"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    county_fips      = Column(String(5), ForeignKey("counties.fips"), nullable=False)
    project_name     = Column(String(300))
    applicant        = Column(String(300))
    permit_type      = Column(String(10))    # SUP | CUP
    energy_type      = Column(String(20))    # solar | wind | BESS | hybrid | transmission
    capacity_mw      = Column(Float)
    acreage          = Column(Float)
    application_date = Column(DateTime)
    outcome          = Column(String(20))    # approved | denied | withdrawn | appealed | pending
    appeal_outcome   = Column(String(20))
    doc_url          = Column(String(1000))

    county   = relationship("County", back_populates="permits")
    hearings = relationship("Hearing", back_populates="permit", cascade="all, delete-orphan")


class Hearing(Base):
    __tablename__ = "hearings"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    permit_id    = Column(Integer, ForeignKey("permits.id"), nullable=False)
    hearing_date = Column(DateTime)
    board_type   = Column(String(80))    # Planning Board | Zoning Board | County Commission
    vote_yes     = Column(Integer, default=0)
    vote_no      = Column(Integer, default=0)
    vote_abstain = Column(Integer, default=0)
    conditions   = Column(Text)           # JSON list of condition strings
    denial_reasons = Column(Text)         # JSON list of denial reasons

    permit = relationship("Permit", back_populates="hearings")
    votes  = relationship("Vote", back_populates="hearing", cascade="all, delete-orphan")


class Vote(Base):
    __tablename__ = "votes"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    hearing_id  = Column(Integer, ForeignKey("hearings.id"), nullable=False)
    member_name = Column(String(150))
    vote        = Column(String(10))     # yes | no | abstain | recuse

    hearing = relationship("Hearing", back_populates="votes")


class Document(Base):
    __tablename__ = "documents"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    county_fips          = Column(String(5), ForeignKey("counties.fips"), nullable=False)
    permit_id            = Column(Integer, ForeignKey("permits.id"), nullable=True)
    doc_type             = Column(String(40))    # ordinance | minutes | resolution | staff_report
    title                = Column(String(500))
    source_url           = Column(String(1000))
    s3_key               = Column(String(500))
    raw_text             = Column(Text)

    # Hash gating
    doc_hash             = Column(String(64))    # SHA-256 hex digest
    hash_checked_at      = Column(DateTime)

    # Extraction metadata
    extracted_at         = Column(DateTime)
    document_confidence  = Column(Float)
    needs_human_review   = Column(Boolean, default=False)
    provider             = Column(String(40))    # which BaseScraper subclass
    langfuse_trace_id    = Column(String(200))
    extracted_json       = Column(Text)          # raw JSON from Claude

    county = relationship("County", back_populates="documents")
