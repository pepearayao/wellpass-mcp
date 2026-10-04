"""Authenticated client for the Netpulse class API (the Wellpass class backend).

Host: https://qualitrain.netpulse.com  (BuildConfig SERVER_URL_BASE).
Auth: session cookie. Login is form-urlencoded username+password; the server
sets JSESSIONID, which is sent on later requests. See docs/api-contract.md.

Credentials come from WELLPASS_EMAIL / WELLPASS_PASSWORD in the environment
(loaded from .env). Studios need no auth; only classes do.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = "https://qualitrain.netpulse.com"
_SESSION_MAX_AGE = 25 * 60  # re-login after this many seconds

# App identity the Netpulse backend expects. Override via env if needed.
_APP_VERSION = os.environ.get("WELLPASS_APP_VERSION", "6.6.1")
_APP_VERSION_CODE = os.environ.get("WELLPASS_APP_VERSION_CODE", "353")
# A per-install device id. Use WELLPASS_DEVICE_ID if set, else a random one.
_DEVICE_ID = os.environ.get("WELLPASS_DEVICE_ID") or str(uuid.uuid4())

# The X-NP-User-Agent is a structured, joined string (see BackendHeaderValues).
_NP_USER_AGENT = (
    "clientType=MOBILE_DEVICE; devicePlatform=ANDROID; "
    f"deviceUid={_DEVICE_ID}; "
    f"applicationName=Wellpass; applicationVersion={_APP_VERSION}; "
    f"applicationVersionCode={_APP_VERSION_CODE}"
)
_HEADERS = {
    "Accept": "application/json",
    "X-NP-API-Version": "1.5",
    "X-NP-APP-Version": _APP_VERSION,
    "X-NP-User-Agent": _NP_USER_AGENT,
    "User-Agent": "okhttp/4.12.0",
}


class AuthError(RuntimeError):
    """Login failed or credentials are missing."""


class WrongClubError(RuntimeError):
    """The club does not offer in-app class booking (HTTP 400 'Wrong club')."""


class NetpulseSession:
    """A lazy, auto-renewing Netpulse login session."""

    def __init__(self) -> None:
        self._client: httpx.Client | None = None
        self._uuid: str | None = None
        self._home_club: str | None = None
        self._logged_in_at = 0.0
        self._lock = threading.Lock()

    def _credentials(self) -> tuple[str, str]:
        email = os.environ.get("WELLPASS_EMAIL")
        password = os.environ.get("WELLPASS_PASSWORD")
        if not email or not password:
            raise AuthError(
                "Set WELLPASS_EMAIL and WELLPASS_PASSWORD in .env to search classes."
            )
        return email, password

    def _login(self) -> None:
        email, password = self._credentials()
        if self._client is not None:
            self._client.close()
        client = httpx.Client(base_url=BASE_URL, headers=_HEADERS, timeout=30.0)
        resp = client.post(
            "/np/exerciser/login",
            data={"username": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            client.close()
            raise AuthError(f"Login failed (HTTP {resp.status_code}).")
        profile = resp.json()
        self._client = client
        self._uuid = profile.get("uuid")
        self._home_club = profile.get("homeClubUuid")
        self._logged_in_at = time.time()

    def _ensure(self) -> None:
        if self._client is None or (time.time() - self._logged_in_at) > _SESSION_MAX_AGE:
            self._login()

    @property
    def uuid(self) -> str:
        with self._lock:
            self._ensure()
            return self._uuid or ""

    @property
    def home_club_uuid(self) -> str | None:
        with self._lock:
            self._ensure()
            return self._home_club

    def get_json(self, path: str, params: dict | None = None) -> Any:
        with self._lock:
            self._ensure()
            assert self._client is not None
            resp = self._client.get(path, params=params)
            if resp.status_code == 401:
                self._login()
                resp = self._client.get(path, params=params)
            if resp.status_code == 400 and "Wrong club" in resp.text:
                raise WrongClubError("This studio does not offer in-app class booking.")
            resp.raise_for_status()
            return resp.json()

    def post_json(self, path: str, params: dict | None = None) -> Any:
        """POST with a form-urlencoded body (matches the app's Call semantics)."""
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        with self._lock:
            self._ensure()
            assert self._client is not None
            resp = self._client.post(path, data=params or {}, headers=form)
            if resp.status_code == 401:
                self._login()
                resp = self._client.post(path, data=params or {}, headers=form)
            if resp.status_code == 400 and "Wrong club" in resp.text:
                raise WrongClubError("This studio does not offer in-app class booking.")
            resp.raise_for_status()
            return resp.json() if resp.content else {}


# One shared session for the server process.
_session = NetpulseSession()

# Which clubs expose structured classes (Netpulse NATIVE). Persists per process.
# True = has classes, False = "Wrong club"/error. Lets the aggregator skip dead clubs.
_native_status: dict[str, bool] = {}
_classes_cache: dict[tuple, tuple[float, list]] = {}
_CLASSES_TTL = 120.0


def native_status(club_uuid: str) -> bool | None:
    """Known native status for a club, or None if not yet probed."""
    return _native_status.get(club_uuid)


def fetch_classes(
    club_uuid: str, start_ms: int, end_ms: int, class_type: str | None = None
) -> list[dict]:
    """Return the class list for a club over a time window (cached).

    Raises WrongClubError for a non-native club and records that status.
    """
    key = (club_uuid, start_ms, end_ms, class_type)
    hit = _classes_cache.get(key)
    if hit is not None and (time.time() - hit[0]) <= _CLASSES_TTL:
        return hit[1]
    params: dict[str, Any] = {
        "startDateTime": start_ms,
        "endDateTime": end_ms,
        "exerciserUuid": _session.uuid,
    }
    if class_type:
        params["type"] = class_type
    try:
        data = _session.get_json(f"/np/company/{club_uuid}/classes", params)
    except WrongClubError:
        _native_status[club_uuid] = False
        raise
    out = data if isinstance(data, list) else []
    _native_status[club_uuid] = True
    _classes_cache[key] = (time.time(), out)
    return out


def book_class(club_uuid: str, class_id: str, spot: str | None = None) -> dict:
    """Book the user into a class. WRITE action. Returns the updated class."""
    params = {"exerciserUuid": _session.uuid}
    if spot:
        params["spot"] = spot
    return _session.post_json(f"/np/company/{club_uuid}/class/{class_id}/addExerciser", params)


def cancel_class(club_uuid: str, class_id: str) -> dict:
    """Cancel the user's booking for a class. WRITE action."""
    params = {"exerciserUuid": _session.uuid}
    return _session.post_json(f"/np/company/{club_uuid}/class/{class_id}/removeExerciser", params)


def home_club_uuid() -> str | None:
    """The user's home club uuid (the virtual club that holds online classes)."""
    return _session.home_club_uuid
