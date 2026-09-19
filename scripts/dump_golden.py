"""Dump N days of panchangam output to JSON: golden data for the C port.

Uses only the public panchangam API, so the C code can be checked against
exactly what the Python service returns. Every instant is written twice: the
local ISO string, and a Julian Day (UT) float so the C side can compare
numbers without parsing dates.

    .venv/bin/python scripts/dump_golden.py --start 2026-09-01 --days 30 \
        --out tests/fixtures/golden_petaling_jaya.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta

from panchangam import angas, ephemeris, hora_spans, lagna, muhurta
from panchangam.types import Place

PLACE = Place("Petaling Jaya", 3.1073, 101.6067, "Asia/Kuala_Lumpur")

_UNIX_EPOCH_JD = 2440587.5


def jd_ut(when: datetime) -> float:
    return _UNIX_EPOCH_JD + when.timestamp() / 86400.0


def instant(when: datetime) -> dict:
    return {"iso": when.isoformat(), "jd_ut": jd_ut(when)}


def span(s) -> dict:
    return {
        "index": s.index,
        "name": s.name,
        "start": instant(s.start),
        "end": instant(s.end),
    }


def period(p) -> dict:
    return {
        "name": p.name,
        "auspicious": p.auspicious,
        "start": instant(p.start),
        "end": instant(p.end),
    }


def longitudes(when: datetime) -> dict:
    """Raw sidereal longitudes and speeds: the layer the C ephemeris replaces."""
    out = {"ayanamsa_deg": ephemeris.ayanamsa_degrees(when)}
    for g in ephemeris.Graha:
        out[g.name.lower()] = {
            "lon_deg": ephemeris.graha_longitude(g, when),
            "speed_deg_per_day": ephemeris.graha_speed(g, when),
        }
    return out


def day_record(on: date) -> dict:
    sunrise = ephemeris.sunrise(on, PLACE)
    sunset = ephemeris.sunset(on, PLACE)
    return {
        "date": on.isoformat(),
        "sunrise": instant(sunrise),
        "sunset": instant(sunset),
        "next_sunrise": instant(ephemeris.sunrise(on + timedelta(days=1), PLACE)),
        "longitudes_at_sunrise": longitudes(sunrise),
        "ascendant_at_sunrise_deg": ephemeris.ascendant(sunrise, PLACE),
        "vara": span(angas.vara(on, PLACE)),
        "tithi": [span(s) for s in angas.tithi(on, PLACE)],
        "nakshatra": [span(s) for s in angas.nakshatra(on, PLACE)],
        "yoga": [span(s) for s in angas.yoga(on, PLACE)],
        "karana": [span(s) for s in angas.karana(on, PLACE)],
        "rahu_kalam": period(muhurta.rahu_kalam(on, PLACE)),
        "yamaganda": period(muhurta.yamaganda(on, PLACE)),
        "gulika": period(muhurta.gulika(on, PLACE)),
        "abhijit": period(muhurta.abhijit(on, PLACE)),
        "durmuhurtam": [period(p) for p in muhurta.durmuhurtam(on, PLACE)],
        "choghadiya": [span(s) for s in muhurta.choghadiya(on, PLACE)],
        "hora": [span(s) for s in hora_spans.horas(on, PLACE)],
        "lagna": [span(s) for s in lagna.lagna(on, PLACE)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 1))
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--out", default="golden_petaling_jaya.json")
    args = parser.parse_args()

    ephemeris.configure(ephemeris.Ayanamsa.LAHIRI)
    doc = {
        "place": {
            "name": PLACE.name,
            "latitude": PLACE.latitude,
            "longitude": PLACE.longitude,
            "timezone": PLACE.timezone,
            "elevation_m": PLACE.elevation_m,
        },
        "ayanamsa": "lahiri",
        "ephemeris": "moshier",
        "days": [day_record(args.start + timedelta(days=i)) for i in range(args.days)],
    }
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=1)
    print(f"wrote {len(doc['days'])} days to {args.out}")


if __name__ == "__main__":
    main()
