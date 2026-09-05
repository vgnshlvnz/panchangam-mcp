"""Tests for the Swiss Ephemeris adapter."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from panchangam import ephemeris
from panchangam.ephemeris import Ayanamsa, NaiveDatetimeError

# 2000-01-01 12:00 UT -- J2000, a conventional reference instant.
J2000 = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)


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
