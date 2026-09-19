"""Planetary horas of a day.

The day is split into 24 horas of a fixed 60 minutes starting at sunrise. Hora 1
belongs to the weekday lord and the lords then follow the order Sun, Venus,
Mercury, Moon, Saturn, Jupiter, Mars, repeating. Pure given sunrise: the only
ephemeris call is :func:`panchangam.ephemeris.sunrise`.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

from panchangam import ephemeris
from panchangam.types import AngaSpan, Place

HORAS_PER_DAY = 24

_HORA_ORDER = ("Sun", "Venus", "Mercury", "Moon", "Saturn", "Jupiter", "Mars")

# Weekday lords, Sunday-first (``isoweekday() % 7``: Sunday -> 0).
_WEEKDAY_LORD = (
    "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn",
)


def horas(on: date_cls, place: Place) -> list[AngaSpan]:
    """The 24 horas beginning at sunrise on ``on``.

    ``index`` is 1..24 and ``name`` is the lord. Every hora is exactly 60
    minutes, so hora 24 ends 24 h after sunrise, which differs from the next
    sunrise by a few seconds to a minute or so.
    """
    sunrise = ephemeris.sunrise(on, place)
    first = _HORA_ORDER.index(_WEEKDAY_LORD[on.isoweekday() % 7])
    return [
        AngaSpan(
            index=i + 1,
            name=_HORA_ORDER[(first + i) % 7],
            start=sunrise + timedelta(hours=i),
            end=sunrise + timedelta(hours=i + 1),
        )
        for i in range(HORAS_PER_DAY)
    ]
