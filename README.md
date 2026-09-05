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

> The calculation backend (Swiss Ephemeris) is wired in at integration. Until
> then `panchangam-mcp` exits with "integration pending"; construct the server
> in-process with a provider to run it — see `tests/fakes.py` and
> `tests/test_server.py`.

## Test

```
pytest tests/test_server.py -q
```
