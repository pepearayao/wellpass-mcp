"""Tests for the two-step booking tools. All writes are mocked (no real calls)."""
from __future__ import annotations

import json
from pathlib import Path

from wellpass_mcp import netpulse, server

SAMPLE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "classes_sample.json").read_text())
CID = SAMPLE[0]["brief"]["id"]
CLUB = SAMPLE[0]["brief"]["clubUuid"]


def test_book_preview_does_not_write(monkeypatch):
    monkeypatch.setattr(netpulse, "fetch_classes", lambda club, s, e, t=None: SAMPLE)
    def boom(*a, **k):  # booking must NOT be called in preview
        raise AssertionError("preview must not book")
    monkeypatch.setattr(netpulse, "book_class", boom)
    r = server.book_class(club_uuid=CLUB, class_id=CID, confirm=False)
    assert r["action"] == "preview"
    assert r["requires_confirmation"] is True
    assert r["class"]["name"]


def test_book_preview_class_not_found(monkeypatch):
    monkeypatch.setattr(netpulse, "fetch_classes", lambda *a, **k: [])
    r = server.book_class(club_uuid=CLUB, class_id="missing", confirm=False)
    assert "error" in r


def test_book_confirm_calls_netpulse(monkeypatch):
    called = {}
    def fake_book(club, cid, spot=None):
        called["args"] = (club, cid)
        return SAMPLE[0]
    monkeypatch.setattr(netpulse, "book_class", fake_book)
    r = server.book_class(club_uuid=CLUB, class_id=CID, confirm=True)
    assert r["action"] == "booked"
    assert called["args"] == (CLUB, CID)


def test_book_wrong_club(monkeypatch):
    def boom(*a, **k):
        raise netpulse.WrongClubError("x")
    monkeypatch.setattr(netpulse, "book_class", boom)
    r = server.book_class(club_uuid=CLUB, class_id=CID, confirm=True)
    assert "error" in r


def test_cancel_confirm_calls_netpulse(monkeypatch):
    called = {}
    def fake_cancel(club, cid):
        called["args"] = (club, cid)
        return SAMPLE[0]
    monkeypatch.setattr(netpulse, "cancel_class", fake_cancel)
    r = server.cancel_booking(club_uuid=CLUB, class_id=CID, confirm=True)
    assert r["action"] == "cancelled"
    assert called["args"] == (CLUB, CID)


def test_auth_error_surfaces(monkeypatch):
    def boom(*a, **k):
        raise netpulse.AuthError("Set WELLPASS_EMAIL and WELLPASS_PASSWORD in .env to search classes.")
    monkeypatch.setattr(netpulse, "book_class", boom)
    r = server.book_class(club_uuid=CLUB, class_id=CID, confirm=True)
    assert "error" in r and "WELLPASS_EMAIL" in r["error"]
