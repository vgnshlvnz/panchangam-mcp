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

#: Nakshatra and yoga both divide a circle into 27. 360 / 27 = 13 deg 20 min
#: = 800 arcminutes exactly -- the figure old almanacs quote. Nakshatra steps
#: the Moon's longitude; yoga steps the Sun-plus-Moon longitude sum.
NAKSHATRA_COUNT = 27
YOGA_COUNT = 27
DEGREES_PER_NAKSHATRA = 360.0 / NAKSHATRA_COUNT  # 13.333... == 800' / 60
DEGREES_PER_YOGA = 360.0 / YOGA_COUNT

#: Bracket half-width for every forward/backward boundary search below.
#: Each anga angle is prograde; over 30 hours the slowest sweeps are
#:   tithi  (Moon - Sun):  ~13.4 deg   (Moon near apogee)
#:   nakshatra (Moon):     ~14.7 deg   (Moon near apogee)
#:   yoga   (Moon + Sun):  ~15.9 deg   (Moon near apogee)
#: and the fastest about 1.4x those. Every one clears its own step (12 deg /
#: 13.33 deg) and stays under two steps, so a 30 h window straddling a known
#: boundary contains exactly the next boundary -- never zero, never two.
_BOUNDARY_SEARCH_HOURS = 30

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


# The 27 nakshatras in Moon-longitude order, Ashwini (0 deg) first.
_NAKSHATRA_NAMES = (
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni",
    "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha",
    "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana",
    "Dhanishta", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada",
    "Revati",
)

# The 27 yogas in Sun+Moon-sum order, Vishkambha first.
_YOGA_NAMES = (
    "Vishkambha", "Priti", "Ayushman", "Saubhagya", "Shobhana", "Atiganda",
    "Sukarma", "Dhriti", "Shula", "Ganda", "Vriddhi", "Dhruva", "Vyaghata",
    "Harshana", "Vajra", "Siddhi", "Vyatipata", "Variyana", "Parigha",
    "Shiva", "Siddha", "Sadhya", "Shubha", "Shukla", "Brahma", "Indra",
    "Vaidhriti",
)


def _yoga_sum(when):
    """Sun-plus-Moon sidereal longitude, degrees in ``[0, 360)``.

    Prograde like the individual longitudes, so monotonically increasing over
    a boundary search -- what :func:`ephemeris.find_crossing` requires.
    """
    return (
        ephemeris.sun_longitude(when) + ephemeris.moon_longitude(when)
    ) % 360.0


def tithi(on: date_cls, place: Place) -> list[AngaSpan]:
    """Tithi spans active from sunrise on ``on`` to the following sunrise.

    Each span's ``index`` is the tithi number ``1..30`` (1 = Shukla Pratipada,
    15 = Purnima, 16 = Krishna Pratipada, 30 = Amavasya). ``start`` and ``end``
    are the true instants the elongation crosses a multiple of 12 deg, in
    ``place``'s timezone.
    """
    return _angam_spans(
        ephemeris.elongation, DEGREES_PER_TITHI, TITHI_COUNT, _tithi_name,
        on, place,
    )


def nakshatra(on: date_cls, place: Place) -> list[AngaSpan]:
    """Nakshatra spans active from sunrise on ``on`` to the following sunrise.

    ``index`` is the nakshatra number ``1..27`` (1 = Ashwini). Boundaries are
    the instants the Moon's sidereal longitude crosses a multiple of
    13 deg 20 min.
    """
    return _angam_spans(
        ephemeris.moon_longitude, DEGREES_PER_NAKSHATRA, NAKSHATRA_COUNT,
        lambda n: _NAKSHATRA_NAMES[n - 1], on, place,
    )


def yoga(on: date_cls, place: Place) -> list[AngaSpan]:
    """Yoga spans active from sunrise on ``on`` to the following sunrise.

    ``index`` is the yoga number ``1..27`` (1 = Vishkambha). Boundaries are the
    instants the Sun-plus-Moon sidereal longitude sum crosses a multiple of
    13 deg 20 min.
    """
    return _angam_spans(
        _yoga_sum, DEGREES_PER_YOGA, YOGA_COUNT,
        lambda n: _YOGA_NAMES[n - 1], on, place,
    )


def _angam_spans(angle_fn, step_deg, count, name_fn, on, place):
    """Walk an angle divided into ``count`` equal ``step_deg`` steps across the
    sunrise-to-sunrise window.

    ``angle_fn`` maps a tz-aware datetime to a monotonically increasing angle in
    ``[0, 360)``. ``name_fn`` maps a 1-based division number to its name.
    """
    window_start = ephemeris.sunrise(on, place)
    window_end = ephemeris.sunrise(on + timedelta(days=1), place)
    search_span = timedelta(hours=_BOUNDARY_SEARCH_HOURS)

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
