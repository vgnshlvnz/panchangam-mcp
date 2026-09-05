"""Tests for the Swiss Ephemeris adapter."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from panchangam import ephemeris
from panchangam.ephemeris import Ayanamsa, NaiveDatetimeError

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())

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
