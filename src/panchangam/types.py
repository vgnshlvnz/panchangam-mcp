"""Shared value types for the panchangam package.

Contract between lanes. Imports nothing from the package, no third-party deps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Place:
    """A geographic location for which panchangam quantities are computed.

    name:        display/identity only; no computation depends on it.
    latitude:    degrees, north positive, [-90, 90].
    longitude:   degrees, east positive, [-180, 180].
    timezone:    IANA name, e.g. "Asia/Kuala_Lumpur". Wall-clock results are
                 expressed in this zone. A string, not a tzinfo, so a Place
                 stays serializable across the MCP boundary.
    elevation_m: metres above sea level; shifts rise/set by a few seconds.
    """

    name: str
    latitude: float
    longitude: float
    timezone: str
    elevation_m: float = 0.0


@dataclass(frozen=True)
class AngaSpan:
    """One occurrence of an anga (tithi / nakshatra / yoga / karana).

    index: 1-based number within the anga's own cycle — tithi 1..30,
           nakshatra 1..27, yoga 1..27, karana 1..60.
    name:  human name, e.g. "Krishna Dashami", "Ardra", "Vishkambha".
    start: instant the anga begins; tz-aware, in the Place's zone. Usually
           precedes the sunrise that opens the query window.
    end:   instant it ends; tz-aware, same zone. Usually follows the closing
           sunrise. end == the next span's start.
    """

    index: int
    name: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class DayPanchangam:
    """The five angas of one civil day at one place, plus its solar frame.

    A panchangam ("five limbs") answers, for a date and a location: which
    tithi, vaara, nakshatra, yoga and karana are in force, and when each of the
    four varying ones begins and ends.

    place:     where this was computed; its timezone is the zone of every
               datetime below.
    date:      the civil day requested. The day runs sunrise to sunrise, so the
               spans below may start before it and end after it.
    sunrise:   sunrise on ``date`` at ``place``; opens the day window.
    sunset:    sunset on ``date``.
    vaara:     weekday name — the one anga fixed for the whole civil day, e.g.
               "Shanivara" for Saturday.
    tithi:     tithi span(s) overlapping the sunrise-to-next-sunrise window, in
               chronological order — one if no boundary falls within the day,
               two if it does.
    nakshatra: nakshatra span(s), same convention.
    yoga:      yoga span(s), same convention.
    karana:    karana span(s), same convention. A karana is half a tithi, so a
               day usually holds two or three.
    """

    place: Place
    date: date
    sunrise: datetime
    sunset: datetime
    vaara: str
    tithi: tuple[AngaSpan, ...]
    nakshatra: tuple[AngaSpan, ...]
    yoga: tuple[AngaSpan, ...]
    karana: tuple[AngaSpan, ...]


@dataclass(frozen=True)
class NamedPeriod:
    """A named stretch of a day that muhurta practice singles out.

    Examples: Rahu Kalam, Yamaganda, Gulika Kalam (avoid); Abhijit Muhurta
    (seek); Durmuhurtam (avoid), which can occur twice in a day. Each is a
    fixed division of the daylight span on the requested date.

    name:       transliterated label, e.g. "Rahu Kalam".
    start:      tz-aware, in the Place's zone.
    end:        tz-aware, same zone. Always after ``start``; a period does not
                wrap past midnight.
    auspicious: True for a period to seek out, False for one to avoid.
    """

    name: str
    start: datetime
    end: datetime
    auspicious: bool
