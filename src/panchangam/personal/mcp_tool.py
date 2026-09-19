"""The personal card as a server tool: config lookup and rendering.

The tool definition and argument handling live in ``panchangam.server``; this
module does the work, importing the swisseph-backed code only when called.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .cli import DEFAULT_CFG, load, place_from
from .format import render
from .muhurta import Person, compute_day


def personal_card(profile: str, day: date | None, lang: str | None = None) -> str:
    """The card text for a stored profile; ``day`` defaults to today at its place. Raises ``FileNotFoundError`` if the
    profiles file is missing and ``KeyError`` for an unknown profile."""
    cfg = load(DEFAULT_CFG)
    prof = cfg["profiles"][profile]
    s = cfg.get("settings", {})
    place = place_from(cfg)
    r = compute_day(
        Person(prof["name"], prof["janma_nakshatra"], prof["janma_rasi"]),
        place, day or datetime.now(ZoneInfo(place.timezone)).date(),
        s.get("ayanamsa", "lahiri"), s.get("sandhi_pct", 20), s.get("min_window_min", 20),
    )
    return render(r, lang or prof.get("lang", "en"))
