"""
Claude-powered document extractor.

Extracts structured permit / setback / ordinance data from raw PDF text.
Every call is wrapped in a Langfuse trace (if configured) so failures and
low-confidence extractions can be debugged field-by-field.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

import anthropic

from config import settings
from extractors.confidence import apply_review_flags
from utils.fips import display_name

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Langfuse client (lazy — only initialised when credentials are present)
# ---------------------------------------------------------------------------

_langfuse = None


def _get_langfuse():
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    if not settings.langfuse_enabled:
        return None
    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        log.info("Langfuse tracing enabled.")
    except Exception as exc:
        log.warning("Langfuse init failed: %s — tracing disabled", exc)
        _langfuse = None
    return _langfuse


# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a land use document analyst specialising in US county
energy project permitting. Extract structured information from the document provided.

Return ONLY a valid JSON object with no additional text, preamble, or markdown
code fences. If a field is absent from the document, return null.

Schema:
{
  "document_type": "ordinance | SUP | CUP | staff_report | resolution | minutes | other",
  "project_name": "string or null",
  "applicant_name": "string or null",
  "energy_type": "solar | wind | BESS | hybrid | transmission | other | null",
  "capacity_mw": "number or null",
  "acreage": "number or null",
  "application_date": "YYYY-MM-DD or null",
  "hearing_dates": ["YYYY-MM-DD"],
  "outcome": "approved | denied | withdrawn | appealed | pending | null",
  "vote_record": [{"member": "string", "vote": "yes | no | abstain | recuse"}],
  "conditions_of_approval": ["string"],
  "denial_reasons": ["string"],
  "setbacks": [
    {
      "project_type": "solar | wind | BESS",
      "setback_type": "property_line | residence | road | wetland | floodplain | other",
      "distance_ft": "number or null",
      "source_section": "string or null",
      "notes": "string or null",
      "confidence_score": "float 0.0–1.0 — how certain are you of this number?",
      "confidence_reason": "string — brief explanation if confidence < 1.0, else null"
    }
  ],
  "ordinance_number": "string or null",
  "ordinance_adoption_date": "YYYY-MM-DD or null",
  "document_confidence": "float 0.0–1.0 — overall confidence across all extracted fields",
  "needs_human_review": "boolean — true if ANY setback confidence_score < 0.90"
}

Confidence scoring guidance:
- 1.0  — The value is stated explicitly and unambiguously.
- 0.9  — The value is clearly present but requires minor interpretation.
- 0.75 — The value is implied, in a table footnote, or requires unit conversion.
- 0.5  — Multiple conflicting values exist; you selected the most recent/relevant.
- 0.25 — The value is inferred from context with significant uncertainty.
- 0.0  — You cannot extract this field reliably from this document.
"""


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_document(
    raw_text: str,
    fips: str,
    doc_id: int | None,
    source_url: str,
    doc_type: str,
    provider: str,
) -> dict[str, Any]:
    """
    Run Claude extraction on raw_text.  Returns the parsed JSON dict.
    Wraps everything in a Langfuse trace when tracing is enabled.

    Raises on API failure after retries — the runner should catch and log.
    """
    if not settings.anthropic_enabled:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

    county_label = display_name(fips)
    lf = _get_langfuse()
    trace = None
    trace_id = None

    if lf:
        trace = lf.trace(
            name="county_document_extraction",
            tags=["extraction", fips, provider, doc_type],
            metadata={
                "fips":         fips,
                "county_name":  county_label,
                "doc_id":       str(doc_id) if doc_id else "new",
                "doc_type":     doc_type,
                "source_url":   source_url,
                "provider":     provider,
            },
        )
        trace_id = trace.id

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Truncate to avoid hitting context limits on very long documents
    truncated_text = raw_text[:60_000]

    try:
        if trace:
            span = trace.span(name="claude_api_call")

        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"County: {county_label}\n"
                        f"Document type: {doc_type}\n"
                        f"Source URL: {source_url}\n\n"
                        f"--- DOCUMENT TEXT ---\n{truncated_text}"
                    ),
                }
            ],
        )

        raw_output = response.content[0].text if response.content else ""
        result = _parse_response(raw_output)
        result = apply_review_flags(result)
        result["_langfuse_trace_id"] = trace_id

        if trace:
            span.end(
                output=result,
                metadata={
                    "document_confidence": result.get("document_confidence"),
                    "input_tokens":  response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            )
            # Log individual low-confidence setback events
            for setback in result.get("setbacks") or []:
                if (setback.get("confidence_score") or 1.0) < settings.confidence_review_threshold:
                    trace.event(
                        name="low_confidence_setback",
                        metadata={
                            "field":             "distance_ft",
                            "value":             setback.get("distance_ft"),
                            "confidence_score":  setback.get("confidence_score"),
                            "confidence_reason": setback.get("confidence_reason"),
                            "project_type":      setback.get("project_type"),
                            "setback_type":      setback.get("setback_type"),
                            "source_section":    setback.get("source_section"),
                        },
                    )
            trace.update(status="success")

        return result

    except Exception as exc:
        log.error("Extraction failed for %s (%s): %s", source_url, fips, exc)
        if trace:
            try:
                span.end(level="ERROR", status_message=str(exc))
                trace.update(
                    status="error",
                    status_message=str(exc),
                    metadata={"raw_text_preview": raw_text[:500]},
                )
            except Exception:
                pass
        raise


def _parse_response(raw: str) -> dict:
    """Strip markdown fences and parse JSON from Claude's response."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        log.error("JSON parse failed. Raw output:\n%s\nError: %s", raw[:500], exc)
        return {
            "document_type": "other",
            "document_confidence": 0.0,
            "needs_human_review": True,
            "_parse_error": str(exc),
        }
