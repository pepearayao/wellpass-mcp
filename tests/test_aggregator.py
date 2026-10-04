"""Integration tests for search_classes_near (network mocked)."""
from __future__ import annotations

import json
from pathlib import Path

from wellpass_mcp import gymfinder, netpulse, server

SAMPLE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "classes_sample.json").read_text())

# Two studios at the Munich search point: A is native (has classes), B is not.
GYM_A = {"g": "clubA", "a": "Native Gym", "slug": "native-gym", "lat": 48.137154,
         "lng": 11.576124, "tz": "Europe/Berlin", "st": "GYM",
         "cbc": {"e": True}, "ac": [{"a": "FITNESS"}]}
GYM_B = {"g": "clubB", "a": "External Yoga", "slug": "external-yoga", "lat": 48.1372,
         "lng": 11.5762, "tz": "Europe/Berlin", "st": "YOGA_STUDIO",
         "cbc": {"e": True}, "ac": [{"a": "YOGA"}]}


def _setup(monkeypatch):
    netpulse._native_status.clear()
    monkeypatch.setattr(gymfinder, "fetch_overview", lambda *a, **k: [GYM_A, GYM_B])
    monkeypatch.setattr(netpulse, "home_club_uuid", lambda: None)  # skip online

    def fake_fetch(club, start, end, class_type=None):
        if club == "clubA":
            return SAMPLE
        raise netpulse.WrongClubError("Wrong club")

    monkeypatch.setattr(netpulse, "fetch_classes", fake_fetch)


def test_native_studio_classes_shown(monkeypatch):
    _setup(monkeypatch)
    res = server.search_classes_near(location="Munich", radius_km=5.0, include_online=False)
    assert "Native Gym" in res["studios_with_classes"]
    assert res["total"] == len(SAMPLE)
    assert all(c["studio"] == "Native Gym" for c in res["classes"])


def test_without_times_hidden_by_default(monkeypatch):
    _setup(monkeypatch)
    res = server.search_classes_near(location="Munich", radius_km=5.0, include_online=False)
    assert res["studios_without_times"] == []


def test_without_times_included_on_request(monkeypatch):
    _setup(monkeypatch)
    res = server.search_classes_near(
        location="Munich", radius_km=5.0, include_online=False,
        include_studios_without_times=True,
    )
    names = [s["name"] for s in res["studios_without_times"]]
    assert "External Yoga" in names
    assert "Native Gym" not in names  # native one is not duplicated here


def test_category_filter_applies(monkeypatch):
    _setup(monkeypatch)
    res = server.search_classes_near(
        location="Munich", radius_km=5.0, include_online=False, category="body & mind",
    )
    assert res["total"] >= 1
    assert all("body & mind" in (c["category"] or "").lower() for c in res["classes"])
