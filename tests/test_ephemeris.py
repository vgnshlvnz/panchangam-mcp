"""Tests for the Swiss Ephemeris adapter."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from panchangam import ephemeris
from panchangam.ephemeris import (
    Ayanamsa,
    CircumpolarError,
    Graha,
    NaiveDatetimeError,
)
from panchangam.types import Place

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def fixture_place(fx):
    return Place(**fx["place"])

# 2000-01-01 12:00 UT -- J2000, a conventional reference instant.
J2000 = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)

KL_TZ = timezone(timedelta(hours=8))
# 2026-09-06 morning in Kuala Lumpur. Per drikpanchang.com (Lahiri) this
# instant is: Sun in Simha, Moon in Mithuna, Krishna Dashami, Ardra nakshatra.
KL_MORNING = datetime(2026, 9, 6, 6, 0, tzinfo=KL_TZ)


def test_ayanamsa_lahiri_known_value():
    # Lahiri ayanamsa at J2000 is ~23.857 deg (Swiss Ephemeris / Chitrapaksha).
    assert ephemeris.ayanamsa_degrees(J2000, Ayanamsa.LAHIRI) == pytest.approx(
        23.8571, abs=1e-3
    )


def test_lahiri_and_raman_differ_by_expected_amount():
    lahiri = ephemeris.ayanamsa_degrees(J2000, Ayanamsa.LAHIRI)
    raman = ephemeris.ayanamsa_degrees(J2000, Ayanamsa.RAMAN)
    # The two initial epochs differ by ~1.4463 deg; both precess at the same
    # rate, so the gap is essentially constant across the modern era.
    assert lahiri - raman == pytest.approx(1.4463, abs=5e-3)


def test_default_ayanamsa_is_lahiri():
    ephemeris.configure()  # reset any override from earlier tests
    assert ephemeris.ayanamsa_degrees(J2000) == pytest.approx(
        ephemeris.ayanamsa_degrees(J2000, Ayanamsa.LAHIRI), abs=1e-9
    )


def test_naive_datetime_is_rejected():
    naive = datetime(2000, 1, 1, 12, 0)
    with pytest.raises(NaiveDatetimeError):
        ephemeris.ayanamsa_degrees(naive)


# --- sidereal longitudes ---------------------------------------------------


def test_sun_longitude_in_simha():
    lon = ephemeris.sun_longitude(KL_MORNING)
    assert 120.0 <= lon < 150.0  # Simha (Leo)


def test_moon_longitude_in_mithuna():
    lon = ephemeris.moon_longitude(KL_MORNING)
    assert 60.0 <= lon < 90.0  # Mithuna (Gemini)


def test_sun_and_moon_longitude_values():
    ephemeris.configure(Ayanamsa.LAHIRI)
    # Values cross-checked against drikpanchang.com for this instant.
    assert ephemeris.sun_longitude(KL_MORNING) == pytest.approx(139.12, abs=0.05)
    assert ephemeris.moon_longitude(KL_MORNING) == pytest.approx(70.23, abs=0.05)


@pytest.mark.parametrize("fn", [ephemeris.sun_longitude, ephemeris.moon_longitude])
def test_longitude_rejects_naive_datetime(fn):
    with pytest.raises(NaiveDatetimeError):
        fn(datetime(2026, 9, 6, 6, 0))


# --- graha longitudes (all nine) ----------------------------------------

GRAHAS_FX = load_fixture("drikpanchang_kuala_lumpur_2026-09-06.json")["grahas"]
GRAHAS_AT = datetime.fromisoformat(GRAHAS_FX["at"])


@pytest.mark.parametrize("name,expected", GRAHAS_FX["longitude_deg"].items())
def test_graha_longitude_matches_drikpanchang(name, expected):
    ephemeris.configure(Ayanamsa.LAHIRI)
    got = ephemeris.graha_longitude(Graha[name], GRAHAS_AT)
    assert got == pytest.approx(expected, abs=0.02)


def test_ketu_is_opposite_rahu():
    rahu = ephemeris.graha_longitude(Graha.RAHU, GRAHAS_AT)
    ketu = ephemeris.graha_longitude(Graha.KETU, GRAHAS_AT)
    assert (ketu - rahu) % 360.0 == pytest.approx(180.0)


def test_sun_moon_wrappers_delegate_to_graha_longitude():
    assert ephemeris.sun_longitude(KL_MORNING) == ephemeris.graha_longitude(
        Graha.SUN, KL_MORNING
    )
    assert ephemeris.moon_longitude(KL_MORNING) == ephemeris.graha_longitude(
        Graha.MOON, KL_MORNING
    )


def test_graha_longitude_rejects_naive_datetime():
    with pytest.raises(NaiveDatetimeError):
        ephemeris.graha_longitude(Graha.MARS, datetime(2026, 9, 6, 6, 0))


# --- retrograde / speed ------------------------------------------------

_RETRO = set(GRAHAS_FX["retrograde"])


@pytest.mark.parametrize("name", [g.name for g in Graha])
def test_is_retrograde_matches_drikpanchang(name):
    ephemeris.configure(Ayanamsa.LAHIRI)
    assert ephemeris.is_retrograde(Graha[name], GRAHAS_AT) is (name in _RETRO)


def test_speed_sign_agrees_with_retrograde_flag():
    for g in Graha:
        speed = ephemeris.graha_speed(g, GRAHAS_AT)
        assert (speed < 0) == (g.name in _RETRO)


def test_sun_and_moon_never_retrograde():
    # Sample a year; both always advance.
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for days in range(0, 365, 5):
        when = base + timedelta(days=days)
        assert ephemeris.graha_speed(Graha.SUN, when) > 0
        assert ephemeris.graha_speed(Graha.MOON, when) > 0


def test_ketu_speed_equals_rahu_speed():
    assert ephemeris.graha_speed(Graha.KETU, GRAHAS_AT) == ephemeris.graha_speed(
        Graha.RAHU, GRAHAS_AT
    )


# --- find_crossing: synthetic monotonic functions -------------------------

EPOCH = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def _hours(t):
    return (t - EPOCH).total_seconds() / 3600.0


def test_find_crossing_linear_no_wrap():
    # 15 deg/hour, like sidereal rotation. Crosses 90 deg at EPOCH + 6h.
    hit = ephemeris.find_crossing(
        lambda t: _hours(t) * 15.0, 90.0, EPOCH, EPOCH + timedelta(hours=8)
    )
    assert abs(hit - (EPOCH + timedelta(hours=6))) <= timedelta(seconds=1)


def test_find_crossing_handles_360_wrap():
    # Angle runs 350 -> 360/0 -> 10 over two hours; target 0 is hit at +1h.
    fn = lambda t: (350.0 + _hours(t) * 10.0) % 360.0
    hit = ephemeris.find_crossing(fn, 0.0, EPOCH, EPOCH + timedelta(hours=2))
    assert abs(hit - (EPOCH + timedelta(hours=1))) <= timedelta(seconds=1)


def test_find_crossing_tolerance_is_respected():
    fn = lambda t: _hours(t) * 15.0
    hit = ephemeris.find_crossing(
        fn, 90.0, EPOCH, EPOCH + timedelta(hours=8),
        tolerance=timedelta(milliseconds=10),
    )
    assert abs(hit - (EPOCH + timedelta(hours=6))) <= timedelta(milliseconds=10)


def test_find_crossing_target_outside_arc_raises():
    # fn sweeps 0 -> 12 deg; target 200 is nowhere on that arc.
    with pytest.raises(ValueError):
        ephemeris.find_crossing(
            lambda t: _hours(t) * 1.0, 200.0, EPOCH, EPOCH + timedelta(hours=12)
        )


def test_find_crossing_decreasing_fn_raises():
    with pytest.raises(ValueError):
        ephemeris.find_crossing(
            lambda t: 100.0 - _hours(t), 95.0, EPOCH, EPOCH + timedelta(hours=12)
        )


def test_find_crossing_rejects_naive_bracket():
    with pytest.raises(NaiveDatetimeError):
        ephemeris.find_crossing(
            lambda t: 0.0, 0.0,
            datetime(2026, 1, 1), datetime(2026, 1, 2),
        )


# --- find_crossing against a real anga boundary --------------------------

BOUNDARY_TOLERANCE = timedelta(minutes=2)


def test_find_crossing_locates_real_tithi_boundary():
    fx = load_fixture("drikpanchang_kuala_lumpur_2026-09-06.json")
    expected = datetime.fromisoformat(fx["tithi"]["ends_at"])
    day = expected.replace(hour=0, minute=0, second=0)

    def elongation(t):
        return (ephemeris.moon_longitude(t) - ephemeris.sun_longitude(t)) % 360.0

    hit = ephemeris.find_crossing(
        elongation, fx["tithi"]["elongation_deg"],
        day + timedelta(hours=18), day + timedelta(hours=23),
    )
    assert hit.utcoffset() == expected.utcoffset()  # stays in local zone
    assert abs(hit - expected) <= BOUNDARY_TOLERANCE


def test_find_crossing_locates_real_nakshatra_boundary():
    fx = load_fixture("drikpanchang_kuala_lumpur_2026-09-06.json")
    expected = datetime.fromisoformat(fx["nakshatra"]["ends_at"])
    day = expected.replace(hour=0, minute=0, second=0)

    hit = ephemeris.find_crossing(
        ephemeris.moon_longitude, fx["nakshatra"]["moon_longitude_deg"],
        day + timedelta(hours=18), day + timedelta(hours=23, minutes=30),
    )
    assert abs(hit - expected) <= BOUNDARY_TOLERANCE


# --- sunrise / sunset ----------------------------------------------------

SUN_EVENT_TOLERANCE = timedelta(seconds=60)
KL_FIXTURE = "drikpanchang_kuala_lumpur_2026-09-06.json"


def test_sunrise_matches_drikpanchang():
    fx = load_fixture(KL_FIXTURE)
    got = ephemeris.sunrise(date(2026, 9, 6), fixture_place(fx))
    expected = datetime.fromisoformat(fx["sunrise"])
    assert abs(got - expected) <= SUN_EVENT_TOLERANCE


def test_sunset_matches_drikpanchang():
    fx = load_fixture(KL_FIXTURE)
    got = ephemeris.sunset(date(2026, 9, 6), fixture_place(fx))
    expected = datetime.fromisoformat(fx["sunset"])
    assert abs(got - expected) <= SUN_EVENT_TOLERANCE


def test_day_length_matches_drikpanchang():
    # Sunrise/sunset print to the minute, but dinamana is given to the second.
    fx = load_fixture(KL_FIXTURE)
    place = fixture_place(fx)
    day = date(2026, 9, 6)
    span = ephemeris.sunset(day, place) - ephemeris.sunrise(day, place)
    assert abs(span.total_seconds() - fx["day_length_seconds"]) <= 60


def test_sun_event_is_tz_aware_in_place_zone():
    place = fixture_place(load_fixture(KL_FIXTURE))
    got = ephemeris.sunrise(date(2026, 9, 6), place)
    assert got.tzinfo is not None
    assert got.utcoffset() == timedelta(hours=8)


def test_sunrise_raises_in_polar_night():
    svalbard = Place(
        name="Longyearbyen",
        latitude=78.22,
        longitude=15.65,
        timezone="Arctic/Longyearbyen",
    )
    with pytest.raises(CircumpolarError):
        ephemeris.sunrise(date(2026, 12, 21), svalbard)
