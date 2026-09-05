# panchangam-mcp

An MCP server that exposes Hindu almanac (*panchangam*) calculations as tools:

- **`get_panchangam`** — the five limbs of a civil day at a place (tithi,
  nakshatra, yoga, karana, vaara) plus sunrise/sunset.
- **`get_muhurta`** — the named auspicious/inauspicious periods within a day
  (Abhijit Muhurat, Rahu Kalam, Yamaganda, Gulika Kalam, Durmuhurtam).

All timestamps crossing the tool boundary are timezone-aware ISO-8601 strings in
the location's zone.

## Install

```
pip install -e ".[dev]"
```

## Run

```
panchangam-mcp --transport http --host 127.0.0.1 --port 8765   # Streamable HTTP at /mcp
panchangam-mcp --transport stdio                                # default; client spawns the process
```

The backend is Swiss Ephemeris (Moshier) via `load_provider()` — the one place
the calculation backend is chosen.

## Test

`pyswisseph` has no wheel for Python 3.13+; use the uv-managed 3.12 venv:

```
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
.venv/bin/pytest -q
```

The server lane alone (no Swiss Ephemeris needed — those tests skip):

```
pytest tests/test_server.py -q
```
