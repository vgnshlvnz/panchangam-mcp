"""Reads the hora settings from ``~/.config/panchangam/profiles.yaml``.

This is the only hora module that touches the filesystem; the engine receives
plain values from here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROFILES_PATH = Path.home() / ".config" / "panchangam" / "profiles.yaml"
DEFAULT_OWN_LORD_FLOOR = 60


def load_profiles(path: Path = PROFILES_PATH) -> dict[str, Any]:
    """The parsed profiles file, or ``{}`` if it does not exist."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def own_lord_floor_from(profiles: dict[str, Any]) -> int:
    """``settings.hora.own_lord_floor`` (an int 0..100), default 60."""
    settings = profiles.get("settings") or {}
    hora = settings.get("hora") or {}
    value = hora.get("own_lord_floor", DEFAULT_OWN_LORD_FLOOR)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError(
            f"settings.hora.own_lord_floor must be an integer 0..100, got {value!r}"
        )
    return value
