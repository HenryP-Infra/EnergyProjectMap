"""
seed_demo.py — populate the database with realistic demo records.

Run once after `python -c "from db.database import init_db; init_db()"`:
    python seed_demo.py

This lets the app look fully populated without needing real county data.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from db.database import init_db, get_db
from db.models import (
    County, CountyProvider, Ordinance, Setback,
    Permit, Hearing, Vote, Document,
)

DEMO_COUNTIES = [
    {"fips": "48113", "name": "Dallas County",        "state_name": "Texas",      "state_abbr": "TX"},
    {"fips": "19153", "name": "Polk County",           "state_name": "Iowa",       "state_abbr": "IA"},
    {"fips": "39049", "name": "Franklin County",       "state_name": "Ohio",       "state_abbr": "OH"},
    {"fips": "20091", "name": "Johnson County",        "state_name": "Kansas",     "state_abbr": "KS"},
    {"fips": "38065", "name": "Oliver County",         "state_name": "North Dakota","state_abbr": "ND"},
]

DEMO_ORDINANCES = {
    "48113": [
        {
            "ordinance_number": "2021-045",
            "title": "Solar Energy Systems — Land Use Ordinance",
            "energy_type": "solar",
            "adopted_date": datetime(2021, 6, 14),
            "has_energy_overlay": True,
            "doc_url": "https://example.com/dallas-solar-ordinance-2021.pdf",
            "setbacks": [
                {"project_type": "solar", "setback_type": "property_line", "distance_ft": 50,
                 "source_section": "§4.3.1", "confidence_score": 0.98, "notes": None},
                {"project_type": "solar", "setback_type": "residence",     "distance_ft": 300,
                 "source_section": "§4.3.2", "confidence_score": 0.95, "notes": "From occupied dwelling"},
                {"project_type": "solar", "setback_type": "road",          "distance_ft": 100,
                 "source_section": "§4.3.3", "confidence_score": 0.72,
                 "notes": "Ambiguous — could be 75 ft per §2.1 table",
                 "needs_human_review": True,
                 "confidence_reason": "Two sections conflict: §4.3.3 states 100 ft, §2.1 table states 75 ft"},
            ],
        },
        {
            "ordinance_number": "2019-112",
            "title": "Wind Energy Conversion Systems Ordinance",
            "energy_type": "wind",
            "adopted_date": datetime(2019, 3, 7),
            "has_energy_overlay": False,
            "doc_url": "https://example.com/dallas-wind-ordinance-2019.pdf",
            "setbacks": [
                {"project_type": "wind", "setback_type": "property_line", "distance_ft": 1000,
                 "source_section": "§6.2", "confidence_score": 0.99, "notes": "1× tip height minimum"},
                {"project_type": "wind", "setback_type": "residence",     "distance_ft": 1500,
                 "source_section": "§6.3", "confidence_score": 0.97, "notes": None},
            ],
        },
    ],
    "19153": [
        {
            "ordinance_number": "ORD-2022-007",
            "title": "Renewable Energy Facility Siting Standards",
            "energy_type": "solar",
            "adopted_date": datetime(2022, 1, 18),
            "has_energy_overlay": True,
            "doc_url": "https://example.com/polk-renewable-2022.pdf",
            "setbacks": [
                {"project_type": "solar", "setback_type": "property_line", "distance_ft": 75,
                 "source_section": "Art. IV §2", "confidence_score": 0.96, "notes": None},
                {"project_type": "solar", "setback_type": "road",          "distance_ft": 150,
                 "source_section": "Art. IV §3", "confidence_score": 0.55,
                 "needs_human_review": True,
                 "confidence_reason": "Value appears in a footnote with qualifier 'unless waived by Board'"},
                {"project_type": "BESS",  "setback_type": "residence",     "distance_ft": 500,
                 "source_section": "Art. V §1", "confidence_score": 0.91, "notes": "Battery storage only"},
            ],
        },
    ],
}

DEMO_PERMITS = {
    "48113": [
        {
            "project_name": "Sunridge Solar Farm I",
            "applicant": "Sunridge Energy LLC",
            "permit_type": "SUP",
            "energy_type": "solar",
            "capacity_mw": 80.0,
            "acreage": 640.0,
            "application_date": datetime(2022, 3, 15),
            "outcome": "approved",
            "hearings": [
                {
                    "hearing_date": datetime(2022, 6, 8),
                    "board_type": "Planning & Zoning Commission",
                    "vote_yes": 5, "vote_no": 1, "vote_abstain": 0,
                    "conditions": ["Install wildlife-friendly fencing", "Submit decommissioning bond"],
                    "denial_reasons": [],
                    "votes": [
                        {"member": "J. Martinez", "vote": "yes"},
                        {"member": "S. Patel",    "vote": "yes"},
                        {"member": "L. Brooks",   "vote": "yes"},
                        {"member": "R. Kim",      "vote": "yes"},
                        {"member": "A. Thompson", "vote": "yes"},
                        {"member": "C. Rivera",   "vote": "no"},
                    ],
                }
            ],
        },
        {
            "project_name": "Prairieland Wind Project",
            "applicant": "GreenWind Partners",
            "permit_type": "CUP",
            "energy_type": "wind",
            "capacity_mw": 200.0,
            "acreage": 3200.0,
            "application_date": datetime(2021, 9, 1),
            "outcome": "denied",
            "hearings": [
                {
                    "hearing_date": datetime(2022, 1, 19),
                    "board_type": "County Commission",
                    "vote_yes": 1, "vote_no": 4, "vote_abstain": 0,
                    "conditions": [],
                    "denial_reasons": [
                        "Insufficient setback from residential properties",
                        "Noise impact study incomplete",
                    ],
                    "votes": [
                        {"member": "Commissioner Adams",    "vote": "yes"},
                        {"member": "Commissioner Lee",      "vote": "no"},
                        {"member": "Commissioner Johnson",  "vote": "no"},
                        {"member": "Commissioner Williams", "vote": "no"},
                        {"member": "Commissioner Brown",    "vote": "no"},
                    ],
                }
            ],
        },
        {
            "project_name": "Metro Battery Storage Facility",
            "applicant": "StorageCo Texas",
            "permit_type": "SUP",
            "energy_type": "BESS",
            "capacity_mw": 50.0,
            "acreage": 12.0,
            "application_date": datetime(2023, 2, 20),
            "outcome": "pending",
            "hearings": [
                {
                    "hearing_date": datetime(2023, 5, 10),
                    "board_type": "Planning & Zoning Commission",
                    "vote_yes": 3, "vote_no": 2, "vote_abstain": 1,
                    "conditions": [],
                    "denial_reasons": [],
                    "votes": [
                        {"member": "J. Martinez", "vote": "yes"},
                        {"member": "S. Patel",    "vote": "yes"},
                        {"member": "L. Brooks",   "vote": "yes"},
                        {"member": "R. Kim",      "vote": "no"},
                        {"member": "A. Thompson", "vote": "no"},
                        {"member": "C. Rivera",   "vote": "abstain"},
                    ],
                }
            ],
        },
    ],
    "19153": [
        {
            "project_name": "Central Iowa Solar Array",
            "applicant": "SolarFarm Midwest Inc.",
            "permit_type": "CUP",
            "energy_type": "solar",
            "capacity_mw": 120.0,
            "acreage": 900.0,
            "application_date": datetime(2022, 7, 11),
            "outcome": "approved",
            "hearings": [
                {
                    "hearing_date": datetime(2022, 10, 4),
                    "board_type": "Zoning Board of Adjustment",
                    "vote_yes": 4, "vote_no": 0, "vote_abstain": 1,
                    "conditions": [
                        "Agricultural land restoration plan required",
                        "Annual inspection report to county engineer",
                    ],
                    "denial_reasons": [],
                    "votes": [
                        {"member": "B. Hansen",  "vote": "yes"},
                        {"member": "T. Nguyen",  "vote": "yes"},
                        {"member": "M. O'Brien", "vote": "yes"},
                        {"member": "D. Clark",   "vote": "yes"},
                        {"member": "P. Evans",   "vote": "abstain"},
                    ],
                }
            ],
        },
    ],
}

DEMO_DOCUMENTS = {
    "48113": [
        {
            "doc_type": "ordinance",
            "title": "Solar Energy Systems — Land Use Ordinance (2021-045)",
            "source_url": "https://example.com/dallas-solar-ordinance-2021.pdf",
            "raw_text": (
                "DALLAS COUNTY ORDINANCE 2021-045\n"
                "An ordinance establishing standards for solar energy systems.\n\n"
                "§4.3 SETBACK REQUIREMENTS\n"
                "§4.3.1 Property Line Setback: Solar arrays shall be set back a minimum of "
                "50 feet from all property lines.\n"
                "§4.3.2 Residential Setback: No solar array shall be located within 300 feet "
                "of an occupied dwelling unit.\n"
                "§4.3.3 Road Setback: Arrays shall maintain 100 feet from public road rights-of-way.\n\n"
                "§2.1 TABLE OF SETBACKS [see footnote 3]\n"
                "Road setback: 75 feet (see §4.3.3 for exceptions)\n"
            ),
            "provider": "municode",
            "document_confidence": 0.87,
            "needs_human_review": True,
        },
        {
            "doc_type": "staff_report",
            "title": "Staff Report — Sunridge Solar Farm I SUP Application",
            "source_url": "https://example.com/sunridge-staff-report.pdf",
            "raw_text": (
                "PLANNING & ZONING COMMISSION STAFF REPORT\n"
                "Application: Special Use Permit — Solar Energy Facility\n"
                "Applicant: Sunridge Energy LLC\n"
                "Project: Sunridge Solar Farm I (80 MW / 640 acres)\n\n"
                "STAFF RECOMMENDATION: Approval with conditions.\n"
                "The proposed facility meets all setback requirements under Ordinance 2021-045. "
                "Wildlife fencing and a decommissioning bond are recommended as conditions of approval."
            ),
            "provider": "legistar",
            "document_confidence": 0.96,
            "needs_human_review": False,
        },
    ],
    "19153": [
        {
            "doc_type": "ordinance",
            "title": "Renewable Energy Facility Siting Standards (ORD-2022-007)",
            "source_url": "https://example.com/polk-renewable-2022.pdf",
            "raw_text": (
                "POLK COUNTY ORDINANCE ORD-2022-007\n"
                "Renewable Energy Facility Siting Standards.\n\n"
                "ARTICLE IV. SOLAR FACILITY SETBACKS\n"
                "§2. Property Line Setback: 75 feet from all parcel boundaries.\n"
                "§3. Road Setback: 150 feet from centerline of public road¹.\n\n"
                "ARTICLE V. BATTERY ENERGY STORAGE SYSTEMS\n"
                "§1. Residential setback for BESS facilities: 500 feet minimum.\n\n"
                "Footnote 1: Road setback may be waived by Board upon written request."
            ),
            "provider": "civicplus",
            "document_confidence": 0.79,
            "needs_human_review": True,
        },
    ],
}


def seed():
    init_db()

    with get_db() as db:
        # Counties
        for c in DEMO_COUNTIES:
            if not db.query(County).filter_by(fips=c["fips"]).first():
                db.add(County(**c))
        db.flush()

        # Ordinances + setbacks
        for fips, ords in DEMO_ORDINANCES.items():
            for o_data in ords:
                setbacks_data = o_data.pop("setbacks", [])
                if not db.query(Ordinance).filter_by(
                    county_fips=fips, ordinance_number=o_data.get("ordinance_number")
                ).first():
                    ord_obj = Ordinance(county_fips=fips, **o_data)
                    db.add(ord_obj)
                    db.flush()
                    for sb in setbacks_data:
                        db.add(Setback(
                            ordinance_id=ord_obj.id,
                            county_fips=fips,
                            **sb,
                        ))

        # Permits + hearings + votes
        for fips, permits in DEMO_PERMITS.items():
            for p_data in permits:
                hearings_data = p_data.pop("hearings", [])
                if not db.query(Permit).filter_by(
                    county_fips=fips, project_name=p_data["project_name"]
                ).first():
                    permit = Permit(county_fips=fips, **p_data)
                    db.add(permit)
                    db.flush()
                    for h_data in hearings_data:
                        votes_data = h_data.pop("votes", [])
                        conds = h_data.pop("conditions", [])
                        denials = h_data.pop("denial_reasons", [])
                        hearing = Hearing(
                            permit_id=permit.id,
                            conditions=json.dumps(conds),
                            denial_reasons=json.dumps(denials),
                            **h_data,
                        )
                        db.add(hearing)
                        db.flush()
                        for v in votes_data:
                            db.add(Vote(hearing_id=hearing.id, **v))

        # Documents
        for fips, docs in DEMO_DOCUMENTS.items():
            for d_data in docs:
                if not db.query(Document).filter_by(
                    county_fips=fips, source_url=d_data["source_url"]
                ).first():
                    db.add(Document(
                        county_fips=fips,
                        extracted_at=datetime.utcnow(),
                        **d_data,
                    ))

    print("✅ Demo seed complete.")
    print("   Counties seeded:", [c["fips"] for c in DEMO_COUNTIES])
    print("   Try FIPS 48113 (Dallas County, TX) or 19153 (Polk County, IA).")


if __name__ == "__main__":
    seed()
