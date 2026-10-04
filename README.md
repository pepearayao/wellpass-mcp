# wellpass-mcp

An MCP server to search the **EGYM Wellpass** fitness network — studios and
classes — from any MCP client (Claude Desktop, Claude Code, etc.).

> **Unofficial.** This project is not affiliated with, endorsed by, or
> supported by EGYM or Wellpass. It talks to Wellpass's own app/web APIs on
> your behalf, using your own account. Use it for personal use and at your own
> risk; respect Wellpass's Terms of Service. No warranty (see `LICENSE`).

## Features

Studios (no login required):

- **`search_studios`** — studios near a location, filtered by activities,
  services, Plus1, studio type, amenities, open-now, radius. City name or
  lat/lon.
- **`get_studio_details`** — full details for one studio.
- **`list_studio_filters`** — every valid filter value.

Classes (require login — an active Wellpass membership):

- **`search_classes`** — classes for one studio or the online catalogue.
- **`search_classes_near`** — classes across studios near a location, with
  filters (date, category, teacher, availability, online). Optionally also list
  nearby studios that offer classes without an in-app schedule.
- **`book_class`** / **`cancel_booking`** — two-step (preview, then
  `confirm=true`) booking. These WRITE to your account.

## Requirements

- Python 3.11+
- Optional: [uv](https://docs.astral.sh/uv/) (faster installs)

## Install

```bash
git clone <your-fork-url> wellpass-mcp
cd wellpass-mcp
./scripts/setup.sh
```

The script creates a virtualenv in `.venv`, installs the package, and creates
`.env` from `.env.example`.

Manual alternative:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
```

## Configure

Studio search needs no login. For class search/booking, edit `.env`:

```
WELLPASS_EMAIL=you@example.com
WELLPASS_PASSWORD=your-password
```

`.env` is git-ignored. Credentials are read only from the environment and are
never written to any other file.

## Register with an MCP client

The server speaks MCP over stdio. Point your client at the venv's Python.

**Claude Code:**

```bash
claude mcp add wellpass -- /absolute/path/to/wellpass-mcp/.venv/bin/python -m wellpass_mcp.server
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "wellpass": {
      "command": "/absolute/path/to/wellpass-mcp/.venv/bin/python",
      "args": ["-m", "wellpass_mcp.server"]
    }
  }
}
```

Then ask your assistant things like:

- "Find yoga studios within 3 km of Munich with a sauna."
- "What classes are near me tomorrow morning with free spots?"
- "Show Fitness First Marienplatz classes on Saturday."

## Limitations

- **Classes exist only for some studios.** The class API covers studios whose
  booking is native to the platform (e.g. large chains) plus the online class
  catalogue. Most small studios use external booking the app only links to;
  `search_classes_near` can list them separately but has no times for them.
- **Booking depends on the studio and an active membership.** Many classes are
  check-in based (no reservation). Booking is built but may return an external
  error for non-reservable classes.
- The APIs are reverse-engineered and may change without notice.

## Development

```bash
.venv/bin/python -m pytest -q        # offline tests (from fixtures)
.venv/bin/python -m wellpass_mcp.server   # run the server
```

See `AGENTS.md` for architecture and conventions, and `docs/api-contract.md`
for the reverse-engineered API details.

## License

MIT — see `LICENSE`.
