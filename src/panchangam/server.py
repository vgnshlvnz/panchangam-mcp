"""MCP server exposing panchangam (Hindu almanac) calculations as tools.

This module owns the tool surface and the transport. It does no astronomy of
its own: every calculation comes from an injected :class:`PanchangamProvider`
(:class:`_SwissEphemerisProvider` in production; tests inject stubs or the real
one). Nothing here imports ``swisseph``.

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
import re
from datetime import date, datetime, timedelta
from functools import partial
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

from panchangam.hora import engine as hora_engine
from panchangam.hora.settings import (
    DEFAULT_OWN_LORD_FLOOR,
    load_profiles,
    own_lord_floor_from,
)
from panchangam.types import AngaSpan, DayPanchangam, NamedPeriod, Place

logger = logging.getLogger("panchangam.server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
HTTP_PATH = "/mcp"


class ProviderError(Exception):
    """A provider could not compute a result for an otherwise-valid request.

    Raised when the arguments parsed fine but no answer exists or can be
    produced -- e.g. the Sun neither rises nor sets at that latitude on that
    date, or an ephemeris backend fails. The message is caller-facing: the
    server turns it into a tool error result verbatim, so keep it specific and
    free of internal detail.
    """


class PanchangamProvider(Protocol):
    """The calculation backend the tools call.

    The server depends only on this Protocol; :func:`load_provider` chooses the
    implementation (:class:`_SwissEphemerisProvider`) and everything downstream
    -- :func:`build_server`, the transports, :func:`main` -- takes it as an
    argument.

    Both methods raise :class:`ProviderError` (and nothing else that is
    caller-facing) when a well-formed request has no result.
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

    def hora_day(self, place: Place, day: date) -> tuple[datetime, tuple[float, ...]]:
        """Sunrise of ``day`` at ``place`` (tz-aware) and the sidereal longitude,
        in degrees, of each of the 24 hora lords at the start of its hora."""
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


def _iso(when: datetime) -> str:
    """A tz-aware datetime as a second-precision ISO-8601 string.

    Anga and muhurta boundaries are meaningful to the minute; sub-second digits
    from the root-finder are noise, so they are dropped here.
    """
    return when.isoformat(timespec="seconds")


def _serialize_span(span: AngaSpan) -> dict[str, Any]:
    return {
        "name": span.name,
        "number": span.index,
        "starts": _iso(span.start),
        "ends": _iso(span.end),
    }


def _serialize_day(day: DayPanchangam) -> dict[str, Any]:
    """A DayPanchangam as a JSON-safe dict: every datetime a tz-aware ISO string."""
    return {
        "location": _serialize_location(day.place),
        "date": day.date.isoformat(),
        "weekday": day.vaara,
        "sunrise": _iso(day.sunrise),
        "sunset": _iso(day.sunset),
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
        "starts": _iso(period.start),
        "ends": _iso(period.end),
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


# --- hora tools --------------------------------------------------------------

_HORA_CAVEAT = (
    "Scores use PROVISIONAL nature, friendship and gochara tables chosen from "
    "general Jyotish knowledge, not yet verified against a printed source; treat "
    "them as a guide, not a ruling."
)

# Defaults for the hora tools: the household's place, so lat/lon/tz are optional.
_DEFAULT_LAT, _DEFAULT_LON, _DEFAULT_TZ = 3.1073, 101.6067, "Asia/Kuala_Lumpur"

_HORA_PLACE_PROPERTIES: dict[str, Any] = {
    "lat": {
        "type": "number",
        "description": f"Latitude in decimal degrees, north positive. Default {_DEFAULT_LAT} (Petaling Jaya).",
    },
    "lon": {
        "type": "number",
        "description": f"Longitude in decimal degrees, east positive. Default {_DEFAULT_LON}.",
    },
    "tz": {
        "type": "string",
        "description": f"IANA time-zone name. Default '{_DEFAULT_TZ}'.",
    },
}

_RASI_PROPERTY: dict[str, Any] = {
    "type": "integer",
    "minimum": 1,
    "maximum": 12,
    "description": (
        "The person's rasi (Moon sign) as a number: 1 Mesha, 2 Rishabha, 3 "
        "Mithuna, 4 Kataka, 5 Simha, 6 Kanya, 7 Tula, 8 Vrischika, 9 Dhanus, "
        "10 Makara, 11 Kumbha, 12 Meena."
    ),
}

_RASI_HORA_TABLE_DESCRIPTION = f"""\
How favourable each of the 24 horas (planetary hours) of a day is for one rasi. \
A hora is a fixed 60-minute slot counted from sunrise; hora 1 belongs to the \
lord of the weekday and the lords then follow the order Sun, Venus, Mercury, \
Moon, Saturn, Jupiter, Mars.

Reach for this tool when asked which hours of a day suit someone of a given \
rasi, or for the whole day's hora sequence with scores.

Returns, for the date and place: 24 rows of hora number, lord, local start and \
end ("HH:MM") and a score 0-100 (with score_breakdown, also its nature, \
friendship and gochara parts).

Example: rasi_hora_table with rasi=2 and date='2026-09-24'.

Not for: the hora running right now -- use current_hora instead. Not for picking \
the best times -- use best_horas to get only the top-scoring horas.

{_HORA_CAVEAT}
"""

_RASI_HORA_TABLE_TOOL = Tool(
    name="rasi_hora_table",
    description=_RASI_HORA_TABLE_DESCRIPTION,
    inputSchema={
        "type": "object",
        "additionalProperties": False,
        "required": ["rasi"],
        "properties": {
            "rasi": _RASI_PROPERTY,
            "date": {
                "type": "string",
                "description": "ISO-8601 'YYYY-MM-DD'. Default: today at the place.",
            },
            "score_breakdown": {
                "type": "boolean",
                "description": "Also return each row's nature, friendship and gochara parts.",
            },
            **_HORA_PLACE_PROPERTIES,
        },
    },
)

_CURRENT_HORA_DESCRIPTION = f"""\
The hora (planetary hour) in force right now at a place, scored for one rasi. \
Before sunrise it is the last hours of the previous day's cycle.

Reach for this tool when asked whether the present hour is good for someone of \
a given rasi, or what the current hora lord is.

Returns the hora number, lord, local start and end ("HH:MM"), the score 0-100 \
and the current local date and time.

Example: current_hora with rasi=2.

Not for: the whole day's sequence -- use rasi_hora_table instead.

{_HORA_CAVEAT}
"""

_CURRENT_HORA_TOOL = Tool(
    name="current_hora",
    description=_CURRENT_HORA_DESCRIPTION,
    inputSchema={
        "type": "object",
        "additionalProperties": False,
        "required": ["rasi"],
        "properties": {"rasi": _RASI_PROPERTY, **_HORA_PLACE_PROPERTIES},
    },
)


_BEST_HORAS_DESCRIPTION = f"""\
The best (highest-scoring) horas of a day for one rasi, optionally limited to a \
time range. A hora is a fixed 60-minute slot counted from sunrise, scored 0-100 \
for the rasi; only favourable horas (score 60 or more) are returned, best first, \
so fewer than count may come back.

Reach for this tool when asked "when is a good time" -- the best hora this \
morning, or the top three horas between 9am and 5pm. Each result has hora \
(1-24), lord, start and end (local "HH:MM") and score. from_time and to_time \
filter by the hora's start time, "HH:MM" 24-hour, from_time inclusive and \
to_time exclusive; from_time must be earlier than to_time. count is 1-24, \
default 3.

Example: best_horas with rasi=4, date='2026-09-24', count=3, from_time='09:00', \
to_time='17:00'.

Not for: the whole day's table or the reason behind a score -- use \
rasi_hora_table instead (with score_breakdown=true for the parts). Not for the \
hora running right now -- use current_hora.

{_HORA_CAVEAT}
"""

_BEST_HORAS_TOOL = Tool(
    name="best_horas",
    description=_BEST_HORAS_DESCRIPTION,
    inputSchema={
        "type": "object",
        "additionalProperties": False,
        "required": ["rasi"],
        "properties": {
            "rasi": _RASI_PROPERTY,
            "date": {
                "type": "string",
                "description": "ISO-8601 'YYYY-MM-DD'. Default: today at the place.",
            },
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 24,
                "description": "How many horas to return, 1-24. Default 3.",
            },
            "from_time": {
                "type": "string",
                "description": "Only horas starting at or after this local time, 'HH:MM'. Optional.",
            },
            "to_time": {
                "type": "string",
                "description": "Only horas starting before this local time, 'HH:MM'. Optional.",
            },
            **_HORA_PLACE_PROPERTIES,
        },
    },
)


def _hora_rasi(arguments: dict[str, Any]) -> int:
    rasi = arguments.get("rasi")
    if isinstance(rasi, bool) or not isinstance(rasi, int) or not 1 <= rasi <= 12:
        raise RequestError(f"rasi must be an integer 1..12, got {rasi!r}")
    return rasi


def _hora_place(arguments: dict[str, Any]) -> Place:
    return build_place(
        arguments.get("lat", _DEFAULT_LAT),
        arguments.get("lon", _DEFAULT_LON),
        arguments.get("tz", _DEFAULT_TZ),
    )


def _hhmm(when: datetime) -> str:
    return when.strftime("%H:%M")


def _weekday_sunday0(day: date) -> int:
    return (day.weekday() + 1) % 7


def _handle_rasi_hora_table(
    provider: PanchangamProvider,
    arguments: dict[str, Any],
    own_lord_floor: int = DEFAULT_OWN_LORD_FLOOR,
) -> dict[str, Any]:
    rasi = _hora_rasi(arguments)
    place = _hora_place(arguments)
    breakdown = arguments.get("score_breakdown", False)
    if not isinstance(breakdown, bool):
        raise RequestError(f"score_breakdown must be true or false, got {breakdown!r}")
    if "date" in arguments:
        day = parse_query_date(arguments["date"])
    else:
        day = datetime.now(ZoneInfo(place.timezone)).date()
    sunrise, longitudes = provider.hora_day(place, day)
    rows = hora_engine.hora_table(
        rasi, _weekday_sunday0(day), longitudes, own_lord_floor, breakdown
    )
    for row in rows:
        start = sunrise + timedelta(hours=int(row["hora"]) - 1)
        row["start"] = _hhmm(start)
        row["end"] = _hhmm(start + timedelta(hours=1))
    return {
        "location": _serialize_location(place),
        "date": day.isoformat(),
        "rasi": rasi,
        "horas": rows,
        "caveat": _HORA_CAVEAT,
    }


def _handle_current_hora(
    provider: PanchangamProvider,
    arguments: dict[str, Any],
    own_lord_floor: int = DEFAULT_OWN_LORD_FLOOR,
    now: datetime | None = None,
) -> dict[str, Any]:
    rasi = _hora_rasi(arguments)
    place = _hora_place(arguments)
    now = now or datetime.now(ZoneInfo(place.timezone))
    day = now.date()
    sunrise, longitudes = provider.hora_day(place, day)
    if now < sunrise:  # still inside the previous day's hora cycle
        day -= timedelta(days=1)
        sunrise, longitudes = provider.hora_day(place, day)
    hora = min(int((now - sunrise) / timedelta(hours=1)) + 1, hora_engine.HORAS_PER_DAY)
    lord = hora_engine.hora_lord(_weekday_sunday0(day), hora)
    score = hora_engine.score_hora(rasi, lord, longitudes[hora - 1], own_lord_floor)
    start = sunrise + timedelta(hours=hora - 1)
    return {
        "location": _serialize_location(place),
        "date": now.date().isoformat(),
        "time": _hhmm(now),
        "rasi": rasi,
        "hora": hora,
        "lord": lord,
        "start": _hhmm(start),
        "end": _hhmm(start + timedelta(hours=1)),
        "score": score["total"],
        "caveat": _HORA_CAVEAT,
    }


_HHMM_RE = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


def _parse_hhmm(value: object, name: str) -> str:
    match = _HHMM_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise RequestError(
            f"{name} must be a 24-hour local time like '09:30', got {value!r}"
        )
    return f"{int(match[1]):02d}:{match[2]}"


def _handle_best_horas(
    provider: PanchangamProvider,
    arguments: dict[str, Any],
    own_lord_floor: int = DEFAULT_OWN_LORD_FLOOR,
) -> dict[str, Any]:
    count = arguments.get("count", 3)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 24:
        raise RequestError(f"count must be an integer 1-24, got {count!r}")
    lo = arguments.get("from_time")
    hi = arguments.get("to_time")
    if lo is not None:
        lo = _parse_hhmm(lo, "from_time")
    if hi is not None:
        hi = _parse_hhmm(hi, "to_time")
    if lo is not None and hi is not None and lo >= hi:
        raise RequestError(f"from_time ({lo}) must be earlier than to_time ({hi})")

    out = _handle_rasi_hora_table(provider, arguments, own_lord_floor)
    picked = [
        r
        for r in out["horas"]
        if r["score"] >= hora_engine.FAVOURABLE_MIN
        and (lo is None or r["start"] >= lo)
        and (hi is None or r["start"] < hi)
    ]
    picked.sort(key=lambda r: (-r["score"], r["hora"]))
    return {**out, "horas": picked[:count]}


# --- personal tool -----------------------------------------------------------

_PERSONAL_MUHURTA_DESCRIPTION = """\
A stored person's personal muhurta card for a day: tarabala and chandrabala \
against their janma star and rasi, chandrashtama warning, good lagna windows and \
the day's kalams, as a ready-to-send message.

Reach for this tool when asked for someone's personal daily card or their good \
times today. The person must exist in the server's profiles file \
(~/.config/panchangam/profiles.yaml).

Example: personal_muhurta with profile='vignesh'.

Not for: general almanac data or Rahu Kalam for anyone -- use get_panchangam or \
get_muhurta instead.
"""

_PERSONAL_MUHURTA_TOOL = Tool(
    name="personal_muhurta",
    description=_PERSONAL_MUHURTA_DESCRIPTION,
    inputSchema={
        "type": "object",
        "additionalProperties": False,
        "required": ["profile"],
        "properties": {
            "profile": {
                "type": "string",
                "description": "Profile key in profiles.yaml, e.g. 'vignesh' or 'amma'.",
            },
            "date": {
                "type": "string",
                "description": "ISO-8601 'YYYY-MM-DD'. Default: today at the profile's place.",
            },
            "lang": {
                "type": "string",
                "enum": ["en", "ta"],
                "description": "Card language. Default: the profile's own language.",
            },
        },
    },
)


def _handle_personal_muhurta(
    provider: PanchangamProvider, arguments: dict[str, Any]
) -> dict[str, Any]:
    # Imported here: personal pulls in the swisseph-backed modules and PyYAML.
    from panchangam.personal.cli import DEFAULT_CFG
    from panchangam.personal.mcp_tool import personal_card

    profile = arguments.get("profile")
    if not isinstance(profile, str):
        raise RequestError(f"profile must be a string, got {profile!r}")
    lang = arguments.get("lang")
    if lang not in (None, "en", "ta"):
        raise RequestError(f"lang must be 'en' or 'ta', got {lang!r}")
    try:
        day = (
            parse_query_date(arguments["date"])
            if "date" in arguments
            else None
        )
        return {"profile": profile, "card": personal_card(profile, day, lang)}
    except FileNotFoundError:
        raise ProviderError(f"no profiles file at {DEFAULT_CFG}") from None
    except KeyError as exc:
        raise RequestError(f"unknown profile {profile!r} (missing key {exc})") from None


class ToolError(Exception):
    """A tool call failed. ``str(self)`` is what the caller sees in the MCP
    error result, so it is always a clean, actionable sentence."""


def _invoke(
    handler: Any, provider: PanchangamProvider, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Run a tool handler, mapping every failure to a :class:`ToolError`.

    - bad arguments (:class:`RequestError`)  -> "invalid arguments: ..."
    - no result for a valid request (:class:`ProviderError`) -> "cannot compute: ..."
    - anything else -> a generic message; the real error goes to the log, not
      the caller.
    """
    try:
        return handler(provider, arguments)
    except RequestError as exc:
        raise ToolError(f"invalid arguments: {exc}") from exc
    except ProviderError as exc:
        raise ToolError(f"cannot compute: {exc}") from exc
    except Exception as exc:  # last line of defence -- never leak a traceback
        logger.exception("tool handler raised an unexpected error")
        raise ToolError(
            "internal error: the request parsed but the server could not "
            "produce a result. This is a bug; see the server log."
        ) from exc


def build_server(provider: PanchangamProvider) -> Server:
    """An MCP server whose tools are backed by ``provider``.

    The provider is the only moving part. Transport wiring is separate.
    """
    server: Server = Server("panchangam", version="0.1.0")

    own_lord_floor = own_lord_floor_from(load_profiles())
    handlers = {
        "get_panchangam": _handle_get_panchangam,
        "get_muhurta": _handle_get_muhurta,
        "rasi_hora_table": partial(_handle_rasi_hora_table, own_lord_floor=own_lord_floor),
        "best_horas": partial(_handle_best_horas, own_lord_floor=own_lord_floor),
        "current_hora": partial(_handle_current_hora, own_lord_floor=own_lord_floor),
        "personal_muhurta": _handle_personal_muhurta,
    }

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            _GET_PANCHANGAM_TOOL,
            _GET_MUHURTA_TOOL,
            _RASI_HORA_TABLE_TOOL,
            _BEST_HORAS_TOOL,
            _CURRENT_HORA_TOOL,
            _PERSONAL_MUHURTA_TOOL,
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = handlers.get(name)
        if handler is None:
            raise ToolError(
                f"unknown tool {name!r}; available: {', '.join(handlers)}"
            )
        return _invoke(handler, provider, arguments)

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


class _SwissEphemerisProvider:
    """Adapter: the ``angas`` / ``muhurta`` / ``ephemeris`` lanes as one
    :class:`PanchangamProvider`.

    Those modules expose granular ``(date, place)`` functions; this composes
    them into the aggregate values the tools return. It is the whole of the
    integration seam -- ``build_server``, the transports and ``main`` are
    already provider-agnostic.
    """

    def __init__(self) -> None:
        from panchangam import angas, ephemeris, muhurta

        self._angas = angas
        self._ephemeris = ephemeris
        self._muhurta = muhurta

    def hora_day(self, place: Place, day: date) -> tuple[datetime, tuple[float, ...]]:
        ephemeris = self._ephemeris
        try:
            sunrise = ephemeris.sunrise(day, place)
        except ephemeris.CircumpolarError as exc:
            raise ProviderError(str(exc)) from exc
        weekday = _weekday_sunday0(day)
        longitudes = tuple(
            ephemeris.graha_longitude(
                ephemeris.Graha[hora_engine.hora_lord(weekday, hora).upper()],
                sunrise + timedelta(hours=hora - 1),
            )
            for hora in range(1, hora_engine.HORAS_PER_DAY + 1)
        )
        return sunrise, longitudes

    def day_panchangam(self, place: Place, day: date) -> DayPanchangam:
        angas, ephemeris = self._angas, self._ephemeris
        try:
            return DayPanchangam(
                place=place,
                date=day,
                sunrise=ephemeris.sunrise(day, place),
                sunset=ephemeris.sunset(day, place),
                vaara=angas.vara(day, place).name,
                tithi=tuple(angas.tithi(day, place)),
                nakshatra=tuple(angas.nakshatra(day, place)),
                yoga=tuple(angas.yoga(day, place)),
                karana=tuple(angas.karana(day, place)),
            )
        except ephemeris.CircumpolarError as exc:
            raise ProviderError(str(exc)) from exc

    def named_periods(self, place: Place, day: date) -> tuple[NamedPeriod, ...]:
        m, ephemeris = self._muhurta, self._ephemeris
        try:
            return (
                m.abhijit(day, place),
                m.rahu_kalam(day, place),
                m.yamaganda(day, place),
                m.gulika(day, place),
                *m.durmuhurtam(day, place),
            )
        except ephemeris.CircumpolarError as exc:
            raise ProviderError(str(exc)) from exc


def load_provider() -> PanchangamProvider:
    """The calculation backend for the installed console script.

    Swiss Ephemeris (Moshier), via :class:`_SwissEphemerisProvider`. This is the
    one place the backend is chosen; everything downstream takes the provider as
    an argument.
    """
    return _SwissEphemerisProvider()


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
