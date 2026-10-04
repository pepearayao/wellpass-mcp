"""Class decode + client-side filtering (pure logic, testable without network)."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Europe/Berlin"


def _iso(ms: int | None, tz: str = DEFAULT_TZ) -> str | None:
    """Format an epoch-ms instant in a studio-local timezone.

    The server stores true UTC epochs. We render them in the studio timezone so
    the time the user sees matches the app (e.g. 19:35+02:00, not 17:35Z).
    """
    if not ms:
        return None
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = timezone.utc
    return datetime.fromtimestamp(ms / 1000, tz=zone).isoformat()


def available_spots(brief: dict) -> int | None:
    """Free spots = maxCapacity - totalBooked. `availableSpots` is usually null."""
    if brief.get("availableSpots") is not None:
        return brief["availableSpots"]
    cap = brief.get("maxCapacity")
    booked = brief.get("totalBooked")
    if cap is None or booked is None:
        return None
    return max(cap - booked, 0)


def decode_class(obj: dict, tz: str = DEFAULT_TZ) -> dict:
    """Turn a GroupXClass into a clean record. Times render in `tz`."""
    brief = obj.get("brief", {}) or {}
    details = obj.get("details", {}) or {}
    instructor = brief.get("instructor") or {}
    activity = brief.get("activity") or {}
    free = available_spots(brief)
    cap = brief.get("maxCapacity")
    return {
        "id": brief.get("id"),
        "name": brief.get("name"),
        "category": activity.get("description") or activity.get("id"),
        "start": _iso(brief.get("startDateTime"), tz),
        "end": _iso(brief.get("endDateTime"), tz),
        "start_ms": brief.get("startDateTime"),
        "teacher": instructor.get("fullName"),
        "available_spots": free,
        "max_capacity": cap,
        "booked": brief.get("totalBooked"),
        "is_full": (free == 0) if free is not None else None,
        "online": bool(brief.get("liveStreamClass")),
        "reservable": brief.get("reservable"),
        "cancelled": bool(brief.get("cancelled")),
        "room": details.get("room"),
        "level": details.get("level"),
        "club_uuid": brief.get("clubUuid"),
    }


def filter_classes(
    rows: list[dict],
    teacher: str | None = None,
    category: str | None = None,
    online: bool | None = None,
    available_only: bool = False,
    include_cancelled: bool = False,
) -> list[dict]:
    """Apply client-side filters to decoded class records."""
    out = []
    t = teacher.strip().lower() if teacher else None
    cat = category.strip().lower() if category else None
    for r in rows:
        if not include_cancelled and r.get("cancelled"):
            continue
        if online is not None and bool(r.get("online")) != online:
            continue
        if t and t not in (r.get("teacher") or "").lower():
            continue
        if cat and cat not in (r.get("category") or "").lower():
            continue
        if available_only and not (r.get("available_spots") or 0) > 0:
            continue
        out.append(r)
    out.sort(key=lambda r: r.get("start_ms") or 0)
    return out


def resolve_window(
    date_from: str | None, date_to: str | None, now_ms: int, *, default_days: int = 7
) -> tuple[int, int]:
    """Resolve a (start_ms, end_ms) window. Raises ValueError on bad input.

    - No date_from -> now. No date_to -> start + default_days (NOT now + days).
    - A date that does not parse is an error, not a silent fallback.
    - end before start is an error.
    """
    if date_from is None:
        start_ms = now_ms
    else:
        start_ms = parse_date_to_ms(date_from)
        if start_ms is None:
            raise ValueError(f"Bad date_from {date_from!r}. Use YYYY-MM-DD or ISO datetime.")
    if date_to is None:
        end_ms = start_ms + default_days * 86400 * 1000
    else:
        end_ms = parse_date_to_ms(date_to, end_of_day=True)
        if end_ms is None:
            raise ValueError(f"Bad date_to {date_to!r}. Use YYYY-MM-DD or ISO datetime.")
    if end_ms < start_ms:
        raise ValueError("date_to is before date_from.")
    return start_ms, end_ms


def parse_date_to_ms(value: str | None, *, end_of_day: bool = False) -> int | None:
    """Parse an ISO date or datetime into epoch ms. Returns None if value is None."""
    if not value:
        return None
    value = value.strip()
    try:
        if len(value) == 10:  # YYYY-MM-DD
            dt = datetime.fromisoformat(value)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)
