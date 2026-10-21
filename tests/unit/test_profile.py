"""Device profiles: validation and user-facing errors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datalab_tango.core import (
    AttributeKind,
    Reception,
    load_profile,
    profile_from_dict,
)

EXAMPLE = (
    Path(__file__).parents[2]
    / "src"
    / "datalab_tango"
    / "profiles"
    / "example_camera.json"
)


def _profile(**changes) -> dict:
    """Return a valid profile, with changed fields."""
    data = {
        "version": 1,
        "name": "Bench",
        "device": "lab/cam/1",
        "attributes": [{"name": "frame", "kind": "image"}],
    }
    data.update(changes)
    return data


def test_example_profile() -> None:
    """The packaged example profile is valid."""
    profile = load_profile(EXAMPLE)
    assert profile.reception is Reception.POLLING
    frame = profile.get_attribute()
    assert frame.kind is AttributeKind.IMAGE
    assert (frame.x.step, frame.x.unit) == (6.5, "µm")
    assert profile.get_attribute("profile").kind is AttributeKind.SIGNAL
    assert profile.trigger.command == "Snap"


def test_defaults() -> None:
    """Optional fields have documented defaults."""
    profile = profile_from_dict(_profile())
    assert profile.trigger is None
    assert (profile.polling_interval_ms, profile.timeout_ms) == (200, 3000)
    assert profile.buffer_size == 16
    attribute = profile.get_attribute("frame")
    assert (attribute.x.origin, attribute.x.step) == (0.0, 1.0)
    with pytest.raises(ValueError, match="no attribute 'counts'"):
        profile.get_attribute("counts")


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"version": 2}, "'version' must be 1"),
        ({"device": ""}, "'device' must be a non-empty string"),
        ({"attributes": []}, "'attributes' must be a non-empty list"),
        ({"attributes": [{"name": "a", "kind": "scalar"}]}, "'kind' must be"),
        ({"attributes": [{"name": "a", "kind": "signal", "y": {}}]}, "no 'y'"),
        ({"attributes": [{"name": "a", "kind": "image", "x": {"step": 0}}]}, "zero"),
        ({"reception": "push"}, "'reception' must be"),
        ({"buffer_size": 0}, "'buffer_size' must be a positive integer"),
        ({"trigger": {"command": "Snap", "argument": [1]}}, "JSON scalar"),
        ({"extra": 1}, "unknown fields"),
        (
            {"attributes": [{"name": "a", "kind": "image"}] * 2},
            "names must be unique",
        ),
    ],
)
def test_invalid_profiles(changes: dict, message: str) -> None:
    """Invalid profiles are refused with a message telling what to fix."""
    with pytest.raises(ValueError, match=message):
        profile_from_dict(_profile(**changes))


def test_unreadable_file(tmp_path: Path) -> None:
    """Missing or malformed files are reported, not raised as raw errors."""
    with pytest.raises(ValueError, match="Cannot read profile"):
        load_profile(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_profile(broken)
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_profile()), encoding="utf-8")
    assert load_profile(valid).name == "Bench"
