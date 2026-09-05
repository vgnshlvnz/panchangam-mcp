"""MCP server exposing panchangam (Hindu almanac) calculations as tools.

This module owns the tool surface and the transport. It does no astronomy of
its own: every calculation comes from a *provider* (see :class:`PanchangamProvider`
in a later commit). The provider is injected, so the fixture-backed fake used in
tests and the real Swiss Ephemeris implementation are interchangeable.

Boundary rules for every tool:

* Locations arrive as three separate primitives -- ``lat``, ``lon``, ``tz`` --
  and are assembled into a :class:`panchangam.types.Place` here.
* ``tz`` is an IANA zone name (``"Asia/Kuala_Lumpur"``), never a UTC offset.
* Any datetime returned to the caller is a timezone-aware ISO-8601 string in
  that zone. No naive strings, no epoch integers.
* Bad input produces a :class:`RequestError` whose message tells the caller how
  to fix the call -- never a bare stack trace.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from panchangam.types import DayPanchangam, Place


class PanchangamProvider(Protocol):
    """The calculation backend the tools call.

    The server depends only on this Protocol. ``FakePanchangamProvider`` in
    ``tests/fakes.py`` satisfies it from fixtures today; the Swiss Ephemeris
    implementation satisfies it at integration. Swapping the two is one import
    change plus the constructor argument to :func:`build_server`.
    """

    def day_panchangam(self, place: Place, day: date) -> DayPanchangam:
        """The five angas in force on the civil day ``day`` at ``place``.

        ``day`` is a plain date; the provider resolves it against ``place``'s
        timezone. Every datetime in the result is tz-aware in that zone.
        """
        ...


class RequestError(ValueError):
    """A tool argument failed validation.

    The message is written for the model that called the tool: it names the
    offending argument, shows the value received, and states what a valid value
    looks like.
    """


def parse_query_date(value: object) -> date:
    """A calendar date for which the panchangam is wanted, e.g. ``"2026-09-06"``.

    Accepts an ISO-8601 date string with zero-padded fields. A panchangam is a
    property of a civil day at a place, so this is a plain date, not a datetime:
    the time of day is irrelevant and a timezone is supplied separately as
    ``tz``.
    """
    if not isinstance(value, str):
        raise RequestError(
            f"date must be a string like '2026-09-06', got {type(value).__name__}"
        )
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise RequestError(
            f"date must be an ISO-8601 calendar date with zero-padded fields, "
            f"like '2026-09-06'; got {value!r}"
        ) from None


def _coerce_degrees(value: object, axis: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise RequestError(
            f"{axis} must be a number in degrees, got {type(value).__name__}"
        )
    try:
        return float(value)
    except ValueError:
        raise RequestError(
            f"{axis} must be a number in degrees, got {value!r}"
        ) from None


def build_place(
    lat: object,
    lon: object,
    tz: object,
    *,
    name: str = "query location",
    elevation_m: float = 0.0,
) -> Place:
    """Assemble a :class:`Place` from the three location primitives a tool takes.

    ``lat``  -- degrees north of the equator, -90 to 90.
    ``lon``  -- degrees east of Greenwich, -180 to 180.
    ``tz``   -- IANA timezone name (``"Asia/Kolkata"``, ``"America/New_York"``).
                A UTC offset such as ``"+05:30"`` is rejected: the calendar needs
                the named zone to place civil days and handle DST.

    Raises :class:`RequestError` with an actionable message on any bad value.
    """
    latitude = _coerce_degrees(lat, "lat")
    longitude = _coerce_degrees(lon, "lon")

    if not -90.0 <= latitude <= 90.0:
        raise RequestError(
            f"lat must be between -90 and 90 degrees, got {latitude}"
        )
    if not -180.0 <= longitude <= 180.0:
        raise RequestError(
            f"lon must be between -180 and 180 degrees, got {longitude}"
        )

    if not isinstance(tz, str):
        raise RequestError(
            f"tz must be an IANA timezone name like 'Asia/Kuala_Lumpur', "
            f"got {type(tz).__name__}"
        )
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise RequestError(
            f"tz must be an IANA timezone name like 'Asia/Kuala_Lumpur' "
            f"(not a UTC offset); {tz!r} is not a known zone"
        ) from None

    return Place(
        name=name,
        latitude=latitude,
        longitude=longitude,
        timezone=tz,
        elevation_m=elevation_m,
    )
