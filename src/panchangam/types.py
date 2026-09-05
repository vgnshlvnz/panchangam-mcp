"""Shared value types for the panchangam package.

Contract between lanes. Imports nothing from the package, no third-party deps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
