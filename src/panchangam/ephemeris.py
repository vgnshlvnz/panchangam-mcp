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
from collections.abc import Callable
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import swisseph as swe

from panchangam.types import Place

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


_SIDEREAL_FLAG = _EPHE_FLAG | swe.FLG_SIDEREAL | swe.FLG_SPEED

#: Sentinel enum value for Ketu, which is not a swisseph body.
_KETU_ID = 900


class Graha(enum.Enum):
    """The nine grahas of Vedic astrology. Value is the ``swisseph`` body id.

    ``RAHU`` is the **mean** lunar node -- the convention drikpanchang.com uses
    by default. ``KETU`` has no swisseph body; it is the point exactly 180 deg
    opposite Rahu.
    """

    SUN = swe.SUN
    MOON = swe.MOON
    MERCURY = swe.MERCURY
    VENUS = swe.VENUS
    MARS = swe.MARS
    JUPITER = swe.JUPITER
    SATURN = swe.SATURN
    RAHU = swe.MEAN_NODE
    KETU = _KETU_ID


def _calc(when: datetime, body: int) -> tuple[float, float]:
    """(sidereal longitude in [0, 360), longitude speed in deg/day) for ``body``."""
    _ensure_configured()
    values, status = swe.calc_ut(_julian_day_ut(when), body, _SIDEREAL_FLAG)
    if status < 0:
        raise RuntimeError(
            f"swisseph.calc_ut failed for body {body} at {when!r}: {status}"
        )
    return values[0] % 360.0, values[3]


def graha_longitude(graha: Graha, when: datetime) -> float:
    """Sidereal ecliptic longitude of ``graha`` at ``when``, degrees in [0, 360).

    ``when`` must be timezone-aware. Ketu is returned as Rahu + 180 deg.
    """
    if graha is Graha.KETU:
        return (graha_longitude(Graha.RAHU, when) + 180.0) % 360.0
    return _calc(when, graha.value)[0]


def sun_longitude(when: datetime) -> float:
    """Sidereal ecliptic longitude of the Sun at ``when``, degrees in [0, 360).

    ``when`` must be timezone-aware.
    """
    return graha_longitude(Graha.SUN, when)


def moon_longitude(when: datetime) -> float:
    """Sidereal ecliptic longitude of the Moon at ``when``, degrees in [0, 360).

    ``when`` must be timezone-aware.
    """
    return graha_longitude(Graha.MOON, when)


class CircumpolarError(ValueError):
    """Raised when the Sun does not rise or set on the requested day."""


def _utc_from_jd(jd_ut: float) -> datetime:
    """A Julian Day in UT to a timezone-aware UTC datetime."""
    year, month, day, hour = swe.revjul(jd_ut, swe.GREG_CAL)
    midnight = datetime(year, month, day, tzinfo=timezone.utc)
    return midnight + timedelta(hours=hour)


def _sun_event(kind: int, on: date_cls, place: Place) -> datetime:
    _ensure_configured()
    tz = ZoneInfo(place.timezone)
    day_start = datetime(on.year, on.month, on.day, tzinfo=tz)
    geopos = (place.longitude, place.latitude, place.elevation_m)
    status, times = swe.rise_trans(
        _julian_day_ut(day_start), swe.SUN, kind, geopos, 0.0, 0.0, _EPHE_FLAG
    )
    if status != 0:
        raise CircumpolarError(
            f"Sun has no {'rise' if kind & swe.CALC_RISE else 'set'} at "
            f"{place.name} on {on.isoformat()}"
        )
    return _utc_from_jd(times[0]).astimezone(tz)


def sunrise(on: date_cls, place: Place) -> datetime:
    """Sunrise at ``place`` on the calendar date ``on``.

    Returns a timezone-aware datetime in ``place``'s zone.

    Convention: the instant the Sun's **upper limb** reaches the horizon,
    **with** standard atmospheric refraction (Swiss Ephemeris default -- the
    same "true horizon" definition almanacs and drikpanchang.com use, not the
    Hindu disc-centre / no-refraction variant). Refraction is computed for a
    standard atmosphere at ``place.elevation_m``; horizon dip from elevation is
    included. Raises :class:`CircumpolarError` above the polar circles.
    """
    return _sun_event(swe.CALC_RISE, on, place)


def sunset(on: date_cls, place: Place) -> datetime:
    """Sunset at ``place`` on the calendar date ``on``.

    Timezone-aware datetime in ``place``'s zone. Same disc/refraction
    convention as :func:`sunrise` -- upper limb at the true horizon, with
    refraction. Raises :class:`CircumpolarError` above the polar circles.
    """
    return _sun_event(swe.CALC_SET, on, place)


def _signed_delta(angle: float, base: float) -> float:
    """Angle minus base, wrapped into (-180, 180]. Used to unwrap across 0/360."""
    return (angle - base + 180.0) % 360.0 - 180.0


def find_crossing(
    fn: Callable[[datetime], float],
    target_deg: float,
    lo: datetime,
    hi: datetime,
    *,
    tolerance: timedelta = timedelta(seconds=1),
) -> datetime:
    """Instant in ``[lo, hi]`` at which the angle ``fn(t)`` reaches ``target_deg``.

    ``fn`` maps a timezone-aware datetime to an angle in degrees. The angle is
    compared modulo 360, so passing ``target_deg = k * 12`` locates the k-th
    tithi boundary, ``k * (360 / 27)`` the k-th nakshatra boundary, and so on.

    Preconditions -- the caller is expected to bracket tightly:

    * ``fn`` is continuous and *monotonically increasing* on ``[lo, hi]``. Every
      panchangam angle (solar/lunar longitude, their elongation) is prograde,
      so this holds; a decreasing ``fn`` is rejected.
    * ``fn`` advances by less than 180 deg between ``lo`` and ``hi``. Boundary
      searches span minutes to a couple of hours, far below this.
    * ``target_deg`` (mod 360) lies within the arc ``fn`` sweeps.

    :class:`ValueError` is raised if a precondition fails. ``lo`` and ``hi``
    must be timezone-aware. Bisects until the bracket is narrower than
    ``tolerance``; the returned datetime carries ``lo``'s timezone.
    """
    if lo.tzinfo is None or hi.tzinfo is None:
        raise NaiveDatetimeError(
            f"bracket must be timezone-aware, got lo={lo!r}, hi={hi!r}"
        )
    if hi <= lo:
        raise ValueError(f"expected lo < hi, got lo={lo!r}, hi={hi!r}")

    base = fn(lo)
    span = _signed_delta(fn(hi), base)  # signed travel over [lo, hi]
    if span <= 0.0:
        raise ValueError(
            f"fn must increase across [{lo}, {hi}] by (0, 180) deg, "
            f"got travel {span:.6f} deg"
        )
    offset = _signed_delta(target_deg, base)  # target's position along the arc
    if not 0.0 <= offset <= span:
        raise ValueError(
            f"target {target_deg} deg is not in the arc fn sweeps over "
            f"[{lo}, {hi}] (0 to {span:.6f} deg from fn(lo))"
        )
    if offset == 0.0:
        return lo
    if offset == span:
        return hi

    while hi - lo > tolerance:
        mid = lo + (hi - lo) / 2
        if _signed_delta(fn(mid), base) < offset:
            lo = mid
        else:
            hi = mid

    return lo + (hi - lo) / 2
