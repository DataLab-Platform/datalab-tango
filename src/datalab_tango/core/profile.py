"""Device profiles: which TANGO attributes to read, and how to interpret them.

A profile is a JSON file describing one device: its address, the attributes
DataLab may show (spectra as signals, images as images) with their units and
axis calibrations, the optional command triggering a measurement, and how data
is received (periodic reads or change events). Site-specific values live in
profiles, never in the code.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import math
from pathlib import Path
from typing import Any, Union

__all__ = [
    "PROFILE_VERSION",
    "TRIGGER_RETURNS",
    "AttributeKind",
    "AttributeProfile",
    "AxisCalibration",
    "DeviceProfile",
    "Reception",
    "TriggerProfile",
    "load_profile",
    "profile_from_dict",
]

#: Version of the profile file layout
PROFILE_VERSION = 1

#: Values of the ``returns`` field of a trigger: what its command returns
TRIGGER_RETURNS = ("time_stamp",)

JsonScalar = Union[str, int, float, bool, None]


class AttributeKind(str, enum.Enum):
    """How an attribute is shown: SPECTRUM as a signal, IMAGE as an image."""

    SIGNAL = "signal"
    IMAGE = "image"


class Reception(str, enum.Enum):
    """How new attribute values are received."""

    POLLING = "polling"
    EVENTS = "events"


@dataclasses.dataclass(frozen=True)
class AxisCalibration:
    """Linear calibration of an axis: ``origin + index * step``."""

    origin: float = 0.0
    step: float = 1.0
    unit: str = ""
    label: str = ""


@dataclasses.dataclass(frozen=True)
class AttributeProfile:
    """Attribute shown and acquired by DataLab.

    Args:
        name: TANGO attribute name
        kind: signal (SPECTRUM attribute) or image (IMAGE attribute)
        label: label of the values (default: attribute name)
        unit: unit of the values
        x: calibration of the X axis (signal samples, image columns)
        y: calibration of the Y axis (image rows only)
    """

    name: str
    kind: AttributeKind
    label: str = ""
    unit: str = ""
    x: AxisCalibration = AxisCalibration()
    y: AxisCalibration = AxisCalibration()


@dataclasses.dataclass(frozen=True)
class TriggerProfile:
    """Command triggering a measurement.

    Args:
        command: TANGO command name
        argument: argument of the command, if any
        returns: ``"time_stamp"`` if the command returns the device time stamp
         (s since the epoch) of the value it measured, so that this value is
         told apart from others received meanwhile; None if it returns nothing
         useful
    """

    command: str
    argument: JsonScalar = None
    returns: str | None = None


@dataclasses.dataclass(frozen=True)
class DeviceProfile:
    """Device profile.

    Args:
        name: profile name, shown to users and recorded with acquisitions
        device: TANGO device name or full address (``tango://host:port/a/b/c``)
        attributes: attributes DataLab may show and acquire
        trigger: command triggering a measurement, if the device has one
        reception: periodic reads, or change events pushed by the device
        polling_interval_ms: interval between two reads in polling mode
        timeout_ms: timeout of device calls
        buffer_size: number of received values kept by DataLab
    """

    name: str
    device: str
    attributes: tuple[AttributeProfile, ...]
    trigger: TriggerProfile | None = None
    reception: Reception = Reception.POLLING
    polling_interval_ms: int = 200
    timeout_ms: int = 3000
    buffer_size: int = 16

    def get_attribute(self, name: str = "") -> AttributeProfile:
        """Return an attribute of the profile (default: the first one).

        Raises:
            ValueError: if the profile has no attribute with this name
        """
        if not name:
            return self.attributes[0]
        for attribute in self.attributes:
            if attribute.name == name:
                return attribute
        names = ", ".join(attribute.name for attribute in self.attributes)
        raise ValueError(
            f"Profile '{self.name}' has no attribute '{name}' (available: {names})"
        )


def _text(data: dict, key: str, where: str, default: str | None = None) -> str:
    """Return a non-empty string field, or its default."""
    value = data.get(key, default)
    if not isinstance(value, str) or (default is None and not value.strip()):
        raise ValueError(f"{where}: '{key}' must be a non-empty string")
    return value


def _number(data: dict, key: str, where: str, default: float) -> float:
    """Return a finite number field, or its default."""
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}: '{key}' must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{where}: '{key}' must be finite")
    return float(value)


def _positive_int(data: dict, key: str, where: str, default: int) -> int:
    """Return a positive integer field, or its default."""
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{where}: '{key}' must be a positive integer")
    return value


def _check_keys(data: Any, allowed: set[str], where: str) -> None:
    """Raise if data is not a dictionary with known keys only."""
    if not isinstance(data, dict):
        raise ValueError(f"{where} must be a JSON object")
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{where}: unknown fields {unknown}")


def _axis(data: Any, where: str) -> AxisCalibration:
    """Return an axis calibration."""
    _check_keys(data, {"origin", "step", "unit", "label"}, where)
    step = _number(data, "step", where, 1.0)
    if step == 0.0:
        raise ValueError(f"{where}: 'step' must not be zero")
    return AxisCalibration(
        origin=_number(data, "origin", where, 0.0),
        step=step,
        unit=_text(data, "unit", where, ""),
        label=_text(data, "label", where, ""),
    )


def _attribute(data: Any, index: int) -> AttributeProfile:
    """Return an attribute profile."""
    where = f"attributes[{index}]"
    _check_keys(data, {"name", "kind", "label", "unit", "x", "y"}, where)
    try:
        kind = AttributeKind(data.get("kind"))
    except ValueError as exc:
        raise ValueError(f"{where}: 'kind' must be 'signal' or 'image'") from exc
    if kind is AttributeKind.SIGNAL and "y" in data:
        raise ValueError(f"{where}: a signal has no 'y' calibration")
    return AttributeProfile(
        name=_text(data, "name", where),
        kind=kind,
        label=_text(data, "label", where, ""),
        unit=_text(data, "unit", where, ""),
        x=_axis(data.get("x", {}), f"{where}.x"),
        y=_axis(data.get("y", {}), f"{where}.y"),
    )


def profile_from_dict(data: Any) -> DeviceProfile:
    """Return a validated device profile.

    Args:
        data: profile, as read from its JSON file

    Raises:
        ValueError: with a user-facing message if the profile is invalid
    """
    allowed = {
        "version",
        "name",
        "device",
        "attributes",
        "trigger",
        "reception",
        "polling_interval_ms",
        "timeout_ms",
        "buffer_size",
    }
    _check_keys(data, allowed, "Profile")
    if data.get("version") != PROFILE_VERSION:
        raise ValueError(f"Profile: 'version' must be {PROFILE_VERSION}")
    attributes = data.get("attributes")
    if not isinstance(attributes, list) or not attributes:
        raise ValueError("Profile: 'attributes' must be a non-empty list")
    parsed = tuple(_attribute(item, index) for index, item in enumerate(attributes))
    names = [attribute.name for attribute in parsed]
    if len(set(names)) != len(names):
        raise ValueError("Profile: attribute names must be unique")
    trigger = None
    if data.get("trigger") is not None:
        _check_keys(data["trigger"], {"command", "argument", "returns"}, "trigger")
        argument = data["trigger"].get("argument")
        if isinstance(argument, (dict, list)):
            raise ValueError("trigger: 'argument' must be a JSON scalar")
        returns = data["trigger"].get("returns")
        if returns is not None and returns not in TRIGGER_RETURNS:
            choices = ", ".join(f"'{value}'" for value in TRIGGER_RETURNS)
            raise ValueError(f"trigger: 'returns' must be {choices} or absent")
        trigger = TriggerProfile(
            _text(data["trigger"], "command", "trigger"), argument, returns
        )
    try:
        reception = Reception(data.get("reception", Reception.POLLING.value))
    except ValueError as exc:
        raise ValueError("Profile: 'reception' must be 'polling' or 'events'") from exc
    return DeviceProfile(
        name=_text(data, "name", "Profile"),
        device=_text(data, "device", "Profile"),
        attributes=parsed,
        trigger=trigger,
        reception=reception,
        polling_interval_ms=_positive_int(data, "polling_interval_ms", "Profile", 200),
        timeout_ms=_positive_int(data, "timeout_ms", "Profile", 3000),
        buffer_size=_positive_int(data, "buffer_size", "Profile", 16),
    )


def load_profile(path: str | Path) -> DeviceProfile:
    """Read and validate a device profile file.

    Raises:
        ValueError: with a user-facing message if the file cannot be used
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Cannot read profile '{path}': {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Profile '{path}' is not valid JSON: {exc}") from exc
    return profile_from_dict(data)
