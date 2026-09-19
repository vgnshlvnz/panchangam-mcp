"""
Personal muhurta engine.

For one date + place + person (janma nakshatra, janma rasi) it returns:
  - Moon segments of the day (nakshatra / rasi changes) with tarabala and chandrabala
  - Lagna windows (rising sign, % progressed, planets by whole-sign house)
  - Rahu kalam / Yamagandam / Gulika kalam
  - "Good windows": lagna middle portion, outside kalams, personal checks passing

Everything is computed on a 1-minute grid from sunrise to next sunrise and merged,
which keeps the logic simple and portable (easy to re-write in C for the ESP32).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import swisseph as swe

from panchangam import ephemeris
from panchangam.ephemeris import Ayanamsa, Graha
from panchangam.types import Place

# ---------------------------------------------------------------- constants
NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu",
    "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta",
    "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha",
    "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada",
    "Uttara Bhadrapada", "Revati",
]
NAKSHATRAS_TA = [
    "அசுவினி", "பரணி", "கார்த்திகை", "ரோகிணி", "மிருகசீரிடம்", "திருவாதிரை", "புனர்பூசம்",
    "பூசம்", "ஆயில்யம்", "மகம்", "பூரம்", "உத்திரம்", "அஸ்தம்", "சித்திரை", "சுவாதி",
    "விசாகம்", "அனுஷம்", "கேட்டை", "மூலம்", "பூராடம்", "உத்திராடம்", "திருவோணம்",
    "அவிட்டம்", "சதயம்", "பூரட்டாதி", "உத்திரட்டாதி", "ரேவதி",
]
RASIS = ["Mesha", "Rishabha", "Mithuna", "Kataka", "Simha", "Kanya",
         "Tula", "Vrischika", "Dhanus", "Makara", "Kumbha", "Meena"]
RASIS_TA = ["மேஷம்", "ரிஷபம்", "மிதுனம்", "கடகம்", "சிம்மம்", "கன்னி",
            "துலாம்", "விருச்சிகம்", "தனுசு", "மகரம்", "கும்பம்", "மீனம்"]

# tara index 1..9 -> (english, tamil, verdict)  verdict: good / bad / mixed
TARAS = {
    1: ("Janma", "ஜன்ம", "mixed"),
    2: ("Sampat", "சம்பத்", "good"),
    3: ("Vipat", "விபத்", "bad"),
    4: ("Kshema", "க்ஷேம", "good"),
    5: ("Pratyak", "பிரத்யக்", "bad"),
    6: ("Sadhana", "சாதக", "good"),
    7: ("Naidhana", "நைதன", "bad"),
    8: ("Mitra", "மித்ர", "good"),
    9: ("Parama Mitra", "பரம மித்ர", "good"),
}

PLANETS = {
    "Sun": Graha.SUN, "Moon": Graha.MOON, "Mars": Graha.MARS, "Mercury": Graha.MERCURY,
    "Jupiter": Graha.JUPITER, "Venus": Graha.VENUS, "Saturn": Graha.SATURN,
    "Rahu": Graha.RAHU, "Ketu": Graha.KETU,
}
MALEFICS = {"Sun", "Mars", "Saturn", "Rahu", "Ketu"}
BENEFICS = {"Jupiter", "Venus", "Mercury"}          # Moon handled by paksha
KENDRA = {1, 4, 7, 10}
TRIKONA = {1, 5, 9}

# 1-based eighth-of-daytime index, weekday Mon=0 .. Sun=6
RAHU_KALAM = {6: 8, 0: 2, 1: 7, 2: 5, 3: 6, 4: 4, 5: 3}
YAMAGANDAM = {6: 5, 0: 4, 1: 3, 2: 2, 3: 1, 4: 7, 5: 6}
GULIKA = {6: 7, 0: 6, 1: 5, 2: 4, 3: 3, 4: 2, 5: 1}


# ---------------------------------------------------------------- data classes
@dataclass
class Person:
    name: str
    janma_nakshatra: int      # 1..27
    janma_rasi: int           # 1..12


@dataclass
class Span:
    start: datetime
    end: datetime

    def overlap(self, other: Span) -> Span | None:
        s, e = max(self.start, other.start), min(self.end, other.end)
        return Span(s, e) if e > s else None


@dataclass
class MoonSegment(Span):
    nakshatra: int = 0        # 1..27
    rasi: int = 0             # 1..12
    waxing: bool = True
    tara: int = 0             # 1..9
    tara_verdict: str = ""
    chandra_house: int = 0    # 1..12
    chandra_verdict: str = ""


@dataclass
class LagnaWindow(Span):
    rasi: int = 0
    houses: dict = field(default_factory=dict)   # planet -> house from this lagna
    usable: Span | None = None                  # middle portion (not sandhi)
    ok: bool = True
    notes: list = field(default_factory=list)


@dataclass
class DayResult:
    person: Person
    place: Place
    day: date
    sunrise: datetime
    sunset: datetime
    kalams: dict
    moon: list
    lagnas: list
    good_windows: list
    chandrashtama: bool


# ---------------------------------------------------------------- helpers
def _lagna_lon(when: datetime, place: Place) -> float:
    _, ascmc = swe.houses_ex(
        ephemeris._julian_day_ut(when), place.latitude, place.longitude, b"W", swe.FLG_SIDEREAL
    )
    return ascmc[0] % 360


def tara_of(janma_nak: int, nak: int) -> int:
    count = (nak - janma_nak) % 27 + 1
    return (count - 1) % 9 + 1


def chandra_of(janma_rasi: int, rasi: int, waxing: bool) -> tuple[int, str]:
    h = (rasi - janma_rasi) % 12 + 1
    if h == 8:
        return h, "chandrashtama"
    if h in (1, 3, 6, 7, 10, 11):
        return h, "good"
    if h in (2, 5, 9):
        return h, "good" if waxing else "neutral"
    return h, "weak"                                    # 4, 12


def _kalam(sunrise: datetime, sunset: datetime, idx: int) -> Span:
    part = (sunset - sunrise) / 8
    return Span(sunrise + part * (idx - 1), sunrise + part * idx)


# ---------------------------------------------------------------- main
def compute_day(person: Person, place: Place, day: date, ayanamsa: str = "lahiri",
                sandhi_pct: float = 20.0, min_window_min: int = 20,
                show_from: int = 6, show_to: int = 22) -> DayResult:
    ephemeris.configure(Ayanamsa[ayanamsa.upper()])
    try:
        return _compute_day(person, place, day, sandhi_pct, min_window_min, show_from, show_to)
    finally:
        ephemeris.configure()       # the server's tools assume the default ayanamsa


def _minute(when: datetime) -> datetime:
    return when.replace(second=0, microsecond=0)


def _compute_day(person: Person, place: Place, day: date, sandhi_pct: float,
                 min_window_min: int, show_from: int, show_to: int) -> DayResult:
    tz = ZoneInfo(place.timezone)
    local_midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
    sunrise = _minute(ephemeris.sunrise(day, place))
    sunset = _minute(ephemeris.sunset(day, place))
    next_sunrise = _minute(ephemeris.sunrise(day + timedelta(days=1), place))

    wd = day.weekday()
    kalams = {
        "Rahu kalam": _kalam(sunrise, sunset, RAHU_KALAM[wd]),
        "Yamagandam": _kalam(sunrise, sunset, YAMAGANDAM[wd]),
        "Gulika": _kalam(sunrise, sunset, GULIKA[wd]),
    }

    # ---- 1-minute scan, sunrise -> next sunrise
    step = timedelta(minutes=1)
    moon_segs: list[MoonSegment] = []
    lag_segs: list[LagnaWindow] = []
    t = sunrise
    while t < next_sunrise:
        moon = ephemeris.moon_longitude(t)
        sun = ephemeris.sun_longitude(t)
        nak, rasi = int(moon // (360 / 27)) + 1, int(moon // 30) + 1
        waxing = (moon - sun) % 360 < 180
        if not moon_segs or (moon_segs[-1].nakshatra, moon_segs[-1].rasi) != (nak, rasi):
            if moon_segs:
                moon_segs[-1].end = t
            tr = tara_of(person.janma_nakshatra, nak)
            ch, chv = chandra_of(person.janma_rasi, rasi, waxing)
            moon_segs.append(MoonSegment(t, t, nak, rasi, waxing, tr, TARAS[tr][2], ch, chv))
        lr = int(_lagna_lon(t, place) // 30) + 1
        if not lag_segs or lag_segs[-1].rasi != lr:
            if lag_segs:
                lag_segs[-1].end = t
            lag_segs.append(LagnaWindow(t, t, lr))
        t += step
    moon_segs[-1].end = next_sunrise
    lag_segs[-1].end = next_sunrise

    # ---- evaluate each lagna window
    ashtama_lagna = (person.janma_rasi + 6) % 12 + 1   # 8th from janma rasi
    for lw in lag_segs:
        mid = lw.start + (lw.end - lw.start) / 2
        pos = {n: ephemeris.graha_longitude(g, mid) for n, g in PLANETS.items()}
        lw.houses = {n: (int(l // 30) + 1 - lw.rasi) % 12 + 1 for n, l in pos.items()}
        # partial windows at the day edges: we don't know their true %, so don't trust them
        full = lw is not lag_segs[0] and lw is not lag_segs[-1]
        if full:
            dur = lw.end - lw.start
            lw.usable = Span(lw.start + dur * sandhi_pct / 100, lw.end - dur * sandhi_pct / 100)
        else:
            lw.ok = False
            lw.notes.append("partial window")
        in8 = [p for p, h in lw.houses.items() if h == 8]
        if in8:
            lw.ok = False
            lw.notes.append(f"8th occupied: {', '.join(in8)}")
        in1 = [p for p, h in lw.houses.items() if h == 1 and p in MALEFICS]
        if in1:
            lw.ok = False
            lw.notes.append(f"malefic in lagna: {', '.join(in1)}")
        if lw.rasi == ashtama_lagna:
            lw.ok = False
            lw.notes.append("8th from janma rasi")
        good = [p for p, h in lw.houses.items()
                if p in BENEFICS and h in (KENDRA | TRIKONA)]
        if good:
            lw.notes.append(f"benefics strong: {', '.join(good)}")

    # ---- good windows = usable lagna ∩ personal-ok moon ∩ not kalam ∩ display hours
    good_windows = []
    for lw in (l for l in lag_segs if l.ok and l.usable):
        for ms in moon_segs:
            if ms.tara_verdict == "bad" or ms.chandra_verdict in ("chandrashtama", "weak"):
                continue
            span = lw.usable.overlap(ms)
            if not span:
                continue
            pieces = [span]
            for k in kalams.values():                       # subtract kalams
                nxt = []
                for p in pieces:
                    if not p.overlap(k):
                        nxt.append(p)
                        continue
                    if p.start < k.start:
                        nxt.append(Span(p.start, k.start))
                    if p.end > k.end:
                        nxt.append(Span(k.end, p.end))
                pieces = nxt
            for p in pieces:
                s = max(p.start, local_midnight.replace(hour=show_from))
                e = min(p.end, local_midnight.replace(hour=show_to))
                if (e - s) >= timedelta(minutes=min_window_min):
                    good_windows.append((Span(s, e), lw, ms))
    good_windows.sort(key=lambda g: g[0].start)

    daytime = [m for m in moon_segs if m.start < local_midnight.replace(hour=show_to)]
    chandrashtama = any(m.chandra_verdict == "chandrashtama" for m in daytime)
    return DayResult(person, place, day, sunrise, sunset, kalams, moon_segs, lag_segs,
                     good_windows, chandrashtama)


def janma_from_birth(dt_local: datetime, ayanamsa: str = "lahiri") -> tuple[int, int, int]:
    """Birth datetime (tz-aware) -> (janma_nakshatra 1..27, pada 1..4, janma_rasi 1..12)."""
    ephemeris.configure(Ayanamsa[ayanamsa.upper()])
    try:
        moon = ephemeris.moon_longitude(dt_local)
    finally:
        ephemeris.configure()
    nak_span = 360 / 27
    return int(moon // nak_span) + 1, int((moon % nak_span) // (nak_span / 4)) + 1, int(moon // 30) + 1
