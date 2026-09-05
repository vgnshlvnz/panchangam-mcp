"""MCP server exposing panchangam (Hindu almanac) calculations as tools.

This module owns the tool surface and the transport. It does no astronomy of
its own: every calculation comes from an injected :class:`PanchangamProvider`,
so the fixture-backed fake used in tests and the real Swiss Ephemeris
implementation are interchangeable.

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
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server import Server
from mcp.types import Tool

from panchangam.types import AngaSpan, DayPanchangam, Place


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


# --- get_panchangam -------------------------------------------------------------

_GET_PANCHANGAM_DESCRIPTION = """\
The Hindu almanac ("panchangam" / "panchang") for one calendar day at one place \
on Earth. The panchangam describes a day through the positions of the Moon and \
Sun rather than the civil clock, and is the basis of the traditional Indian \
lunisolar calendar.

Reach for this tool when the question involves:
  - the lunar day, the Moon's phase, or whether a fortnight is waxing or waning
  - which "star" (nakshatra) the Moon is in on a date -- often asked about a \
birth date
  - the date of a Hindu observance tied to the Moon: Ekadashi, Amavasya (new \
moon), Purnima (full moon), Sankranti, or a festival whose date shifts each year
  - whether a given day is considered favourable or unfavourable in the Hindu \
calendar, and the exact times its character changes
  - local sunrise and sunset for that date and place

What it returns for the requested day (the traditional day runs from one \
sunrise to the next):
  - sunrise, sunset -- local timestamps
  - weekday
  - tithi: the lunar day. The Moon's angle ahead of the Sun is divided into 30 \
steps; each step is a tithi and ends at a precise instant. Two are listed when \
one ends during the day.
  - nakshatra: which of 27 named zones along the Moon's path it occupies, with \
the instant it moves to the next
  - yoga, karana: two further Sun-Moon subdivisions used when picking auspicious \
moments, each with its start and end

Each of tithi / nakshatra / yoga / karana comes back as the segment(s) covering \
the day, with the exact clock time each begins and ends.

Not for: casting a horoscope or birth chart, predictive astrology, or \
gemstone/ritual advice -- this is calendar and astronomy only. To find good and \
bad times *within* a day (Rahu Kalam, Abhijit muhurta, and similar), use \
get_muhurta.
"""

_GET_PANCHANGAM_TOOL = Tool(
    name="get_panchangam",
    description=_GET_PANCHANGAM_DESCRIPTION,
    inputSchema={
        "type": "object",
        "additionalProperties": False,
        "required": ["date", "lat", "lon", "tz"],
        "properties": {
            "date": {
                "type": "string",
                "description": (
                    "Calendar date to compute, as ISO-8601 'YYYY-MM-DD' with "
                    "zero-padded fields, e.g. '2026-09-06'. A civil date only; "
                    "the time of day is not part of the query."
                ),
            },
            "lat": {
                "type": "number",
                "description": (
                    "Latitude of the place in decimal degrees, north positive, "
                    "-90 to 90. Sunrise-based day boundaries make the result "
                    "location-specific."
                ),
            },
            "lon": {
                "type": "number",
                "description": (
                    "Longitude of the place in decimal degrees, east positive, "
                    "-180 to 180."
                ),
            },
            "tz": {
                "type": "string",
                "description": (
                    "IANA time-zone name for the place, e.g. 'Asia/Kolkata', "
                    "'America/New_York', 'Asia/Kuala_Lumpur'. Every timestamp in "
                    "the result is expressed in this zone. A bare UTC offset such "
                    "as '+05:30' is not accepted: the named zone is needed to "
                    "line civil days up with local sunrise and to handle DST."
                ),
            },
        },
    },
)


def _serialize_span(span: AngaSpan) -> dict[str, Any]:
    return {
        "name": span.name,
        "number": span.index,
        "starts": span.start.isoformat(),
        "ends": span.end.isoformat(),
    }


def _serialize_day(day: DayPanchangam) -> dict[str, Any]:
    """A DayPanchangam as a JSON-safe dict: every datetime a tz-aware ISO string."""
    return {
        "location": {
            "name": day.place.name,
            "latitude": day.place.latitude,
            "longitude": day.place.longitude,
            "timezone": day.place.timezone,
        },
        "date": day.date.isoformat(),
        "weekday": day.vaara,
        "sunrise": day.sunrise.isoformat(),
        "sunset": day.sunset.isoformat(),
        "tithi": [_serialize_span(s) for s in day.tithi],
        "nakshatra": [_serialize_span(s) for s in day.nakshatra],
        "yoga": [_serialize_span(s) for s in day.yoga],
        "karana": [_serialize_span(s) for s in day.karana],
    }


def _handle_get_panchangam(
    provider: PanchangamProvider, arguments: dict[str, Any]
) -> dict[str, Any]:
    day = parse_query_date(arguments.get("date"))
    place = build_place(
        arguments.get("lat"), arguments.get("lon"), arguments.get("tz")
    )
    return _serialize_day(provider.day_panchangam(place, day))


def build_server(provider: PanchangamProvider) -> Server:
    """An MCP server whose tools are backed by ``provider``.

    The provider is the only moving part: pass ``FakePanchangamProvider()`` in
    tests, the real backend in production. Transport wiring is separate.
    """
    server: Server = Server("panchangam")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [_GET_PANCHANGAM_TOOL]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_panchangam":
            return _handle_get_panchangam(provider, arguments)
        raise RequestError(f"unknown tool {name!r}")

    return server
