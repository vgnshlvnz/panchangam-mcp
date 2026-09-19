"""settings.hora handling. File reading is not tested here: it needs a YAML
parser, which is not a dependency yet (awaiting approval)."""

from __future__ import annotations

import pytest

from panchangam.hora.settings import own_lord_floor_from


def test_default_is_60_when_absent():
    assert own_lord_floor_from({}) == 60
    assert own_lord_floor_from({"settings": {}}) == 60
    assert own_lord_floor_from({"settings": {"hora": {}}}) == 60


def test_reads_settings_hora_own_lord_floor():
    assert own_lord_floor_from({"settings": {"hora": {"own_lord_floor": 75}}}) == 75


@pytest.mark.parametrize("bad", [-1, 101, "60", 60.5, True])
def test_rejects_out_of_range_or_non_int(bad):
    with pytest.raises(ValueError, match="own_lord_floor"):
        own_lord_floor_from({"settings": {"hora": {"own_lord_floor": bad}}})


def test_load_profiles_reads_yaml_and_missing_file_is_empty(tmp_path):
    from panchangam.hora.settings import load_profiles

    assert load_profiles(tmp_path / "nope.yaml") == {}
    f = tmp_path / "profiles.yaml"
    f.write_text("settings:\n  hora:\n    own_lord_floor: 70\n")
    assert own_lord_floor_from(load_profiles(f)) == 70
    f.write_text("- not\n- a mapping\n")
    assert load_profiles(f) == {}
