# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this is

`wellpass-mcp` is a read-first MCP (Model Context Protocol) server that searches
the EGYM Wellpass fitness network: studios and their classes. It is an
unofficial client built against Wellpass's own app/web APIs. It is not
affiliated with EGYM / Wellpass.

## Architecture

The package is `wellpass_mcp/`:

- `server.py` — the MCP server (stdio). Defines all tools. Start here.
- `gymfinder.py` — client for the public studio-finder API (no auth). Cached.
- `studios.py` — pure logic: filter-slug resolution, geo distance, decoding.
- `geocode.py` — city name -> lat/lon (OpenStreetMap Nominatim + a small table).
- `netpulse.py` — authenticated client for the class API (session login). Holds
  credentials handling, the session, and the class/book/cancel calls.
- `classes.py` — pure logic: class decode, filters, date-window parsing.

Two backends, two auth models (see `docs/api-contract.md`):

1. Studio finder — public, no auth. `gymfinder.int.api.egym.com`.
2. Class API — session login (form-urlencoded) on `qualitrain.netpulse.com`,
   built on the Netpulse platform. Needs `WELLPASS_EMAIL` / `WELLPASS_PASSWORD`.

The studio `gymUUID` is the class API's `clubUuid` — that is the join between
the two backends. Only "native" studios expose structured classes.

## Conventions

- Keep network I/O in `gymfinder.py` / `netpulse.py`; keep `studios.py` and
  `classes.py` pure and unit-tested.
- Tests run offline from redacted fixtures in `fixtures/`. Do not add tests that
  hit the live API in the default suite; mock `gymfinder` / `netpulse` instead.
- Cache aggressively and keep request rates low (this uses a real account).
- Times are stored by the API as true UTC epochs; render them in the studio's
  timezone.

## Safety

- NEVER commit secrets. `.env` is git-ignored. Credentials come from the
  environment only.
- NEVER commit real personal data. Fixtures must be synthetic or redacted.
- `book_class` / `cancel_booking` are WRITE actions on a real account. They are
  two-step (preview, then `confirm=true`). Do not change them to book on the
  first call. Do not run real bookings in tests.

## Dev workflow

```
./scripts/setup.sh            # venv + install + .env
.venv/bin/python -m pytest -q # tests (offline)
.venv/bin/python -m wellpass_mcp.server   # run the server (stdio)
```

## Reference

- `docs/api-contract.md` — the reverse-engineered API contract (endpoints,
  params, auth, field maps, and known limits).
- `README.md` — user-facing setup and MCP registration.
