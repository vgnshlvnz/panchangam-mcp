# panchangam-mcp

Python package that computes Tamil/Vedic panchangam data with pyswisseph and exposes it as
MCP tools. Runs as a listening service on the Fedora host `fedoraclaw`; OpenClaw uses it to
post to WhatsApp. Long-term: port the calculation core to C for an ESP32-S3.

---

## How to work (Karpathy-style rules, adapted to this repo)

### 1. Think before coding
- State your assumptions before editing. If a request has two readings, list both and ask.
- Astrology rules are the main source of silent wrong assumptions. If a rule is not in
  "Domain rules" below (which tara counts as good, which houses count for gochara, sunrise
  definition, ayanamsa), ask — do not pick one from general knowledge.
- Never invent reference values (nakshatra end times, sunrise, hora lords). If a test needs
  one, leave `TODO: verify against printed panchangam` and tell me.
- If something in the code contradicts this file, stop and point it out.

### 2. Simplicity first
- Write the smallest code that solves the stated task. No speculative options, plugin
  systems, base classes or config knobs nobody asked for.
- Prefer a plain function and a dict over a new class hierarchy.
- Calculation code must stay pure (no I/O, no config reads, no network) and use simple
  loops and integer maths — it will be ported to C with fixed arrays and no malloc.
- New dependencies need my OK.

### 3. Surgical changes
- Touch only lines that trace back to the request. Don't reformat, rename or "tidy"
  neighbouring code.
- Match the existing style in the file you edit.
- Clean up dead code you created in this task; if you notice pre-existing dead code or
  bugs, list them at the end — don't fix them unasked.
- Don't change Tamil spellings, public tool names, or tool output keys unless asked
  (OpenClaw and the WhatsApp posts depend on them).

### 4. Goal-driven execution
- Before starting, restate the task as checkable success criteria, e.g.
  "pytest -q passes; `panchangam-personal --dry-run --date 2026-09-24` shows Thursday
  hora 1 = Jupiter; server lists the new tool".
- For bugs: write a failing test first, then fix until it passes.
- Loop: change → run tests/ruff → check output → repeat. Report what you ran and the result.
- Done means verified, not "should work".

---

## Layout
- `panchangam_mcp/` : server + calculations (five angas, muhurta, lagna tables)
- `panchangam_mcp/personal/` : personal daily cards (tarabala, chandrabala, lagna windows),
  CLI `panchangam-personal`, delivery via Slack webhook / OpenClaw WhatsApp
- `panchangam_mcp/hora/` : rasi-wise hora favourability, tools `rasi_hora_table`, `current_hora`
- Config: `~/.config/panchangam/profiles.yaml`; secrets: `~/.config/panchangam/secrets.env`

## Commands
- venv: `~/.venvs/panchangam` — always use its `python`, `pip`, `pytest`, `ruff`
- install: `~/.venvs/panchangam/bin/pip install -e .`
- tests: `~/.venvs/panchangam/bin/pytest -q`
- lint: `~/.venvs/panchangam/bin/ruff check .`
- preview messages: `panchangam-personal --dry-run [--date YYYY-MM-DD]`
- service: `systemctl --user status panchangam-mcp` (I restart it, not you)

## Domain rules
- Sidereal zodiac via `swe.set_sid_mode`; ayanamsa from profiles.yaml (lahiri / raman / kp)
- Place Petaling Jaya (3.1073, 101.6067), time Asia/Kuala_Lumpur (UTC+8)
- Day runs sunrise → next sunrise; sunrise = disc centre, standard refraction
- Horas: fixed 60 min from sunrise, hora 1 = weekday lord, order
  Sun→Venus→Mercury→Moon→Saturn→Jupiter→Mars
- Tara: count janma star → day star, mod 9. Good 2,4,6,8,9 · bad 3,5,7 · 1 mixed
- Chandrabala houses: good 1,3,6,7,10,11 · 2,5,9 good only when waxing · 4,12 weak · 8 = chandrashtama
- Indices are 1-based: nakshatra 1..27, rasi 1..12, hora 1..24
- MCP tools return JSON-serialisable dicts; times "HH:MM" local plus the date
- mcp SDK may be v1 (FastMCP) or v2 (MCPServer): only use the `@mcp.tool()` decorator

## Never
- Send real Slack / WhatsApp / X messages — use `--dry-run`
- Read or print `secrets.env`
- `git push`, restart services, or edit `~/.config` without asking
