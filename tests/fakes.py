"""A fixture-backed stand-in for the real panchangam provider.

DELETE AT INTEGRATION, along with the ``day_panchangam_*.json`` fixtures it
reads. It exists so ``tests/test_server.py`` can exercise the tool surface
without the ephemeris or angas lanes.

It implements :class:`panchangam.server.PanchangamProvider` -- the same call
signature the real backend will. Nothing in here is astronomy: it loads canned
:class:`~panchangam.types.DayPanchangam` values keyed by (date, location).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from panchangam.server import ProviderError
from panchangam.types import AngaSpan, DayPanchangam, NamedPeriod, Place

_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_COORD_DP = 4  # match fixtures to a query within ~10 m


def _angaspans(raw: list[dict]) -> tuple[AngaSpan, ...]:
    return tuple(
        AngaSpan(
            index=span["index"],
            name=span["name"],
            start=datetime.fromisoformat(span["start"]),
            end=datetime.fromisoformat(span["end"]),
        )
        for span in raw
    )


def _named_periods(raw: list[dict]) -> tuple[NamedPeriod, ...]:
    return tuple(
        NamedPeriod(
            name=period["name"],
            start=datetime.fromisoformat(period["start"]),
            end=datetime.fromisoformat(period["end"]),
            auspicious=period["auspicious"],
        )
        for period in raw
    )


def _key(day_iso: str, latitude: float, longitude: float) -> tuple:
    return (day_iso, round(latitude, _COORD_DP), round(longitude, _COORD_DP))


class MissingFixtureError(ProviderError, LookupError):
    """The fake has no canned panchangam for the requested date and place.

    A ``ProviderError`` so it maps the same way a real "no result" would.
    """


class FakePanchangamProvider:
    """Serves ``day_panchangam_*.json`` fixtures as ``DayPanchangam`` objects."""

    def __init__(self, fixture_dir: Path = _FIXTURE_DIR) -> None:
        self._fixtures: dict[tuple, dict] = {}
        for path in sorted(fixture_dir.glob("day_panchangam_*.json")):
            fx = json.loads(path.read_text())
            place = fx["place"]
            self._fixtures[_key(fx["date"], place["latitude"], place["longitude"])] = fx

    def _fixture_for(self, place: Place, day: date) -> dict:
        try:
            return self._fixtures[
                _key(day.isoformat(), place.latitude, place.longitude)
            ]
        except KeyError:
            raise MissingFixtureError(
                f"no fake panchangam for lat={place.latitude}, lon={place.longitude} "
                f"on {day.isoformat()}; add a fixture or query "
                f"2026-09-06 at Kuala Lumpur (3.14111, 101.68639)"
            ) from None

    def day_panchangam(self, place: Place, day: date) -> DayPanchangam:
        fx = self._fixture_for(place, day)
        return DayPanchangam(
            place=place,
            date=day,
            sunrise=datetime.fromisoformat(fx["sunrise"]),
            sunset=datetime.fromisoformat(fx["sunset"]),
            vaara=fx["vaara"],
            tithi=_angaspans(fx["tithi"]),
            nakshatra=_angaspans(fx["nakshatra"]),
            yoga=_angaspans(fx["yoga"]),
            karana=_angaspans(fx["karana"]),
        )

    def named_periods(self, place: Place, day: date) -> tuple[NamedPeriod, ...]:
        return _named_periods(self._fixture_for(place, day)["muhurta"])
