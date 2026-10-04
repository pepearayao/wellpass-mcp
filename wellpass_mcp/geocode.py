"""Turn a place name into latitude/longitude.

Order:
1. A small built-in table of common cities (no network; Munich is the default).
2. OpenStreetMap Nominatim (free, no key). Rate limited to 1 request/second.

Results are cached in memory for the process lifetime.
"""
from __future__ import annotations

import threading
import time

import httpx

# place -> (lat, lon)
KNOWN_CITIES: dict[str, tuple[float, float]] = {
    "munich": (48.137154, 11.576124),
    "münchen": (48.137154, 11.576124),
    "muenchen": (48.137154, 11.576124),
    "berlin": (52.520008, 13.404954),
    "hamburg": (53.551086, 9.993682),
    "cologne": (50.935173, 6.953101),
    "köln": (50.935173, 6.953101),
    "frankfurt": (50.110924, 8.682127),
    "stuttgart": (48.775846, 9.182932),
    "vienna": (48.208176, 16.373819),
    "wien": (48.208176, 16.373819),
    "zurich": (47.376887, 8.541694),
    "zürich": (47.376887, 8.541694),
}

DEFAULT_CITY = "munich"
DEFAULT_COORDS = KNOWN_CITIES["munich"]

_NOMINATIM = "https://nominatim.openstreetmap.org/search"
_UA = "wellpass-mcp/0.1 (personal studio search)"

_cache: dict[str, tuple[float, float]] = {}
_lock = threading.Lock()
_last_call = 0.0


def geocode(place: str | None) -> tuple[float, float] | None:
    """Return (lat, lon) for a place, or None if it cannot be resolved."""
    if not place or not place.strip():
        return DEFAULT_COORDS
    key = place.strip().lower()
    if key in KNOWN_CITIES:
        return KNOWN_CITIES[key]
    with _lock:
        if key in _cache:
            return _cache[key]
    coords = _nominatim(place)
    if coords is not None:
        with _lock:
            _cache[key] = coords
    return coords


def _nominatim(place: str) -> tuple[float, float] | None:
    global _last_call
    with _lock:
        wait = 1.0 - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent": _UA}) as client:
            resp = client.get(
                _NOMINATIM,
                params={"q": place, "format": "json", "limit": 1},
            )
            resp.raise_for_status()
            rows = resp.json()
    except Exception:
        return None
    if not rows:
        return None
    try:
        return float(rows[0]["lat"]), float(rows[0]["lon"])
    except (KeyError, ValueError, TypeError):
        return None
