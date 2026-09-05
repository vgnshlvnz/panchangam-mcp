"""Swiss Ephemeris adapter.

Nothing above this module imports ``swisseph``. Every astronomical quantity
the panchangam needs -- sidereal planetary longitudes, sunrise/sunset,
root-finding on an angle -- enters the package through here.

Ephemeris backend
-----------------
Moshier (``swe.FLG_MOSEPH``). No external ephemeris data files are required.
Accuracy for the Sun and Moon over the modern era is a few arc-seconds, which
is far inside the panchangam tolerances: a 2-minute anga boundary corresponds
to roughly one arc-minute of lunar motion.

Zodiac
------
Sidereal. The ayanamsa is selectable between Lahiri (the default) and Raman.
``swisseph`` keeps the ayanamsa choice in global state, so :func:`configure`
(called lazily) sets it once per process.

Time
----
Every datetime that crosses this module's boundary -- in or out -- must be
timezone-aware. A naive datetime is rejected with :class:`NaiveDatetimeError`
rather than silently assumed to be UTC or local; the layer above computes
tithi relative to local sunrise and a dropped ``tzinfo`` produces a wrong
answer without an error.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

import swisseph as swe

#: Ephemeris flag used for every calculation in this module.
_EPHE_FLAG = swe.FLG_MOSEPH


class Ayanamsa(enum.Enum):
    """Sidereal reference frame. Value is the ``swisseph`` SIDM constant."""

    LAHIRI = swe.SIDM_LAHIRI
    RAMAN = swe.SIDM_RAMAN


DEFAULT_AYANAMSA = Ayanamsa.LAHIRI

_configured_ayanamsa: Ayanamsa | None = None


class NaiveDatetimeError(ValueError):
    """Raised when a datetime without ``tzinfo`` reaches this module."""


def configure(ayanamsa: Ayanamsa = DEFAULT_AYANAMSA) -> None:
    """Set the sidereal mode. Idempotent; safe to call repeatedly.

    Callers do not normally need this -- every public function configures the
    default lazily. Pass it explicitly to switch between Lahiri and Raman.
    """
    global _configured_ayanamsa
    swe.set_sid_mode(ayanamsa.value, 0.0, 0.0)
    _configured_ayanamsa = ayanamsa


def _ensure_configured() -> None:
    if _configured_ayanamsa is None:
        configure()


def _julian_day_ut(when: datetime) -> float:
    """Convert a tz-aware datetime to a Julian Day in Universal Time."""
    if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
        raise NaiveDatetimeError(
            f"datetime must be timezone-aware, got {when!r}"
        )
    ut = when.astimezone(timezone.utc)
    hour = ut.hour + ut.minute / 60 + (ut.second + ut.microsecond / 1e6) / 3600
    return swe.julday(ut.year, ut.month, ut.day, hour, swe.GREG_CAL)


def ayanamsa_degrees(when: datetime, ayanamsa: Ayanamsa | None = None) -> float:
    """Ayanamsa at ``when`` in fractional degrees.

    ``when`` must be timezone-aware. Pass ``ayanamsa`` to override the
    configured default for this one call.
    """
    if ayanamsa is not None:
        configure(ayanamsa)
    else:
        _ensure_configured()
    return swe.get_ayanamsa_ut(_julian_day_ut(when))
