"""Fake device connections, for tests without a TANGO device."""

from __future__ import annotations

import itertools
import json
import threading
from pathlib import Path

import numpy as np

from datalab_tango.core import DeviceBackend, Reading


def write_profile(path: Path, **changes) -> str:
    """Write a profile of the fake device and return its file name."""
    data = {
        "version": 1,
        "name": "Bench camera",
        "device": "lab/cam/1",
        "attributes": [
            {
                "name": "frame",
                "kind": "image",
                "unit": "counts",
                "x": {"origin": 1.0, "step": 0.5, "unit": "mm"},
            },
            {"name": "spectrum", "kind": "signal", "x": {"step": 2.0, "unit": "eV"}},
        ],
        "trigger": {"command": "Snap"},
        "polling_interval_ms": 5,
        "buffer_size": 8,
    }
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class FakeDevice:
    """Device whose ``frame`` (image) and ``spectrum`` attributes change at each
    ``step``, e.g. when its ``Snap`` command runs."""

    def __init__(self, dtype=np.uint16) -> None:
        self.dtype = dtype
        self.counter = 0
        self.time = 1_000_000.0
        self.connections = 0
        self.unreachable = False
        self.subscriptions: dict[int, tuple[str, object]] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def value(self, attribute: str) -> np.ndarray:
        """Return the current value of an attribute."""
        if attribute == "frame":
            return np.full((3, 4), self.counter, dtype=self.dtype)
        if attribute == "spectrum":
            return np.arange(5, dtype=np.int32) + self.counter
        raise ValueError(f"No attribute '{attribute}'")

    def step(self, value: int | None = None) -> None:
        """Change the values and push them to subscribers."""
        with self._lock:
            self.counter = self.counter + 1 if value is None else value
            self.time += 1.0
            subscriptions = list(self.subscriptions.values())
        for attribute, callback in subscriptions:
            callback(Reading.create(self.value(attribute), self.time))


class FakeBackend(DeviceBackend):
    """Connection to a :class:`FakeDevice`."""

    def __init__(self, device: FakeDevice) -> None:
        self.device = device

    def connect(self, device: str, timeout_ms: int) -> None:
        if self.device.unreachable:
            raise ValueError(f"Cannot connect to '{device}': unreachable")
        self.device.connections += 1

    def read(self, attribute: str) -> Reading:
        return Reading.create(self.device.value(attribute), self.device.time)

    def subscribe(self, attribute: str, callback) -> object:
        handle = next(self.device._ids)  # pylint: disable=protected-access
        self.device.subscriptions[handle] = (attribute, callback)
        callback(self.read(attribute))
        return handle

    def unsubscribe(self, handle: object) -> None:
        del self.device.subscriptions[handle]

    def command(self, name: str, argument=None) -> object:
        if name != "Snap":
            raise ValueError(f"Command '{name}' failed: unknown command")
        self.device.step()
        return None

    def disconnect(self) -> None:
        self.device.connections -= 1
