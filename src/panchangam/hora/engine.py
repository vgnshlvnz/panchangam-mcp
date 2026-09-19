"""Hora scoring for a rasi. Pure: no I/O, no config reads, no ephemeris.

Callers pass in everything that varies -- the rasi, the weekday, the sidereal
longitude of each hora's lord, and the own-lord floor. Tables are fixed tuples
and scoring is integer maths, so this ports to C with fixed arrays.

PROVISIONAL: the nature, friendship and gochara tables below are defaults chosen
by the assistant from general Jyotish knowledge, not taken from a printed source.
TODO: verify against the user's reference before relying on any score.

Indices are 1-based for rasi (1..12) and hora (1..24); weekday is Sunday=0..Saturday=6.
"""

from __future__ import annotations

# Chaldean order used for horas: hora 1 is the weekday lord, then this sequence.
HORA_SEQUENCE = ("Sun", "Venus", "Mercury", "Moon", "Saturn", "Jupiter", "Mars")
WEEKDAY_LORD = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")
# Aries .. Pisces
RASI_LORD = (
    "Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
    "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter",
)

HORAS_PER_DAY = 24

#: A hora scoring at least this counts as favourable (used by best_horas).
FAVOURABLE_MIN = 60

# --- score parts (each 0..max; the three maxima sum to 100) --------------------

NATURE = {
    "Jupiter": 30, "Venus": 30, "Moon": 25, "Mercury": 25,
    "Sun": 15, "Mars": 10, "Saturn": 10,
}

FRIENDSHIP_OWN, FRIENDSHIP_FRIEND, FRIENDSHIP_NEUTRAL, FRIENDSHIP_ENEMY = 30, 25, 15, 5

# Natural friendship, as the rasi's lord sees the hora lord. Anything not listed
# as friend or enemy is neutral.
_FRIENDS = {
    "Sun": ("Moon", "Mars", "Jupiter"),
    "Moon": ("Sun", "Mercury"),
    "Mars": ("Sun", "Moon", "Jupiter"),
    "Mercury": ("Sun", "Venus"),
    "Jupiter": ("Sun", "Moon", "Mars"),
    "Venus": ("Mercury", "Saturn"),
    "Saturn": ("Mercury", "Venus"),
}
_ENEMIES = {
    "Sun": ("Venus", "Saturn"),
    "Moon": (),
    "Mars": ("Mercury",),
    "Mercury": ("Moon",),
    "Jupiter": ("Mercury", "Venus"),
    "Venus": ("Sun", "Moon"),
    "Saturn": ("Sun", "Moon", "Mars"),
}

GOCHARA_GOOD_SCORE = 40

# Houses (counted from the rasi) in which a graha's transit is taken as good.
_GOCHARA_GOOD_HOUSES = {
    "Sun": (3, 6, 10, 11),
    "Moon": (1, 3, 6, 7, 10, 11),
    "Mars": (3, 6, 11),
    "Mercury": (2, 4, 6, 8, 10, 11),
    "Jupiter": (2, 5, 7, 9, 11),
    "Venus": (1, 2, 3, 4, 5, 8, 9, 11, 12),
    "Saturn": (3, 6, 11),
}


def hora_lord(weekday: int, hora: int) -> str:
    """Lord of ``hora`` (1..24) on ``weekday`` (Sunday=0)."""
    start = HORA_SEQUENCE.index(WEEKDAY_LORD[weekday])
    return HORA_SEQUENCE[(start + hora - 1) % 7]


def rasi_lord(rasi: int) -> str:
    return RASI_LORD[rasi - 1]


def house_from_rasi(rasi: int, longitude: float) -> int:
    """House 1..12 that sidereal ``longitude`` falls in, counted from ``rasi``."""
    return (int(longitude // 30) - (rasi - 1)) % 12 + 1


def _friendship(rasi_lord_name: str, lord: str) -> int:
    if lord == rasi_lord_name:
        return FRIENDSHIP_OWN
    if lord in _FRIENDS[rasi_lord_name]:
        return FRIENDSHIP_FRIEND
    if lord in _ENEMIES[rasi_lord_name]:
        return FRIENDSHIP_ENEMY
    return FRIENDSHIP_NEUTRAL


def score_hora(
    rasi: int, lord: str, lord_longitude: float, own_lord_floor: int = 60
) -> dict[str, int]:
    """Score one hora for ``rasi``.

    Returns ``nature``, ``friendship``, ``gochara`` (the raw parts) and
    ``total``. When ``lord`` rules ``rasi`` the total is raised to
    ``own_lord_floor`` if the parts sum to less; the parts are never altered.
    """
    nature = NATURE[lord]
    friendship = _friendship(rasi_lord(rasi), lord)
    house = house_from_rasi(rasi, lord_longitude)
    gochara = GOCHARA_GOOD_SCORE if house in _GOCHARA_GOOD_HOUSES[lord] else 0
    total = nature + friendship + gochara
    if lord == rasi_lord(rasi) and total < own_lord_floor:
        total = own_lord_floor
    return {"nature": nature, "friendship": friendship, "gochara": gochara, "total": total}


def hora_table(
    rasi: int,
    weekday: int,
    lord_longitudes: tuple[float, ...],
    own_lord_floor: int = 60,
    breakdown: bool = False,
) -> list[dict[str, int | str]]:
    """The 24 horas of a day scored for ``rasi``.

    ``lord_longitudes[i]`` is the sidereal longitude of hora ``i + 1``'s lord at
    that hora's start. Rows carry ``hora``, ``lord`` and ``score``; with
    ``breakdown`` they also carry ``nature``, ``friendship`` and ``gochara``.
    """
    if not 1 <= rasi <= 12:
        raise ValueError(f"rasi must be 1..12, got {rasi}")
    if not 0 <= weekday <= 6:
        raise ValueError(f"weekday must be 0..6 (Sunday=0), got {weekday}")
    if len(lord_longitudes) != HORAS_PER_DAY:
        raise ValueError(f"need {HORAS_PER_DAY} longitudes, got {len(lord_longitudes)}")
    rows: list[dict[str, int | str]] = []
    for hora in range(1, HORAS_PER_DAY + 1):
        lord = hora_lord(weekday, hora)
        s = score_hora(rasi, lord, lord_longitudes[hora - 1], own_lord_floor)
        row: dict[str, int | str] = {"hora": hora, "lord": lord, "score": s["total"]}
        if breakdown:
            row["nature"] = s["nature"]
            row["friendship"] = s["friendship"]
            row["gochara"] = s["gochara"]
        rows.append(row)
    return rows
