"""Client for the EGYM Wellpass studio finder API (the "gym finder").

This API is public. It needs no auth. See `docs/api-contract.md`.

Base: https://gymfinder.int.api.egym.com
- /v1/gym/overview  — compact gym list (no geo param; filter by slug)
- /v1/gym/count     — count for a filter set
- /v1/gym?slug=     — full detail for one gym
- /v1/search-filter/<profile> — filter vocabulary (slugs + localized labels)
- /v1/activities    — category -> activity-type taxonomy
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

import httpx

BASE_URL = "https://gymfinder.int.api.egym.com"

# Region catalogs. The value is the API `searchFilter` profile.
SEARCH_FILTERS = {
    "dach": "wellpass",
    "all": "wellpass-all",
    "us": "wellpass-us",
    "fr-be": "wellpass-fr-be",
    "dach-us": "wellpass-dach-and-us",
}
DEFAULT_SEARCH_FILTER = "wellpass"

_USER_AGENT = "wellpass-mcp/0.1 (personal studio search)"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

OVERVIEW_TTL = 6 * 3600
VOCAB_TTL = 24 * 3600


class _TTLCache:
    """A small TTL cache with optional LRU eviction.

    The overview payloads are large (8-21 MB of JSON each), so the overview
    cache is capped. The vocabulary cache is tiny and uncapped.
    """

    def __init__(self, maxsize: int | None = None) -> None:
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float) -> Any | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            ts, value = hit
            if time.time() - ts > ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.time(), value)
            self._data.move_to_end(key)
            if self._maxsize is not None:
                while len(self._data) > self._maxsize:
                    self._data.popitem(last=False)


_overview_cache = _TTLCache(maxsize=3)
_vocab_cache = _TTLCache()


def _get_json(path: str, params: list[tuple[str, str]] | dict | None = None) -> Any:
    with httpx.Client(
        base_url=BASE_URL,
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        timeout=_TIMEOUT,
    ) as client:
        resp = client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()


def _filter_params(search_filter: str, slugs: list[str]) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = [("searchFilter", search_filter)]
    for slug in sorted(set(slugs)):
        params.append(("filter", slug))
    return params


def fetch_overview(
    search_filter: str = DEFAULT_SEARCH_FILTER,
    filter_slugs: list[str] | None = None,
    limit: int = 20000,
) -> list[dict]:
    """Return the compact gym list for a filter set (cached)."""
    slugs = sorted(set(filter_slugs or []))
    key = f"ov::{search_filter}::{','.join(slugs)}::{limit}"
    cached = _overview_cache.get(key, OVERVIEW_TTL)
    if cached is not None:
        return cached
    params = _filter_params(search_filter, slugs)
    params.append(("limit", str(limit)))
    data = _get_json("/v1/gym/overview", params)
    gyms = data.get("gyms", []) if isinstance(data, dict) else data
    _overview_cache.set(key, gyms)
    return gyms


def fetch_count(
    search_filter: str = DEFAULT_SEARCH_FILTER,
    filter_slugs: list[str] | None = None,
) -> int:
    """Return the gym count for a filter set."""
    data = _get_json("/v1/gym/count", _filter_params(search_filter, filter_slugs or []))
    return int(data)


def fetch_detail(slug: str) -> dict | None:
    """Return the full gym object for one slug, or None."""
    data = _get_json("/v1/gym", {"slug": slug})
    if isinstance(data, list):
        return data[0] if data else None
    return data


def fetch_search_filter(search_filter: str = DEFAULT_SEARCH_FILTER) -> list[dict]:
    """Return the filter vocabulary (groups + slugs + localized labels)."""
    key = f"sf::{search_filter}"
    cached = _vocab_cache.get(key, VOCAB_TTL)
    if cached is not None:
        return cached
    data = _get_json(f"/v1/search-filter/{search_filter}")
    _vocab_cache.set(key, data)
    return data


def fetch_activities(locale: str = "de_DE") -> list[dict]:
    """Return the category -> activity-type taxonomy."""
    key = f"acts::{locale}"
    cached = _vocab_cache.get(key, VOCAB_TTL)
    if cached is not None:
        return cached
    data = _get_json("/v1/activities", {"locale": locale})
    _vocab_cache.set(key, data)
    return data
