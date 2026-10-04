"""Studio search logic: slug resolution, geo distance, filtering, decoding.

The heavy lifting is pure. `filter_and_rank` takes a gym list (from the gym
finder overview endpoint) and returns ranked, decoded records. This keeps the
logic testable without network calls.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import gymfinder

_WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Filter-slug resolution
# ---------------------------------------------------------------------------

def _normalize(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(" ", "-")


def build_slug_index(
    search_filter_vocab: list[dict], slug_prefix: str | None = None
) -> dict[str, str]:
    """Map many spellings (slug, bare name, localized label) -> canonical slug.

    `slug_prefix` restricts the index to one facet, so an argument never leaks
    into the wrong group. Use "activity-" for activities and "service-" for
    services. `activity-sauna` and `service-sauna` both exist, so the group
    must be chosen by the caller, not guessed.
    """
    index: dict[str, str] = {}
    for group in search_filter_vocab:
        for entry in group.get("filters", []):
            slug = entry.get("slug")
            if not slug:
                continue
            if slug_prefix and not slug.startswith(slug_prefix):
                continue
            index[slug.lower()] = slug
            if "-" in slug:
                bare = slug.split("-", 1)[1]
                index.setdefault(bare.lower(), slug)
            for label in (entry.get("text") or {}).values():
                if label:
                    index.setdefault(label.lower(), slug)
    return index


def suggest_slugs(value: str, index: dict[str, str], limit: int = 5) -> list[str]:
    """Return up to `limit` canonical slugs closest to an unresolved value."""
    import difflib

    keys = difflib.get_close_matches(value.strip().lower(), index.keys(), n=limit, cutoff=0.5)
    out: list[str] = []
    for key in keys:
        slug = index[key]
        if slug not in out:
            out.append(slug)
    return out


def resolve_slugs(
    values: list[str], index: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Return (resolved canonical slugs, unresolved inputs)."""
    resolved: list[str] = []
    unknown: list[str] = []
    for value in values or []:
        norm = _normalize(value)
        bare = value.strip().lower()
        hit = (
            index.get(bare)
            or index.get(norm)
            or index.get(f"activity-{norm}")
            or index.get(f"service-{norm}")
        )
        if hit:
            resolved.append(hit)
        else:
            unknown.append(value)
    # dedupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for slug in resolved:
        if slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out, unknown


# ---------------------------------------------------------------------------
# Opening hours
# ---------------------------------------------------------------------------

def is_open_at(gym: dict, when: datetime | None = None) -> bool | None:
    """Return True/False if open at `when` (gym-local), or None if unknown.

    Uses the structured `ov2` hours. Ignores holidays and one-off exceptions.
    """
    ov2 = gym.get("ov2")
    tz_name = gym.get("tz")
    if not isinstance(ov2, dict) or not tz_name:
        return None
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        return None
    now = when.astimezone(tz) if when else datetime.now(tz)
    day_key = _WEEKDAYS[now.weekday()]
    intervals = ov2.get(day_key)
    if intervals in (None, "NOT_AVAILABLE") or not isinstance(intervals, list):
        return False
    minutes_now = now.hour * 60 + now.minute
    for interval in intervals:
        start = interval.get("start") or {}
        end = interval.get("end") or {}
        try:
            s = start["hour"] * 60 + start.get("minute", 0)
            e = end["hour"] * 60 + end.get("minute", 0)
        except (KeyError, TypeError):
            continue
        if s <= minutes_now <= e:
            return True
    return False


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def _class_booking_hint(cbc: Any) -> bool:
    """Best-effort flag: does the gym support class booking?

    `cbc.e` appears to mean "enabled". UNCONFIRMED — verify in phone recon.
    """
    if not isinstance(cbc, dict):
        return False
    return bool(cbc.get("e"))


def decode_overview(gym: dict, distance_km: float | None) -> dict:
    """Turn a compact overview gym into a clean record."""
    options = gym.get("op")
    gi = options.get("gi", []) if isinstance(options, dict) else []
    return {
        "name": gym.get("a"),
        "slug": gym.get("slug"),
        "club_uuid": gym.get("g"),  # Netpulse clubUuid — pass to search_classes
        "distance_km": round(distance_km, 2) if distance_km is not None else None,
        "lat": gym.get("lat"),
        "lng": gym.get("lng"),
        "studio_type": gym.get("st"),
        "activities": [a.get("a") for a in gym.get("ac", []) if a.get("a")],
        "membership_types": gym.get("mt", []),
        "plus_one": bool(gym.get("qtpone")),
        "gym_info": gi,
        "class_booking_hint": _class_booking_hint(gym.get("cbc")),
        "network": gym.get("n"),
        "state": gym.get("sp"),
        "image": gym.get("bimg"),
    }


def decode_detail(gym: dict) -> dict:
    """Turn a full gym object into a clean record."""
    address = gym.get("address") or {}
    return {
        "name": gym.get("gymChainName") or gym.get("alias"),
        "slug": gym.get("slug"),
        "gym_id": gym.get("gymId"),
        "studio_type": gym.get("studioType"),
        "description": gym.get("description"),
        "offer": gym.get("qualitrainOfferDescription"),
        "address": {
            "street": address.get("street"),
            "zip": address.get("zip") or address.get("postalCode"),
            "city": address.get("city"),
            "country": address.get("country"),
            "lat": address.get("latitude") or gym.get("latitude"),
            "lng": address.get("longitude") or gym.get("longitude"),
        },
        "phone": gym.get("phone"),
        "email": gym.get("email"),
        "website": gym.get("website"),
        "membership_types": gym.get("membershipTypes", []),
        "options": gym.get("options", []),
        "opening_hours": gym.get("openingHoursV2") or gym.get("openingHours"),
        "class_booking_config": gym.get("classBookingConfig"),
        "external_booking_info": gym.get("externalBookingInfo"),
        "plus_one": bool(gym.get("qualitrainPlusOneGym")),
        "timezone": gym.get("timezone"),
    }


# ---------------------------------------------------------------------------
# Core search (pure over a given gym list)
# ---------------------------------------------------------------------------

def filter_and_rank(
    gyms: list[dict],
    lat: float,
    lon: float,
    radius_km: float | None,
    studio_types: list[str] | None,
    gym_info: list[str] | None,
    open_now: bool,
) -> list[dict]:
    """Filter by geo + local criteria, sort by distance, decode.

    Returns every match (no cap). The caller slices to its limit, so it can
    also report the total number of matches within the radius.
    """
    studio_set = {s.upper() for s in (studio_types or [])}
    info_set = {g.upper() for g in (gym_info or [])}
    scored: list[tuple[float, dict]] = []
    for gym in gyms:
        glat, glng = gym.get("lat"), gym.get("lng")
        if glat is None or glng is None:
            continue
        dist = haversine_km(lat, lon, glat, glng)
        if radius_km is not None and dist > radius_km:
            continue
        if studio_set and str(gym.get("st", "")).upper() not in studio_set:
            continue
        if info_set:
            opt = gym.get("op")
            have = {str(x).upper() for x in (opt.get("gi", []) if isinstance(opt, dict) else [])}
            if not info_set.issubset(have):
                continue
        if open_now and is_open_at(gym) is not True:
            continue
        scored.append((dist, gym))
    scored.sort(key=lambda pair: pair[0])
    return [decode_overview(gym, dist) for dist, gym in scored]
