"""Rasi-lagna windows: the sidereal zodiac sign rising over a day.

The lagna is the sidereal ascendant. It sweeps the whole zodiac in about a day,
so each rasi rises for roughly two hours. Windows are the stretches between
successive crossings of a multiple of 30 deg, located with
:func:`panchangam.ephemeris.find_crossing`.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

from panchangam import ephemeris
from panchangam.types import AngaSpan, Place

RASI_COUNT = 12
DEGREES_PER_RASI = 360.0 / RASI_COUNT

RASI_NAMES = (
    "Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
    "Tula", "Vrischika", "Dhanu", "Makara", "Kumbha", "Meena",
)

# The ascendant advances ~15 deg/h, so a bracket must stay well under the 180 deg
# find_crossing allows (12 h) and still exceed the longest rasi window (~3 h).
_BOUNDARY_SEARCH_HOURS = 6


def lagna(on: date_cls, place: Place) -> list[AngaSpan]:
    """Lagna windows active from sunrise on ``on`` to the following sunrise.

    ``index`` is the rasi 1..12 (1 = Mesha). The first window starts before
    sunrise and the last ends after the next sunrise, as for the angas.
    """
    window_start = ephemeris.sunrise(on, place)
    window_end = ephemeris.sunrise(on + timedelta(days=1), place)
    search_span = timedelta(hours=_BOUNDARY_SEARCH_HOURS)

    def ascendant(when):
        return ephemeris.ascendant(when, place)

    step_index = int(ascendant(window_start) // DEGREES_PER_RASI)  # 0-based
    current_start = ephemeris.find_crossing(
        ascendant,
        (step_index * DEGREES_PER_RASI) % 360.0,
        window_start - search_span,
        window_start,
    )

    spans: list[AngaSpan] = []
    while True:
        next_boundary = ephemeris.find_crossing(
            ascendant,
            ((step_index + 1) * DEGREES_PER_RASI) % 360.0,
            current_start + timedelta(seconds=1),
            current_start + search_span,
        )
        number = step_index % RASI_COUNT + 1
        spans.append(
            AngaSpan(
                index=number,
                name=RASI_NAMES[number - 1],
                start=current_start,
                end=next_boundary,
            )
        )
        if next_boundary >= window_end:
            return spans
        step_index += 1
        current_start = next_boundary
