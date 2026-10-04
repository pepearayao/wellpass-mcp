"""Unit tests for the studio search logic. Built from real, trimmed fixtures."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from wellpass_mcp import studios

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

MUNICH = (48.137154, 11.576124)
BERLIN = (52.520008, 13.404954)


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def overview():
    return _load("overview_sample.json")


@pytest.fixture
def slug_index():
    return studios.build_slug_index(_load("search_filter_wellpass.json"))


# --- distance --------------------------------------------------------------

def test_haversine_munich_berlin():
    dist = studios.haversine_km(*MUNICH, *BERLIN)
    assert 490 < dist < 520  # real distance is ~504 km


def test_haversine_same_point_is_zero():
    assert studios.haversine_km(*MUNICH, *MUNICH) == pytest.approx(0.0, abs=1e-6)


# --- slug resolution -------------------------------------------------------

def test_resolve_bare_name(slug_index):
    resolved, unknown = studios.resolve_slugs(["yoga"], slug_index)
    assert resolved == ["activity-yoga"]
    assert unknown == []


def test_resolve_exact_slug(slug_index):
    resolved, _ = studios.resolve_slugs(["service-free-parking"], slug_index)
    assert resolved == ["service-free-parking"]


def test_resolve_activity_type(slug_index):
    resolved, _ = studios.resolve_slugs(["BOULDERING_CLIMBING"], slug_index)
    assert resolved == ["activity-bouldering-climbing"]


def test_resolve_label(slug_index):
    resolved, _ = studios.resolve_slugs(["Free parking"], slug_index)
    assert resolved == ["service-free-parking"]


def test_resolve_unknown(slug_index):
    resolved, unknown = studios.resolve_slugs(["unicorn-riding"], slug_index)
    assert resolved == []
    assert unknown == ["unicorn-riding"]


def test_resolve_dedupes(slug_index):
    resolved, _ = studios.resolve_slugs(["yoga", "Yoga", "activity-yoga"], slug_index)
    assert resolved == ["activity-yoga"]


# --- filter_and_rank -------------------------------------------------------

def test_radius_keeps_near_excludes_far(overview):
    # Search from the northern gym's own coordinates.
    north = next(g for g in overview if g["a"].startswith("Nordic"))
    rows = studios.filter_and_rank(
        overview, north["lat"], north["lng"], radius_km=5.0,
        studio_types=None, gym_info=None, open_now=False,
    )
    names = [r["name"] for r in rows]
    assert north["a"] in names
    assert "Eastside Fitness" not in names  # ~400 km away


def test_sorted_by_distance(overview):
    rows = studios.filter_and_rank(
        overview, *MUNICH, radius_km=None,
        studio_types=None, gym_info=None, open_now=False,
    )
    dists = [r["distance_km"] for r in rows]
    assert dists == sorted(dists)


def test_studio_type_filter(overview):
    rows = studios.filter_and_rank(
        overview, *MUNICH, radius_km=None,
        studio_types=["PILATES"], gym_info=None, open_now=False,
    )
    assert rows and all(r["studio_type"] == "PILATES" for r in rows)


def test_returns_all_matches_caller_slices(overview):
    rows = studios.filter_and_rank(
        overview, *MUNICH, radius_km=None,
        studio_types=None, gym_info=None, open_now=False,
    )
    assert len(rows) == len(overview)  # all three gyms, no radius cap
    assert len(rows[:1]) == 1  # the server slices to its limit


def test_group_separation_sauna():
    vocab = _load("search_filter_wellpass.json")
    activity_index = studios.build_slug_index(vocab, "activity-")
    service_index = studios.build_slug_index(vocab, "service-")
    assert studios.resolve_slugs(["sauna"], activity_index)[0] == ["activity-sauna"]
    assert studios.resolve_slugs(["sauna"], service_index)[0] == ["service-sauna"]


def test_suggest_slugs_for_typo():
    vocab = _load("search_filter_wellpass.json")
    activity_index = studios.build_slug_index(vocab, "activity-")
    suggestions = studios.suggest_slugs("yga", activity_index)
    assert "activity-yoga" in suggestions


def test_decode_overview_shape(overview):
    row = studios.decode_overview(overview[0], 1.234)
    assert set(row) >= {"name", "slug", "distance_km", "activities", "studio_type"}
    assert row["distance_km"] == 1.23


# --- opening hours ---------------------------------------------------------

def _next_weekday(target: int) -> datetime:
    tz = ZoneInfo("Europe/Berlin")
    d = datetime(2026, 10, 5, 10, 0, tzinfo=tz)  # a Monday
    while d.weekday() != target:
        d += timedelta(days=1)
    return d


def test_is_open_at_within_hours(overview):
    river = next(g for g in overview if g["a"].startswith("Riverside"))
    monday_10 = _next_weekday(0).replace(hour=10)
    assert studios.is_open_at(river, monday_10) is True


def test_is_open_at_outside_hours(overview):
    river = next(g for g in overview if g["a"].startswith("Riverside"))
    monday_3am = _next_weekday(0).replace(hour=3)
    assert studios.is_open_at(river, monday_3am) is False


def test_is_open_at_unknown_when_no_tz():
    assert studios.is_open_at({"ov2": {}, "tz": None}) is None


# --- detail ----------------------------------------------------------------

def test_decode_detail_shape():
    detail = studios.decode_detail(_load("detail_sample.json"))
    assert detail["slug"]
    assert "address" in detail and "city" in detail["address"]
    assert "class_booking_config" in detail
