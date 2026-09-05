"""Tests for the Swiss Ephemeris adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from panchangam import ephemeris
from panchangam.ephemeris import Ayanamsa, NaiveDatetimeError

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
