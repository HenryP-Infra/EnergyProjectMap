"""
Confidence scoring helpers.

Applies needs_human_review flags based on per-field confidence scores,
and provides the confidence badge labels used in both the UI and the
admin dashboard.
"""
from __future__ import annotations

from config import settings


def apply_review_flags(extracted: dict) -> dict:
    """
    Mutates the extracted dict in-place:
      - Sets needs_human_review=True on any setback with confidence < threshold.
      - Sets the top-level needs_human_review=True if any setback is flagged.
    Returns the mutated dict.
    """
    threshold = settings.confidence_review_threshold
    any_flagged = False

    for setback in extracted.get("setbacks") or []:
        score = setback.get("confidence_score")
        if score is None:
            score = 1.0
            setback["confidence_score"] = 1.0

        if score < threshold:
            setback["needs_human_review"] = True
            any_flagged = True
        else:
            setback["needs_human_review"] = False

    if any_flagged:
        extracted["needs_human_review"] = True

    return extracted


# ---------------------------------------------------------------------------
# UI helpers — used in Streamlit components
# ---------------------------------------------------------------------------

def confidence_badge(score: float | None) -> tuple[str, str]:
    """
    Return (label, color) for a confidence score badge.

    Colors are Streamlit-compatible CSS color strings.
    """
    if score is None:
        return "Unknown", "gray"
    if score >= 0.90:
        return "Verified", "green"
    if score >= 0.75:
        return "Review pending", "orange"
    return "Low confidence", "red"


def confidence_emoji(score: float | None) -> str:
    """Single emoji indicator for compact table cells."""
    if score is None:
        return "❓"
    if score >= 0.90:
        return "✅"
    if score >= 0.75:
        return "⚠️"
    return "🔴"


def format_confidence(score: float | None) -> str:
    """Human-readable percentage string."""
    if score is None:
        return "—"
    return f"{score * 100:.0f}%"
