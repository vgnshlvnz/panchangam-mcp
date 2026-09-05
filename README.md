# panchangam-mcp

An [MCP](https://modelcontextprotocol.io) server that computes the Hindu almanac
(*panchangam*) for a date and place and exposes it as two tools. Positions of the
Sun and Moon come from the Swiss Ephemeris (Moshier model, sidereal / Lahiri
ayanamsa — the same convention drikpanchang.com uses).

| Tool | Answers |
|------|---------|
| `get_panchangam` | The five limbs of a civil day — tithi, nakshatra, yoga, karana, vaara — plus sunrise and sunset. Use it for the lunar day, the Moon's phase, the nakshatra a date falls in, Ekadashi / Amavasya / Purnima and other Moon-based observances, or just local sunrise/sunset. |
| `get_muhurta` | The named auspicious and inauspicious periods *within* a day — Abhijit Muhurta, Rahu Kalam, Yamaganda, Gulika Kalam, Durmuhurtam — each with a start, an end, and whether to seek it or avoid it. Use it to pick or avoid a time of day. |

Every timestamp that crosses the tool boundary is a timezone-aware, second-precision
ISO-8601 string in the location's own zone (`2026-09-06T07:06:49+08:00`).

---

## Requirements

- **Python 3.12.** The `pyswisseph` dependency has no prebuilt wheel for 3.13+.
  [`uv`](https://docs.astral.sh/uv/) is the easiest way to get a 3.12
  interpreter without touching the system Python.

## Install

```bash
uv venv --python 3.12 .venv
uv pip install -e .
```

or with plain pip in a 3.12 environment:

```bash
pip install -e .
```

This installs the `panchangam-mcp` console script.

## Run

The server speaks MCP over either transport:

```bash
# stdio — the client launches this process and talks to it over stdin/stdout
panchangam-mcp                       # --transport stdio is the default

# Streamable HTTP — long-running server, MCP endpoint at http://<host>:<port>/mcp
panchangam-mcp --transport http --host 127.0.0.1 --port 8765
```

`--host` and `--port` apply to `http` only and default to `127.0.0.1:8765`.

---

## Connect an MCP client

### Claude Code

```bash
# stdio
claude mcp add panchangam -- panchangam-mcp

# or, against a running HTTP server
claude mcp add --transport http panchangam http://127.0.0.1:8765/mcp
```

### Any client that reads an MCP server config

stdio:

```json
{
  "mcpServers": {
    "panchangam": {
      "command": "panchangam-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

HTTP (server started separately):

```json
{
  "mcpServers": {
    "panchangam": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

If `panchangam-mcp` is not on the client's `PATH`, use the absolute path to the
script inside your virtualenv (`/path/to/.venv/bin/panchangam-mcp`).

---

## Tools

Both tools take the same four arguments:

| Argument | Type | Notes |
|----------|------|-------|
| `date` | string | Civil date, ISO-8601 `YYYY-MM-DD`, zero-padded (`2026-09-06`). Time of day is not used. |
| `lat` | number | Latitude in degrees, north positive, −90 to 90. |
| `lon` | number | Longitude in degrees, east positive, −180 to 180. |
| `tz` | string | IANA timezone name (`Asia/Kolkata`, `America/New_York`). A bare UTC offset like `+05:30` is rejected — the named zone is needed to line civil days up with local sunrise and to handle DST. |

The traditional day runs from one sunrise to the next, so a span can start before
the requested date and end after it. When a boundary falls during the day, both
segments are listed in chronological order (`ends` of one equals `starts` of the
next).

### `get_panchangam`

Request:

```json
{ "date": "2026-09-06", "lat": 3.14111, "lon": 101.68639, "tz": "Asia/Kuala_Lumpur" }
```

Response:

```json
{
  "location": {
    "name": "query location",
    "latitude": 3.14111,
    "longitude": 101.68639,
    "timezone": "Asia/Kuala_Lumpur"
  },
  "date": "2026-09-06",
  "weekday": "Ravivara",
  "sunrise": "2026-09-06T07:06:49+08:00",
  "sunset": "2026-09-06T19:16:32+08:00",
  "tithi": [
    { "name": "Krishna Dashami",  "number": 25, "starts": "2026-09-06T00:24:11+08:00", "ends": "2026-09-06T21:59:43+08:00" },
    { "name": "Krishna Ekadashi", "number": 26, "starts": "2026-09-06T21:59:43+08:00", "ends": "2026-09-07T19:34:38+08:00" }
  ],
  "nakshatra": [
    { "name": "Ardra",     "number": 6, "starts": "2026-09-06T00:01:01+08:00", "ends": "2026-09-06T22:22:56+08:00" },
    { "name": "Punarvasu", "number": 7, "starts": "2026-09-06T22:22:56+08:00", "ends": "2026-09-07T20:44:16+08:00" }
  ],
  "yoga": [
    { "name": "Siddhi",    "number": 16, "starts": "2026-09-05T15:17:08+08:00", "ends": "2026-09-06T12:15:11+08:00" },
    { "name": "Vyatipata", "number": 17, "starts": "2026-09-06T12:15:11+08:00", "ends": "2026-09-07T09:11:08+08:00" }
  ],
  "karana": [
    { "name": "Vanija", "number": 49, "starts": "2026-09-06T00:24:11+08:00", "ends": "2026-09-06T11:12:17+08:00" },
    { "name": "Vishti", "number": 50, "starts": "2026-09-06T11:12:17+08:00", "ends": "2026-09-06T21:59:43+08:00" },
    { "name": "Bava",   "number": 51, "starts": "2026-09-06T21:59:43+08:00", "ends": "2026-09-07T08:46:59+08:00" }
  ]
}
```

`number` is the 1-based index within each cycle: tithi 1–30, nakshatra 1–27,
yoga 1–27, karana 1–60. `weekday` is the vaara, fixed for the whole
sunrise-to-sunrise day.

### `get_muhurta`

Same request shape. Response:

```json
{
  "location": { "name": "query location", "latitude": 3.14111, "longitude": 101.68639, "timezone": "Asia/Kuala_Lumpur" },
  "date": "2026-09-06",
  "periods": [
    { "name": "Abhijit Muhurta", "auspicious": true,  "starts": "2026-09-06T12:47:21+08:00", "ends": "2026-09-06T13:36:00+08:00" },
    { "name": "Rahu Kalam",      "auspicious": false, "starts": "2026-09-06T17:45:19+08:00", "ends": "2026-09-06T19:16:32+08:00" },
    { "name": "Yamaganda",       "auspicious": false, "starts": "2026-09-06T13:11:41+08:00", "ends": "2026-09-06T14:42:54+08:00" },
    { "name": "Gulika Kalam",    "auspicious": false, "starts": "2026-09-06T16:14:07+08:00", "ends": "2026-09-06T17:45:19+08:00" },
    { "name": "Durmuhurtam",     "auspicious": false, "starts": "2026-09-06T17:39:15+08:00", "ends": "2026-09-06T18:27:53+08:00" }
  ]
}
```

Every period is a fixed division of the daylight span, so the times depend on the
place's sunrise and sunset.

### Errors

A bad request comes back as a tool error (`isError: true`) with a message the
caller can act on, not a stack trace:

```
invalid arguments: date must be an ISO-8601 calendar date with zero-padded fields, like '2026-09-06'; got '6 Sept 2026'
invalid arguments: tz must be an IANA timezone name like 'Asia/Kuala_Lumpur' (not a UTC offset); '+08:00' is not a known zone
invalid arguments: lat must be between -90 and 90 degrees, got 999.0
cannot compute: Sun has no rise at query location on 2026-12-21
```

`cannot compute:` means the request was well-formed but has no answer — for
example a polar location where the Sun does not rise or set on that date.

---

## Development

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
.venv/bin/pytest -q
```

The tool-surface tests don't need Swiss Ephemeris (the backend-backed ones skip
if it's absent), so a quick check without a 3.12 build works too:

```bash
pytest tests/test_server.py -q
```

`load_provider()` in `src/panchangam/server.py` is the single place the
calculation backend is chosen; everything downstream takes the provider as an
argument.
