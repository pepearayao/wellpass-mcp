"""Wellpass MCP server (stdio).

Read-only. Searches the EGYM Wellpass studio finder. Class/course search is not
built yet (it needs the mobile app recon — see docs/api-contract.md).
"""
from __future__ import annotations

import time

import httpx
from mcp.server.mcpserver import MCPServer

from . import classes, geocode, gymfinder, netpulse, studios

mcp = MCPServer("wellpass")


def _search_filter(region: str) -> str:
    return gymfinder.SEARCH_FILTERS.get(region, gymfinder.DEFAULT_SEARCH_FILTER)


@mcp.tool()
def search_studios(
    location: str = "Munich",
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 10.0,
    activities: list[str] | None = None,
    services: list[str] | None = None,
    plus_one: bool = False,
    studio_types: list[str] | None = None,
    gym_info: list[str] | None = None,
    open_now: bool = False,
    limit: int = 20,
    region: str = "dach",
) -> dict:
    """Search EGYM Wellpass studios (gyms) near a location, with filters.

    Args:
        location: City or place name. Default "Munich". Ignored if latitude and
            longitude are both given.
        latitude: Optional exact latitude of the search point.
        longitude: Optional exact longitude of the search point.
        radius_km: Only return studios within this distance. Default 10 km.
        activities: Activity filters. Accept a slug ("activity-yoga"), a bare
            name ("yoga"), an activity type ("YOGA"), or a label ("Yoga").
            Several activities are combined with OR.
        services: Service/amenity filters, same spelling rules (e.g. "sauna",
            "service-sauna", "free-parking"). Combined with AND across groups.
        plus_one: Only studios that allow a Plus1 guest.
        studio_types: Keep only these studio types (e.g. "PILATES", "WELLNESS").
        gym_info: Require these gym-info flags (e.g. "COURSES_IN_ENGLISH",
            "ACCESSIBLE_TO_PREGNANT_WOMEN").
        open_now: Only studios open at the current local time.
        limit: Max studios to return (1-50). Default 20.
        region: Catalog: "dach" (default), "all", "us", "fr-be", "dach-us".

    Returns:
        A dict with the resolved center, applied filters, and a ranked studio
        list (nearest first). Call list_studio_filters for valid filter values.
    """
    search_filter = _search_filter(region)

    if latitude is not None and longitude is not None:
        lat, lon = latitude, longitude
        resolved_location = f"{lat:.5f},{lon:.5f}"
    else:
        coords = geocode.geocode(location)
        if coords is None:
            return {"error": f"Could not resolve location: {location!r}"}
        lat, lon = coords
        resolved_location = location

    vocab = gymfinder.fetch_search_filter(search_filter)
    # One index per facet, so "sauna" in `activities` resolves to activity-sauna
    # and "sauna" in `services` resolves to service-sauna. Never cross groups.
    activity_index = studios.build_slug_index(vocab, "activity-")
    service_index = studios.build_slug_index(vocab, "service-")
    activity_slugs, unknown_a = studios.resolve_slugs(activities or [], activity_index)
    service_slugs, unknown_s = studios.resolve_slugs(services or [], service_index)

    # Fail loud on an unknown filter. A silent drop would widen the search.
    if unknown_a or unknown_s:
        problems = []
        for value in unknown_a:
            problems.append(
                {"argument": "activities", "value": value,
                 "did_you_mean": studios.suggest_slugs(value, activity_index)}
            )
        for value in unknown_s:
            problems.append(
                {"argument": "services", "value": value,
                 "did_you_mean": studios.suggest_slugs(value, service_index)}
            )
        return {
            "error": "Unknown filter value(s). Call list_studio_filters for valid values.",
            "unresolved_filters": problems,
        }

    slugs = list(activity_slugs) + list(service_slugs)
    if plus_one:
        slugs.append("wellpass-plus-one")

    limit = max(1, min(int(limit), 50))
    gyms = gymfinder.fetch_overview(search_filter, slugs)
    matched = studios.filter_and_rank(
        gyms, lat, lon, radius_km, studio_types, gym_info, open_now
    )

    return {
        "location": resolved_location,
        "center": {"lat": lat, "lng": lon},
        "radius_km": radius_km,
        "region": region,
        "applied_filters": {
            "activities": activity_slugs,
            "services": service_slugs,
            "plus_one": plus_one,
            "studio_types": studio_types or [],
            "gym_info": gym_info or [],
            "open_now": open_now,
        },
        "total_in_radius": len(matched),
        "returned": min(len(matched), limit),
        "studios": matched[:limit],
    }


@mcp.tool()
def get_studio_details(slug: str) -> dict:
    """Get full details for one studio by its slug (from search_studios)."""
    gym = gymfinder.fetch_detail(slug)
    if not gym:
        return {"error": f"No studio found for slug {slug!r}"}
    return studios.decode_detail(gym)


@mcp.tool()
def list_studio_filters(region: str = "dach", language: str = "en") -> dict:
    """List every studio filter value: activities, services, toggles, categories.

    This is the ground truth for the `activities` and `services` arguments of
    search_studios. `language` picks the label language (de/en/fr/nl).
    """
    search_filter = _search_filter(region)
    groups_out: list[dict] = []
    for group in gymfinder.fetch_search_filter(search_filter):
        text = group.get("text") or {}
        groups_out.append(
            {
                "group": text.get(language) or text.get("en"),
                "type": group.get("type"),
                "always_active": group.get("alwaysActive", False),
                "filters": [
                    {
                        "slug": f.get("slug"),
                        "label": (f.get("text") or {}).get(language)
                        or (f.get("text") or {}).get("en"),
                    }
                    for f in group.get("filters", [])
                ],
            }
        )

    categories = [
        {
            "category": c.get("category"),
            "activity_types": [a.get("activityType") for a in c.get("activities", [])],
        }
        for c in gymfinder.fetch_activities()
    ]

    return {
        "region": region,
        "filter_groups": groups_out,
        "activity_taxonomy": categories,
        "notes": {
            "studio_types": "Filter with studio_types; values appear as studio_type in results (e.g. PILATES, WELLNESS).",
            "gym_info": "Filter with gym_info; values appear as gym_info in results (e.g. COURSES_IN_ENGLISH).",
        },
    }


@mcp.tool()
def search_classes(
    studio_slug: str | None = None,
    club_uuid: str | None = None,
    online: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    category: str | None = None,
    teacher: str | None = None,
    available_only: bool = False,
    limit: int = 30,
) -> dict:
    """Search bookable Wellpass classes for a studio (or online), with filters.

    Needs WELLPASS_EMAIL and WELLPASS_PASSWORD in .env (classes are gated).

    Pick ONE target:
        - studio_slug: a studio from search_studios (its classes).
        - club_uuid: the `club_uuid` field from a search_studios result.
        - online=True: the online / live-stream class catalogue.

    Args:
        studio_slug: Studio slug whose classes to list.
        club_uuid: Netpulse club uuid (from search_studios `club_uuid`).
        online: Search the online class catalogue instead of a studio.
        date_from: ISO date/datetime for the window start. Default: now.
        date_to: ISO date/datetime for the window end. Default: now + 7 days.
        category: Keep classes whose activity matches (e.g. "yoga", "Body & Mind").
        teacher: Keep classes by this instructor (substring, case-insensitive).
        available_only: Keep only classes with a free spot.
        limit: Max classes to return (1-100). Default 30.

    Returns:
        A dict with the resolved club, the window, and a class list (soonest
        first). Each class has name, category, start/end, teacher, free spots,
        capacity, and online flag.
    """
    try:
        tz = classes.DEFAULT_TZ
        if club_uuid:
            club = club_uuid
            target = f"club {club_uuid}"
        elif studio_slug:
            gym = gymfinder.fetch_detail(studio_slug)
            if not gym:
                return {"error": f"No studio found for slug {studio_slug!r}"}
            club = gym.get("gymUUID")
            target = gym.get("gymChainName") or studio_slug
            tz = gym.get("timezone") or tz
        elif online:
            club = netpulse.home_club_uuid()
            target = "online classes"
        else:
            return {"error": "Give studio_slug, club_uuid, or online=True."}

        if not club:
            return {"error": "Could not resolve a club uuid for this target."}

        # Date window. A bad date is an error, not a silent fallback (an LLM may
        # send "tomorrow"; reject it clearly).
        now = int(time.time() * 1000)
        try:
            start_ms, end_ms = classes.resolve_window(date_from, date_to, now)
        except ValueError as exc:
            return {"error": str(exc)}

        limit = max(1, min(int(limit), 100))
        raw = netpulse.fetch_classes(club, start_ms, end_ms)
        rows = [classes.decode_class(c, tz) for c in raw]
        rows = classes.filter_classes(
            rows, teacher=teacher, category=category,
            online=(online if online else None), available_only=available_only,
        )
        for r in rows:
            r.pop("start_ms", None)
        return {
            "target": target,
            "club_uuid": club,
            "window": {"from": classes._iso(start_ms, tz), "to": classes._iso(end_ms, tz)},
            "filters": {
                "category": category, "teacher": teacher,
                "online": online, "available_only": available_only,
            },
            "total": len(rows),
            "returned": min(len(rows), limit),
            "classes": rows[:limit],
        }
    except netpulse.WrongClubError:
        return {"error": "This studio does not offer in-app class booking (Wrong club). "
                         "Try another studio, or online=True."}
    except netpulse.AuthError as exc:
        return {"error": str(exc)}


@mcp.tool()
def search_classes_near(
    location: str = "Munich",
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 5.0,
    date_from: str | None = None,
    date_to: str | None = None,
    category: str | None = None,
    teacher: str | None = None,
    available_only: bool = False,
    include_online: bool = True,
    include_studios_without_times: bool = False,
    limit: int = 40,
) -> dict:
    """Find bookable classes NEAR a location, across studios, with filters.

    Needs login (.env). Note: only a minority of studios expose structured
    classes (Netpulse-native, e.g. Fitness First); most small studios use
    external booking and are not included. Online classes are included by
    default. The first call near a new area is slower (it probes studios); later
    calls are fast (native studios are cached).

    Args:
        location: City/place. Default Munich. Ignored if latitude+longitude set.
        latitude, longitude: Exact search point.
        radius_km: Only studios within this distance. Default 5 km.
        date_from, date_to: ISO date/datetime window. Default: now .. now+7d.
        category: Keep classes whose activity matches (e.g. "yoga", "cardio").
        teacher: Keep classes by this instructor (substring, case-insensitive).
        available_only: Keep only classes with a free spot.
        include_online: Also include the online class catalogue. Default true.
        include_studios_without_times: Also list nearby studios that offer
            classes but expose no in-app schedule (external booking). They come
            back under `studios_without_times`, not as timed classes. Default
            false (hide them).
        limit: Max classes to return (1-100). Default 40. Soonest first.

    Returns:
        Classes (soonest first), each with studio, distance_km, club_uuid, and a
        class id — pass club_uuid + id to book_class.
    """
    try:
        if latitude is not None and longitude is not None:
            lat, lon = latitude, longitude
            where = f"{lat:.4f},{lon:.4f}"
        else:
            coords = geocode.geocode(location)
            if coords is None:
                return {"error": f"Could not resolve location: {location!r}"}
            lat, lon = coords
            where = location

        now = int(time.time() * 1000)
        try:
            start_ms, end_ms = classes.resolve_window(date_from, date_to, now)
        except ValueError as exc:
            return {"error": str(exc)}

        gyms = gymfinder.fetch_overview("wellpass")
        nearest = sorted(
            (
                (studios.haversine_km(lat, lon, g["lat"], g["lng"]), g)
                for g in gyms
                if g.get("lat") is not None and g.get("lng") is not None
            ),
            key=lambda pair: pair[0],
        )

        rows: list[dict] = []
        studios_with_classes: list[str] = []
        native_clubs: set[str] = set()
        checked = 0
        max_check = 22  # bound probing cost on a cold area
        for dist, gym in nearest:
            if dist > radius_km or checked >= max_check:
                break
            club = gym.get("g")
            if not club or netpulse.native_status(club) is False:
                continue
            checked += 1
            try:
                raw = netpulse.fetch_classes(club, start_ms, end_ms)
            except (netpulse.WrongClubError, httpx.HTTPError):
                continue
            native_clubs.add(club)
            studios_with_classes.append(gym.get("a"))
            tz = gym.get("tz") or classes.DEFAULT_TZ
            for c in raw:
                r = classes.decode_class(c, tz)
                r["studio"] = gym.get("a")
                r["studio_slug"] = gym.get("slug")
                r["distance_km"] = round(dist, 2)
                rows.append(r)

        # Studios that offer classes but expose no in-app schedule (external
        # booking). Cheap: derived from the gym-finder data, no extra calls.
        studios_without_times: list[dict] = []
        if include_studios_without_times:
            for dist, gym in nearest:
                if dist > radius_km or len(studios_without_times) >= 25:
                    break
                club = gym.get("g")
                cbc = gym.get("cbc") or {}
                if not club or club in native_clubs or not cbc.get("e"):
                    continue
                studios_without_times.append({
                    "name": gym.get("a"),
                    "slug": gym.get("slug"),
                    "distance_km": round(dist, 2),
                    "studio_type": gym.get("st"),
                    "activities": [a.get("a") for a in gym.get("ac", []) if a.get("a")],
                    "note": "Offers classes, but no in-app schedule. Book via the "
                            "studio profile / its own site.",
                })

        if include_online:
            home = netpulse.home_club_uuid()
            if home:
                try:
                    for c in netpulse.fetch_classes(home, start_ms, end_ms):
                        r = classes.decode_class(c, classes.DEFAULT_TZ)
                        r["studio"] = "Online"
                        r["studio_slug"] = None
                        r["distance_km"] = None
                        rows.append(r)
                except (netpulse.WrongClubError, httpx.HTTPError):
                    pass

        rows = classes.filter_classes(
            rows, teacher=teacher, category=category,
            online=None, available_only=available_only,
        )
        for r in rows:
            r.pop("start_ms", None)

        return {
            "location": where,
            "radius_km": radius_km,
            "window": {"from": classes._iso(start_ms), "to": classes._iso(end_ms)},
            "filters": {"category": category, "teacher": teacher,
                        "available_only": available_only, "include_online": include_online},
            "studios_with_classes": studios_with_classes,
            "studios_without_times": studios_without_times,
            "note": "Only Netpulse-native studios expose structured classes; "
                    "most small studios use external booking. Set "
                    "include_studios_without_times=true to also list those.",
            "total": len(rows),
            "returned": min(len(rows), max(1, min(int(limit), 100))),
            "classes": rows[: max(1, min(int(limit), 100))],
        }
    except netpulse.AuthError as exc:
        return {"error": str(exc)}


def _class_summary(obj: dict, tz: str = classes.DEFAULT_TZ) -> dict:
    row = classes.decode_class(obj, tz)
    details = obj.get("details", {}) or {}
    row["cancellation_window_end"] = classes._iso(details.get("cancellationWindowEnd"), tz)
    row["booking_window_end"] = classes._iso(details.get("bookingWindowEnd"), tz)
    row.pop("start_ms", None)
    return row


def _find_upcoming_class(club_uuid: str, class_id: str) -> dict | None:
    """Find a class object by id in the club's upcoming schedule.

    Uses the working class-list endpoint (the per-class detail endpoint is
    unreliable). The list already carries the cancellation window.
    """
    now = int(time.time() * 1000)
    raw = netpulse.fetch_classes(club_uuid, now, now + 60 * 86400 * 1000)
    return next((c for c in raw if (c.get("brief") or {}).get("id") == class_id), None)


@mcp.tool()
def book_class(club_uuid: str, class_id: str, confirm: bool = False, spot: str | None = None) -> dict:
    """Book the user into a class. TWO-STEP and WRITES to the real account.

    Step 1 (confirm=false, default): returns the class details and cancellation
    window and does NOT book. Relay this to the user.
    Step 2 (confirm=true): actually books. Only send confirm=true AFTER the user
    has explicitly agreed to book this specific class.

    Args:
        club_uuid: The class's club_uuid (from a search result).
        class_id: The class id (from a search result).
        confirm: Must be true to actually book. Default false (preview only).
        spot: Optional spot id, for studios with spot selection.
    """
    try:
        if not confirm:
            match = _find_upcoming_class(club_uuid, class_id)
            if not match:
                return {"error": "Class not found in the upcoming schedule for this club. "
                                 "Re-run a class search to get a current id."}
            return {
                "action": "preview",
                "requires_confirmation": True,
                "class": _class_summary(match),
                "message": "This will book a real spot in your account. "
                           "To book, call book_class again with confirm=true — "
                           "only after the user explicitly agrees.",
            }
        result = netpulse.book_class(club_uuid, class_id, spot)
        return {"action": "booked", "class": _class_summary(result)}
    except netpulse.WrongClubError:
        return {"error": "This studio does not offer in-app class booking."}
    except netpulse.AuthError as exc:
        return {"error": str(exc)}
    except httpx.HTTPStatusError as exc:
        return {"error": f"Booking failed (HTTP {exc.response.status_code}): {exc.response.text[:200]}"}


@mcp.tool()
def cancel_booking(club_uuid: str, class_id: str, confirm: bool = False) -> dict:
    """Cancel the user's booking for a class. TWO-STEP and WRITES to the account.

    confirm=false (default) previews; confirm=true cancels. Only cancel after the
    user explicitly agrees. Check the cancellation window first.
    """
    try:
        if not confirm:
            match = _find_upcoming_class(club_uuid, class_id)
            if not match:
                return {"error": "Class not found in the upcoming schedule for this club. "
                                 "Re-run a class search to get a current id."}
            return {
                "action": "preview",
                "requires_confirmation": True,
                "class": _class_summary(match),
                "message": "To cancel, call cancel_booking again with confirm=true — "
                           "only after the user explicitly agrees.",
            }
        result = netpulse.cancel_class(club_uuid, class_id)
        return {"action": "cancelled", "class": _class_summary(result)}
    except netpulse.WrongClubError:
        return {"error": "This studio does not offer in-app class booking."}
    except netpulse.AuthError as exc:
        return {"error": str(exc)}
    except httpx.HTTPStatusError as exc:
        return {"error": f"Cancel failed (HTTP {exc.response.status_code}): {exc.response.text[:200]}"}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
