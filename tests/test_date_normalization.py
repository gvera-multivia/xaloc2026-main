from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from core.consultor.normalizer import normalize_resource_row
from core.date_normalization import business_today, normalize_date_iso, submission_date_priority_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (date(2026, 3, 17), "2026-03-17"),
        (datetime(2026, 3, 17, 23, 59, 58), "2026-03-17"),
        (
            datetime(2026, 3, 17, 23, 59, tzinfo=timezone(timedelta(hours=-5))),
            "2026-03-17",
        ),
        ("2026-03-17", "2026-03-17"),
        ("2026-03-17 08:09:10.123456", "2026-03-17"),
        ("2026-03-17T08:09:10+01:00", "2026-03-17"),
        ("2026-03-17T08:09:10Z", "2026-03-17"),
        ("17/03/2026", "2026-03-17"),
        (" 17/03/2026 ", "2026-03-17"),
    ],
)
def test_normalize_date_iso_accepts_supported_values(raw: object, expected: str) -> None:
    assert normalize_date_iso(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "31/02/2026",
        "03-17-2026",
        "17-03-2026",
        "not-a-date",
    ],
)
def test_normalize_date_iso_returns_empty_for_missing_or_invalid_values(raw: object) -> None:
    assert normalize_date_iso(raw) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (datetime(2026, 4, 5, 12, 30), "2026-04-05"),
        ("05/04/2026", "2026-04-05"),
        ("invalid", ""),
        (None, ""),
    ],
)
def test_consultor_normalizer_exposes_normalized_submission_date(raw: object, expected: str) -> None:
    canonical = normalize_resource_row(site_id="madrid", row={"fpresentacion": raw})

    assert canonical.resource["submission_date"] == expected


def test_submission_date_priority_is_today_past_future_then_missing() -> None:
    today = date(2026, 9, 22)
    values = [None, "2026-09-24", "2026-09-20", "2026-09-22", "2026-09-21", "2026-09-23"]

    ordered = sorted(values, key=lambda value: submission_date_priority_key(value, today=today))

    assert ordered == ["2026-09-22", "2026-09-21", "2026-09-20", "2026-09-23", "2026-09-24", None]


def test_business_today_converts_aware_clock_to_europe_madrid() -> None:
    utc_clock = datetime(2026, 9, 21, 22, 30, tzinfo=timezone.utc)

    assert business_today(utc_clock) == date(2026, 9, 22)
