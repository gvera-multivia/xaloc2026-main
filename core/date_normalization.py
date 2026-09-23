from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE = ZoneInfo("Europe/Madrid")


def normalize_date_iso(value: Any) -> str:
    """Return a supported date value as ``YYYY-MM-DD`` or an empty string.

    Datetimes keep their calendar date as supplied; timezone-aware values are not
    converted to another timezone. Besides Python ``date``/``datetime`` objects,
    ISO date/datetime strings and the unambiguous project legacy format
    ``DD/MM/YYYY`` are accepted.
    """

    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    iso_value = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        return datetime.fromisoformat(iso_value).date().isoformat()
    except (TypeError, ValueError):
        pass

    try:
        return datetime.strptime(text, "%d/%m/%Y").date().isoformat()
    except (TypeError, ValueError):
        return ""


def business_today(now: datetime | None = None) -> date:
    """Return the calendar day used to prioritize submissions."""

    if now is None:
        return datetime.now(BUSINESS_TIMEZONE).date()
    if now.tzinfo is not None:
        return now.astimezone(BUSINESS_TIMEZONE).date()
    return now.date()


def submission_date_priority_key(
    value: Any,
    *,
    today: date | None = None,
) -> tuple[int, int]:
    """Order today/recent past, then nearest future, then missing dates."""

    normalized = normalize_date_iso(value)
    if not normalized:
        return (3, 0)

    submission_date = date.fromisoformat(normalized)
    reference = today or business_today()
    if submission_date <= reference:
        return (0, (reference - submission_date).days)
    return (2, (submission_date - reference).days)
