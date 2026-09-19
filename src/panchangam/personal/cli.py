"""
panchangam-personal — build and send today's personal muhurta cards.

  panchangam-personal                       # today, all profiles, send
  panchangam-personal --dry-run             # print, don't send
  panchangam-personal --date 2026-09-21 --only amma --dry-run
  panchangam-personal janma "1992-03-11 06:14" --tz 8   # compute janma nakshatra/rasi
"""
import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from panchangam.types import Place

from .deliver import send
from .format import render
from .muhurta import NAKSHATRAS, RASIS, Person, compute_day, janma_from_birth

DEFAULT_CFG = Path.home() / ".config/panchangam/profiles.yaml"


def load(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def place_from(cfg: dict) -> Place:
    p = cfg["place"]
    return Place(p["name"], p["lat"], p["lon"], p["timezone"])


def run(cfg: dict, day: date, only: str | None, dry: bool) -> int:
    place = place_from(cfg)
    s = cfg.get("settings", {})
    failures = 0
    for key, prof in cfg["profiles"].items():
        if only and key != only:
            continue
        if not (1 <= prof["janma_nakshatra"] <= 27 and 1 <= prof["janma_rasi"] <= 12):
            print(f"skip {key}: janma_nakshatra/janma_rasi not filled in", file=sys.stderr)
            failures += 1
            continue
        person = Person(prof["name"], prof["janma_nakshatra"], prof["janma_rasi"])
        result = compute_day(person, place, day, s.get("ayanamsa", "lahiri"),
                             s.get("sandhi_pct", 20), s.get("min_window_min", 20))
        text = render(result, prof.get("lang", "en"))
        if dry:
            print(f"----- {key} -> {prof['deliver']['type']}\n{text}\n")
            continue
        try:
            send(text, prof["deliver"])
            print(f"sent: {key}")
        except Exception as e:  # noqa: BLE001 -- keep going for the other person
            failures += 1
            print(f"FAILED {key}: {e}", file=sys.stderr)
    return 1 if failures else 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="panchangam-personal")
    sub = ap.add_subparsers(dest="cmd")
    j = sub.add_parser("janma", help="compute janma nakshatra/rasi from birth time")
    j.add_argument("when", help='"YYYY-MM-DD HH:MM" local time')
    j.add_argument("--tz", type=float, default=8.0)
    j.add_argument("--ayanamsa", default="lahiri")
    ap.add_argument("--config", type=Path, default=DEFAULT_CFG)
    ap.add_argument("--date", type=date.fromisoformat)
    ap.add_argument("--only")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.cmd == "janma":
        dt = datetime.strptime(a.when, "%Y-%m-%d %H:%M").replace(tzinfo=timezone(timedelta(hours=a.tz)))
        n, pada, r = janma_from_birth(dt, a.ayanamsa)
        print(f"janma_nakshatra: {n}   # {NAKSHATRAS[n-1]} pada {pada}")
        print(f"janma_rasi: {r}        # {RASIS[r-1]}")
        return

    cfg = load(a.config)
    day = a.date or datetime.now(ZoneInfo(cfg["place"]["timezone"])).date()
    sys.exit(run(cfg, day, a.only, a.dry_run))


if __name__ == "__main__":
    main()
