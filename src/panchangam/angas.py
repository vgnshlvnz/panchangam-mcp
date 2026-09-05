"""The five angas: tithi, nakshatra, yoga, karana, vara.

Every quantity here is a function of two ecliptic longitudes -- the Sun's and
the Moon's -- sampled through :mod:`panchangam.ephemeris`. Nothing in this
module imports ``swisseph`` or knows how a longitude is obtained.

Reckoning window
----------------
An anga is a division of a continuously advancing angle, so on any given day it
may change one or more times. Each function returns the list of
:class:`~panchangam.types.AngaSpan` that are active at some point between
*sunrise on the requested date* and *the following sunrise* -- the traditional
Hindu day boundary, not civil midnight. A span's ``start``/``end`` are the true
astronomical instants the anga begins and ends, so the first span usually starts
before the window opens and the last usually ends after it closes.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

from panchangam import ephemeris
from panchangam.types import AngaSpan, Place

# --- boundary constants --------------------------------------------------

#: A tithi is 1/30 of the synodic month: the Moon gains 360 deg on the Sun in
#: elongation over one lunation, divided into 30 equal steps.
TITHI_COUNT = 30
DEGREES_PER_TITHI = 360.0 / TITHI_COUNT  # 12.0

#: The widest arc the Moon-Sun elongation can sweep in 30 hours is about 18 deg
#: (Moon near perigee ~15.4 deg/day, Sun near aphelion ~0.95 deg/day). The
#: narrowest is about 13.4 deg (Moon near apogee). 30 h therefore always
#: contains exactly one 12 deg tithi boundary and never two -- the bracket used
#: for every forward/backward boundary search below.
_MAX_TITHI_HOURS = 30

_SHUKLA = "Shukla"
_KRISHNA = "Krishna"
# Positions 1..14 within a paksha; position 15 is Purnima (bright) or Amavasya
# (dark), named without the paksha prefix -- the convention drikpanchang uses.
_TITHI_STEMS = (
    "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami",
    "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami",
    "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi",
)


def _tithi_name(number: int) -> str:
    """Name for a 1-based tithi number in ``1..30``."""
    if number == 15:
        return "Purnima"
    if number == 30:
        return "Amavasya"
    paksha = _SHUKLA if number <= 15 else _KRISHNA
    position = (number - 1) % 15  # 0..13
    return f"{paksha} {_TITHI_STEMS[position]}"


def _elongation(when):
    """Moon-minus-Sun sidereal ecliptic longitude, degrees in ``[0, 360)``.

    Prograde and (over the hours a boundary search spans) monotonically
    increasing, which is what :func:`ephemeris.find_crossing` requires.
    """
    return (ephemeris.moon_longitude(when) - ephemeris.sun_longitude(when)) % 360.0


def tithi(on: date_cls, place: Place) -> list[AngaSpan]:
    """Tithi spans active from sunrise on ``on`` to the following sunrise.

    Each span's ``index`` is the tithi number ``1..30`` (1 = Shukla Pratipada,
    15 = Purnima, 16 = Krishna Pratipada, 30 = Amavasya). ``start`` and ``end``
    are the true instants the elongation crosses a multiple of 12 deg, in
    ``place``'s timezone.
    """
    return _angam_spans(
        _elongation, DEGREES_PER_TITHI, TITHI_COUNT, _tithi_name, on, place
    )


def _angam_spans(angle_fn, step_deg, count, name_fn, on, place):
    """Walk an angle divided into ``count`` equal ``step_deg`` steps across the
    sunrise-to-sunrise window.

    ``angle_fn`` maps a tz-aware datetime to a monotonically increasing angle in
    ``[0, 360)``. ``name_fn`` maps a 1-based division number to its name.
    """
    window_start = ephemeris.sunrise(on, place)
    window_end = ephemeris.sunrise(on + timedelta(days=1), place)
    search_span = timedelta(hours=_MAX_TITHI_HOURS)

    angle_at_start = angle_fn(window_start)
    step_index = int(angle_at_start // step_deg)  # 0-based

    # True start of the division in progress at sunrise: the previous boundary,
    # somewhere in the 30 h before the window opens.
    current_start = ephemeris.find_crossing(
        angle_fn,
        (step_index * step_deg) % 360.0,
        window_start - search_span,
        window_start,
    )

    spans: list[AngaSpan] = []
    while True:
        next_boundary = ephemeris.find_crossing(
            angle_fn,
            ((step_index + 1) * step_deg) % 360.0,
            current_start + timedelta(seconds=1),
            current_start + search_span,
        )
        number = step_index % count + 1  # 1-based
        spans.append(
            AngaSpan(
                index=number,
                name=name_fn(number),
                start=current_start,
                end=next_boundary,
            )
        )
        if next_boundary >= window_end:
            return spans
        step_index += 1
        current_start = next_boundary
