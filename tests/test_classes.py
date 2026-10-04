"""Unit tests for class decode + filtering. Built from a redacted live fixture."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wellpass_mcp import classes

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def raw_classes():
    return json.loads((FIXTURES / "classes_sample.json").read_text())


def test_available_spots_computed_from_capacity():
    brief = {"availableSpots": None, "maxCapacity": 20, "totalBooked": 5}
    assert classes.available_spots(brief) == 15


def test_available_spots_prefers_explicit():
    assert classes.available_spots({"availableSpots": 3, "maxCapacity": 20, "totalBooked": 5}) == 3


def test_available_spots_none_when_unknown():
    assert classes.available_spots({"maxCapacity": None, "totalBooked": None}) is None


def test_decode_class_shape(raw_classes):
    row = classes.decode_class(raw_classes[0])
    assert set(row) >= {"name", "category", "start", "teacher", "available_spots", "online"}
    # default tz is Europe/Berlin -> a non-UTC offset, not a bare Z
    assert row["start"] and ("+01:00" in row["start"] or "+02:00" in row["start"])


def test_decode_class_tz_override(raw_classes):
    row = classes.decode_class(raw_classes[0], tz="UTC")
    assert row["start"].endswith("+00:00")


def test_resolve_window_defaults_end_to_start_plus_days():
    start, end = classes.resolve_window("2026-10-20", None, now_ms=0)
    assert end - start == 7 * 86400 * 1000  # not now+7d


def test_resolve_window_rejects_bad_date():
    with pytest.raises(ValueError):
        classes.resolve_window("tomorrow", None, now_ms=0)


def test_resolve_window_rejects_reversed_range():
    with pytest.raises(ValueError):
        classes.resolve_window("2026-10-20", "2026-10-10", now_ms=0)


def test_resolve_window_default_both():
    start, end = classes.resolve_window(None, None, now_ms=1000)
    assert start == 1000 and end == 1000 + 7 * 86400 * 1000


def test_decode_class_category_from_activity(raw_classes):
    row = classes.decode_class(raw_classes[0])
    # fixture first class is LES MILLS BODYBALANCE -> activity "Body & Mind"
    assert row["category"] == "Body & Mind"


def test_filter_by_teacher(raw_classes):
    rows = [classes.decode_class(c) for c in raw_classes]
    teacher = rows[0]["teacher"]
    out = classes.filter_classes(rows, teacher=teacher)
    assert out and all(r["teacher"] == teacher for r in out)


def test_filter_by_category(raw_classes):
    rows = [classes.decode_class(c) for c in raw_classes]
    out = classes.filter_classes(rows, category="body & mind")
    assert out and all("body & mind" in (r["category"] or "").lower() for r in out)


def test_filter_available_only(raw_classes):
    rows = [classes.decode_class(c) for c in raw_classes]
    out = classes.filter_classes(rows, available_only=True)
    assert all((r["available_spots"] or 0) > 0 for r in out)


def test_filter_sorted_by_start(raw_classes):
    rows = [classes.decode_class(c) for c in raw_classes]
    out = classes.filter_classes(rows)
    starts = [r["start"] for r in out]
    assert starts == sorted(starts)


def test_parse_date_to_ms_date_only():
    from datetime import datetime, timezone
    ms = classes.parse_date_to_ms("2026-10-05")
    expected = int(datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp() * 1000)
    assert ms == expected


def test_parse_date_to_ms_end_of_day_is_later():
    start = classes.parse_date_to_ms("2026-10-05")
    end = classes.parse_date_to_ms("2026-10-05", end_of_day=True)
    assert end > start


def test_parse_date_none():
    assert classes.parse_date_to_ms(None) is None
    assert classes.parse_date_to_ms("not-a-date") is None
