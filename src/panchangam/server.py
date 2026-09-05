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

import argparse
import contextlib
import logging
from datetime import date
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anyio
import uvicorn
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from panchangam.types import AngaSpan, DayPanchangam, NamedPeriod, Place

logger = logging.getLogger("panchangam.server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
HTTP_PATH = "/mcp"


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

    def named_periods(self, place: Place, day: date) -> tuple[NamedPeriod, ...]:
        """The named auspicious/inauspicious periods of ``day`` at ``place``
        (Rahu Kalam, Yamaganda, Gulika Kalam, Abhijit, Durmuhurtam).

        Same date/timezone contract as :meth:`day_panchangam`.
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


# --- tools -------------------------------------------------------------------

# Both tools answer "for this civil day at this place"; the inputs are identical.
_DATE_LOCATION_SCHEMA: dict[str, Any] = {
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
}


def _serialize_location(place: Place) -> dict[str, Any]:
    return {
        "name": place.name,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "timezone": place.timezone,
    }


def _parse_date_and_place(arguments: dict[str, Any]) -> tuple[date, Place]:
    day = parse_query_date(arguments.get("date"))
    place = build_place(
        arguments.get("lat"), arguments.get("lon"), arguments.get("tz")
    )
    return day, place


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
    inputSchema=_DATE_LOCATION_SCHEMA,
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
        "location": _serialize_location(day.place),
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
    day, place = _parse_date_and_place(arguments)
    return _serialize_day(provider.day_panchangam(place, day))


_GET_MUHURTA_DESCRIPTION = """\
The auspicious and inauspicious periods within a single day at one place -- the \
part of Hindu almanac practice used to choose, or avoid, a time of day to begin \
something that matters: travel, a signing, a purchase, a ceremony.

Reach for this tool when the question is about timing *within* a day rather \
than the character of the day as a whole:
  - "when is Rahu Kalam", or which stretch of today to avoid starting something
  - the brief favourable window around noon ("Abhijit")
  - Gulika Kalam, Yamaganda, Durmuhurtam

What it returns for the requested day: a list of named periods, each with a \
local start and end time and a flag for whether it is one to seek out \
(auspicious) or to avoid (inauspicious). Every period is a fixed division of \
the time between sunrise and sunset, so the times depend on the place.

For the character of the whole day -- tithi, nakshatra, Moon phase, festival \
and Ekadashi dates -- use get_panchangam instead.
"""

_GET_MUHURTA_TOOL = Tool(
    name="get_muhurta",
    description=_GET_MUHURTA_DESCRIPTION,
    inputSchema=_DATE_LOCATION_SCHEMA,
)


def _serialize_period(period: NamedPeriod) -> dict[str, Any]:
    return {
        "name": period.name,
        "auspicious": period.auspicious,
        "starts": period.start.isoformat(),
        "ends": period.end.isoformat(),
    }


def _handle_get_muhurta(
    provider: PanchangamProvider, arguments: dict[str, Any]
) -> dict[str, Any]:
    day, place = _parse_date_and_place(arguments)
    periods = provider.named_periods(place, day)
    return {
        "location": _serialize_location(place),
        "date": day.isoformat(),
        "periods": [_serialize_period(p) for p in periods],
    }


def build_server(provider: PanchangamProvider) -> Server:
    """An MCP server whose tools are backed by ``provider``.

    The provider is the only moving part: pass ``FakePanchangamProvider()`` in
    tests, the real backend in production. Transport wiring is separate.
    """
    server: Server = Server("panchangam", version="0.1.0")

    handlers = {
        "get_panchangam": _handle_get_panchangam,
        "get_muhurta": _handle_get_muhurta,
    }

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [_GET_PANCHANGAM_TOOL, _GET_MUHURTA_TOOL]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            handler = handlers[name]
        except KeyError:
            raise RequestError(f"unknown tool {name!r}") from None
        return handler(provider, arguments)

    return server


# --- transports ---------------------------------------------------------------


async def run_stdio(provider: PanchangamProvider) -> None:
    """Serve the MCP protocol over stdin/stdout (the transport an MCP client
    spawns the process for)."""
    server = build_server(provider)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def build_http_app(provider: PanchangamProvider) -> Starlette:
    """A Starlette ASGI app serving the MCP protocol over Streamable HTTP at
    ``/mcp``.

    Stateless: every POST is a self-contained JSON-RPC exchange, no session to
    keep. Suitable to put behind any ASGI server; :func:`run_http` uses uvicorn.
    """
    session_manager = StreamableHTTPSessionManager(
        app=build_server(provider), json_response=True, stateless=True
    )

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with session_manager.run():
            yield

    return Starlette(routes=[Mount(HTTP_PATH, app=handle_mcp)], lifespan=lifespan)


def run_http(
    provider: PanchangamProvider,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    """Serve over Streamable HTTP on ``host:port`` (endpoint ``/mcp``)."""
    uvicorn.run(build_http_app(provider), host=host, port=port)


# --- entry point -------------------------------------------------------------


def load_provider() -> PanchangamProvider:
    """The calculation backend for the installed console script.

    Integration replaces this one function body with the Swiss Ephemeris
    provider. Until then the console script has no backend; construct the server
    directly with ``tests.fakes.FakePanchangamProvider`` for a runnable demo.
    """
    raise RuntimeError(
        "no panchangam calculation backend is wired yet -- integration pending. "
        "For a demo, call panchangam.server.run_http/run_stdio with "
        "tests.fakes.FakePanchangamProvider()."
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="panchangam-mcp",
        description="MCP server for Hindu almanac (panchangam) calculations.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio (default; the client spawns this process) or http.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="http transport bind host")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="http transport bind port"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    provider = load_provider()
    if args.transport == "stdio":
        anyio.run(run_stdio, provider)
    else:
        run_http(provider, args.host, args.port)
