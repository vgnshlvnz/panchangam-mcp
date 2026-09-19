"""Personal muhurta engine: rules from CLAUDE.md and reuse of the ephemeris."""

from __future__ import annotations

from datetime import date

from panchangam import ephemeris
from panchangam.personal.muhurta import TARAS, Person, chandra_of, compute_day, tara_of
from panchangam.types import Place

PJ = Place("Petaling Jaya", 3.1073, 101.6067, "Asia/Kuala_Lumpur")


def test_tara_good_bad_mixed_counts():
    # janma Rohini (4): day stars counted from it, mod 9
    verdicts = {}
    for nak in range(4, 13):
        verdicts[tara_of(4, nak)] = TARAS[tara_of(4, nak)][2]
    assert [k for k, v in verdicts.items() if v == "good"] == [2, 4, 6, 8, 9]
    assert [k for k, v in verdicts.items() if v == "bad"] == [3, 5, 7]
    assert verdicts[1] == "mixed"


def test_chandrabala_houses():
    assert chandra_of(2, 2, True) == (1, "good")
    assert chandra_of(2, 9, True) == (8, "chandrashtama")
    assert chandra_of(2, 4, True) == (3, "good")
    assert chandra_of(2, 3, True) == (2, "good")
    assert chandra_of(2, 3, False) == (2, "neutral")
    assert chandra_of(2, 5, True) == (4, "weak")


def test_day_runs_from_ephemeris_sunrise_upper_limb():
    r = compute_day(Person("T", 4, 2), PJ, date(2026, 9, 24))
    expected = ephemeris.sunrise(date(2026, 9, 24), PJ).replace(second=0, microsecond=0)
    assert r.sunrise == expected
    assert r.moon[0].start == r.sunrise
    assert r.lagnas[0].start == r.sunrise


def test_compute_day_restores_default_ayanamsa():
    compute_day(Person("T", 4, 2), PJ, date(2026, 9, 24), ayanamsa="raman")
    lahiri = ephemeris.moon_longitude(ephemeris.sunrise(date(2026, 9, 24), PJ))
    ephemeris.configure(ephemeris.Ayanamsa.LAHIRI)
    assert lahiri == ephemeris.moon_longitude(ephemeris.sunrise(date(2026, 9, 24), PJ))
