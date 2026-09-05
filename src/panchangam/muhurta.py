"""Standard day divisions: rahu kalam, yamagandam, gulika, abhijit, choghadiya.

Every function here is a function of the sunrise/sunset pair alone -- no solar or
lunar longitude enters. The three inauspicious eighths and the choghadiya
sequence are keyed to the vara (weekday), taken from the civil date the same way
:func:`panchangam.angas.vara` takes it: the day that begins at a given sunrise
carries that calendar date's weekday.

All periods are returned as :class:`~panchangam.types.AngaSpan` -- ``index`` is
the part number, ``name`` the period. Choghadiya qualities (good / neutral /
bad) are not on the span; look the name up in :data:`CHOGHADIYA_QUALITY`.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

from panchangam import ephemeris
from panchangam.types import AngaSpan, Place

# --- the inauspicious eighths ------------------------------------------
#
# Sunrise-to-sunset is split into 8 equal parts. For each weekday one part is
# rahu kalam, one yamagandam, one gulika. Tables indexed Sunday-first (so
# ``TABLE[date.isoweekday() % 7]`` -- isoweekday is Mon=1..Sun=7, and % 7 sends
# Sunday to 0). These are the values drikpanchang.com and most South Indian
# panchangams use; a second rahu-kalam ordering exists but was not chosen.

RAHU_KALAM_PART = (8, 2, 7, 5, 6, 4, 3)   # Sun, Mon, Tue, Wed, Thu, Fri, Sat
YAMAGANDAM_PART = (5, 4, 3, 2, 1, 7, 6)
GULIKA_PART = (7, 6, 5, 4, 3, 2, 1)

DAYLIGHT_PARTS = 8

#: Daylight muhurta count. Abhijit is the 8th of these 15, centred on solar
#: noon. (Some traditions hold there is no abhijit on Wednesday; this module
#: computes it every day regardless.)
DAYLIGHT_MUHURTAS = 15
ABHIJIT_MUHURTA = 8


def _daylight_span(on: date_cls, place: Place):
    sunrise = ephemeris.sunrise(on, place)
    sunset = ephemeris.sunset(on, place)
    return sunrise, sunset


def _partition(start, end, n: int) -> list:
    """``n + 1`` boundary instants dividing ``[start, end]`` into ``n`` equal
    parts. The endpoints are exact -- ``result[0] is start``, ``result[n]`` is
    ``end`` -- so consecutive parts touch and the last one closes on ``end``
    without floating-point drift.
    """
    width = (end - start) / n
    return [start + i * width for i in range(n)] + [end]


def _weekday_part(on: date_cls, table: tuple[int, ...]) -> int:
    return table[on.isoweekday() % 7]


def _eighth(on, place, table, name) -> AngaSpan:
    sunrise, sunset = _daylight_span(on, place)
    bounds = _partition(sunrise, sunset, DAYLIGHT_PARTS)
    part = _weekday_part(on, table)
    return AngaSpan(index=part, name=name, start=bounds[part - 1], end=bounds[part])


def rahu_kalam(on: date_cls, place: Place) -> AngaSpan:
    """Rahu kalam: the inauspicious eighth of the daylight span for this weekday."""
    return _eighth(on, place, RAHU_KALAM_PART, "Rahu Kalam")


def yamagandam(on: date_cls, place: Place) -> AngaSpan:
    """Yamagandam: another inauspicious eighth of the daylight span, by weekday."""
    return _eighth(on, place, YAMAGANDAM_PART, "Yamagandam")


def gulika(on: date_cls, place: Place) -> AngaSpan:
    """Gulika (Gulika Kalam): the eighth ruled by Saturn's son, by weekday."""
    return _eighth(on, place, GULIKA_PART, "Gulika")


def abhijit(on: date_cls, place: Place) -> AngaSpan:
    """Abhijit muhurta: the 8th of the 15 daylight muhurtas, straddling noon.

    An auspicious ~48-minute window centred on the midpoint of the daylight
    span. ``index`` is 8 (its muhurta number).
    """
    sunrise, sunset = _daylight_span(on, place)
    bounds = _partition(sunrise, sunset, DAYLIGHT_MUHURTAS)
    return AngaSpan(
        index=ABHIJIT_MUHURTA,
        name="Abhijit",
        start=bounds[ABHIJIT_MUHURTA - 1],
        end=bounds[ABHIJIT_MUHURTA],
    )


# --- choghadiya -------------------------------------------------------
#
# Eight parts of the daylight span, then eight of the night (sunset to next
# sunrise). Seven names cycle in planetary-lord order; the day sequence begins
# at the weekday lord's choghadiya, stepping +3 (mod 7) per weekday from
# Sunday's Udveg. The night sequence begins five positions further on -- i.e.
# where the day sequence four weekdays later begins.

_CHOGHADIYA_CYCLE = (
    "Udveg", "Char", "Labh", "Amrit", "Kaal", "Shubh", "Rog",
)

CHOGHADIYA_QUALITY = {
    "Amrit": "good",
    "Shubh": "good",
    "Labh": "good",
    "Char": "neutral",
    "Udveg": "bad",
    "Kaal": "bad",
    "Rog": "bad",
}

CHOGHADIYA_PARTS = 8


def _choghadiya_day_start(on: date_cls) -> int:
    return (3 * (on.isoweekday() % 7)) % 7


def choghadiya(on: date_cls, place: Place) -> list[AngaSpan]:
    """The 16 choghadiya of the day: 8 across the daylight span (``index``
    1..8), then 8 across the night to the next sunrise (``index`` 9..16).

    Spans are contiguous. The name repeats -- each block of 8 cycles through
    the 7 names once and a bit. Use :data:`CHOGHADIYA_QUALITY` for the
    good/neutral/bad tag.
    """
    sunrise, sunset = _daylight_span(on, place)
    next_sunrise = ephemeris.sunrise(on + timedelta(days=1), place)

    day_start = _choghadiya_day_start(on)
    night_start = (day_start + 5) % 7

    spans: list[AngaSpan] = []
    for offset, block_start, bounds in (
        (0, day_start, _partition(sunrise, sunset, CHOGHADIYA_PARTS)),
        (CHOGHADIYA_PARTS, night_start, _partition(sunset, next_sunrise, CHOGHADIYA_PARTS)),
    ):
        for i in range(CHOGHADIYA_PARTS):
            spans.append(
                AngaSpan(
                    index=offset + i + 1,
                    name=_CHOGHADIYA_CYCLE[(block_start + i) % 7],
                    start=bounds[i],
                    end=bounds[i + 1],
                )
            )
    return spans
