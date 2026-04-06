# County Energy Permit Explorer

A Streamlit application that lets you click any US county on an interactive map
and instantly retrieve its energy project permitting history — ordinances,
setbacks, special use permits, conditional use permits, voting records, and
source documents.

---

## Features

| Feature | Detail |
|---|---|
| 🗺️ Interactive map | Click any US county — FIPS code mirrored in URL for sharing |
| 🏗️ Setbacks | AI-extracted setback tables (solar / wind / BESS) with confidence scores |
| 📋 Permit history | SUPs, CUPs, applicant, MW, acreage, application date, hearing date |
| 🗳️ Voting records | Member-level votes, margins, hearing timeline |
| 📄 Documents | Ordinances, staff reports, resolutions, meeting minutes |
| ⚙️ Scraper | Provider-based scraper (Municode, Legistar, CivicPlus, Generic) |
| 🔒 Hash gating | SHA-256 hash check — only extracts changed documents |
| 🤖 Claude extraction | Confidence score per field; < 90% flagged for human review |
| 🔍 Admin review | Confirm / edit / reject flagged setbacks with Langfuse trace links |
| 🔎 Full-text search | GIN index on PostgreSQL; LIKE fallback on SQLite |
| 📊 Langfuse tracing | Every Claude call traced; failures visible field-by-field |

---

## Quick start (local / SQLite)

```bash
git clone <repo-url>
cd county_energy_explorer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Copy and edit environment variables
cp .env.example .env
# Set at minimum: ANTHROPIC_API_KEY

# Initialise the database
python -c "from db.database import init_db; init_db()"

# Seed demo data (optional — populates Dallas County TX + Polk County IA)
python seed_demo.py

# Run the app
streamlit run app.py
```

Open http://localhost:8501 in your browser.

---

## Quick start (Docker — full production stack)

Starts Streamlit + PostgreSQL + Redis + self-hosted Langfuse.

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and LANGFUSE_* keys

docker compose up --build
```

| Service | URL |
|---|---|
| Streamlit app | http://localhost:8501 |
| Langfuse dashboard | http://localhost:3000 |
| PostgreSQL | localhost:5432 |

---

## Sharing a county view

Every county view writes the FIPS code into the URL query parameter:

```
http://localhost:8501/?fips=48113   → Dallas County, Texas
http://localhost:8501/?fips=19153   → Polk County, Iowa
```

Share the URL with a colleague and they land directly on that county.

---

## Project structure

```
county_energy_explorer/
├── app.py                          # Page 1 — interactive map + county panel
├── pages/
│   ├── 2_Admin_Review.py           # Page 2 — human review dashboard
│   └── 3_Search.py                 # Page 3 — full-text document search
├── components/
│   └── county_panel.py             # County profile tabs
├── scrapers/
│   ├── base.py                     # BaseScraper ABC
│   ├── registry.py                 # Provider registry + get_providers()
│   ├── runner.py                   # Pipeline: fetch → hash → extract → persist
│   └── providers/
│       ├── municode.py             # Municode TOC + chapter downloader
│       ├── legistar.py             # Legistar REST API client
│       └── civicplus_generic.py    # CivicPlus + GenericPortal fallback
├── extractors/
│   ├── hash_gate.py                # SHA-256 hash gating
│   ├── claude_extractor.py         # Claude API call + Langfuse tracing
│   └── confidence.py              # Review flag logic + badge helpers
├── db/
│   ├── models.py                   # SQLAlchemy ORM models
│   └── database.py                 # Engine, session, GIN index migration
├── utils/
│   └── fips.py                     # FIPS → county/state name resolution
├── data/
│   └── fips_lookup.json            # ~80 counties pre-loaded; extend as needed
├── seed_demo.py                    # Demo data seeder
├── config.py                       # Pydantic settings from .env
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .streamlit/config.toml
```

---

## Adding a new scraper provider

1. Create `scrapers/providers/myprovider.py`:

```python
from scrapers.base import BaseScraper, ScrapedDocument

class MyProvider(BaseScraper):
    provider_name    = "myprovider"
    supported_states = ["TX", "CA"]   # or [] for all states

    def fetch_documents(self, fips: str) -> list[ScrapedDocument]:
        # ... your scraping logic ...
        return [ScrapedDocument(source_url=..., raw_bytes=..., doc_type=...)]
```

2. Register it in `scrapers/registry.py`:

```python
from scrapers.providers.myprovider import MyProvider

PROVIDER_MAP = {
    ...
    MyProvider.provider_name: MyProvider,
}
```

3. Associate a county with the provider in the database:

```python
from scrapers.registry import register_provider
register_provider(fips="48113", provider_name="myprovider", base_url="https://...")
```

---

## Extending the FIPS lookup

The bundled `data/fips_lookup.json` covers ~80 counties. To load the full
3,200+ US county list, download from the Census Bureau and convert:

```bash
curl -O https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt
python scripts/build_fips_lookup.py   # (script not included — trivial CSV parse)
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (for extraction) | Claude API key |
| `DATABASE_URL` | No | Defaults to SQLite `county_permits.db` |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse project public key |
| `LANGFUSE_SECRET_KEY` | No | Langfuse project secret key |
| `LANGFUSE_HOST` | No | Defaults to `https://cloud.langfuse.com` |
| `ADMIN_PASSWORD` | No | Admin dashboard password (default: `changeme`) |
| `SCRAPE_RATE_LIMIT_RPS` | No | Requests per second (default: 2) |

---

## Confidence & human review

Every setback value extracted by Claude carries a `confidence_score` (0–1).
Values below **0.90** are automatically flagged `needs_human_review = True` and
appear in the Admin Review dashboard at `/admin/review`.

| Badge | Range | Meaning |
|---|---|---|
| ✅ Verified | ≥ 90% | Extracted with high certainty |
| ⚠️ Review pending | 75–89% | Implied or requires interpretation |
| 🔴 Low confidence | < 75% | Conflicting sources or strong ambiguity |

The admin reviewer can **Confirm** (accept the extracted value), **Edit** (correct
it), or **Reject** (mark as unresolvable). Each action records the reviewer's
name and timestamp.

Every extraction failure or low-confidence event is logged as a Langfuse trace
event. The admin dashboard shows a direct link to the trace for each flagged record.
