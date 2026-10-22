"""TANGO instrument with a simulated device served by PyTango.

The device runs in another process and is reached through the TANGO protocol,
as a real device would be. Values are received by periodic reads: change events
depend on the network setup of the test machine.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from sigima.objects import get_experimental_source
from support import SERVER_STARTUP_TIMEOUT

tango_test_context = pytest.importorskip("tango.test_context")

from datalab_tango.instrument import TangoInstrument  # noqa: E402


@pytest.fixture(name="camera", scope="module")
def fixture_camera():
    """Simulated camera device, with its TANGO address."""
    from support.devices import (
        SimulatedCamera,  # pylint: disable=import-outside-toplevel
    )

    with tango_test_context.DeviceTestContext(
        SimulatedCamera, process=True, timeout=SERVER_STARTUP_TIMEOUT
    ) as proxy:
        yield proxy.dev_name()


def _profile(path: Path, address: str, trigger: dict | None = None) -> str:
    """Write the profile of the simulated camera."""
    data = {
        "version": 1,
        "name": "Simulated camera",
        "device": address,
        "attributes": [
            {"name": "frame", "kind": "image", "unit": "counts"},
            {"name": "spectrum", "kind": "signal"},
        ],
        "trigger": trigger or {"command": "Snap"},
        "polling_interval_ms": 20,
        "timeout_ms": 3000,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_acquisition_from_device(tmp_path: Path, camera: str) -> None:
    """Preview, triggered acquisition and series through the TANGO protocol."""
    instrument = TangoInstrument()
    instrument.settings.profile = _profile(tmp_path / "camera.json", camera)
    instrument.open()
    try:
        image = instrument.preview().objects[0]
        assert image.data[0, 0] == 2**32 - 1
        shots = int(image.data[1, 1])

        instrument.settings.mode = "trigger"
        (image,) = instrument.acquire().objects
        assert image.data[1, 1] == shots + 1

        instrument.settings.attribute = "spectrum"
        instrument.settings.mode = "latest"
        (signal,) = instrument.acquire().objects
        assert np.allclose(signal.y, np.linspace(0.0, 1.0, 5) + shots + 1)
    finally:
        instrument.close()


def test_triggered_value_identified_by_time_stamp(tmp_path: Path, camera: str) -> None:
    """A trigger command returning the time stamp of its value through the TANGO
    protocol identifies this value among the received ones."""
    trigger = {"command": "SnapTimed", "returns": "time_stamp"}
    instrument = TangoInstrument()
    instrument.settings.profile = _profile(tmp_path / "camera.json", camera, trigger)
    instrument.settings.mode = "trigger"
    instrument.open()
    try:
        shots = int(instrument.preview().objects[0].data[1, 1])
        for shot in range(shots + 1, shots + 4):
            (image,) = instrument.acquire().objects
            assert image.data[1, 1] == shot
            source = get_experimental_source(image)
            assert source["details"]["trigger"]["synchronization"] == "time_stamp"
    finally:
        instrument.close()


def test_unreachable_device(tmp_path: Path) -> None:
    """An unknown device gives a user-facing message."""
    instrument = TangoInstrument()
    instrument.settings.profile = _profile(
        tmp_path / "missing.json", "tango://127.0.0.1:1/no/such/device#dbase=no"
    )
    with pytest.raises(ValueError, match="Cannot connect to"):
        instrument.preview()
    instrument.close()
