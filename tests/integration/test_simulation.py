"""Simulated devices shipped with the plugin, acquired through TANGO."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

tango_test_context = pytest.importorskip("tango.test_context")

from datalab_tango import simulation  # noqa: E402
from datalab_tango.instrument import TangoInstrument  # noqa: E402


@pytest.fixture(name="profiles", scope="module")
def fixture_profiles(tmp_path_factory):
    """Profiles of the simulated devices, served in another process."""
    devices = (
        {
            "class": simulation.SimulatedOscilloscope,
            "devices": [{"name": simulation.SCOPE_NAME}],
        },
        {
            "class": simulation.SimulatedCamera,
            "devices": [{"name": simulation.CAMERA_NAME}],
        },
    )
    with tango_test_context.MultiDeviceTestContext(devices, process=True) as context:
        yield simulation.write_profiles(
            tmp_path_factory.mktemp("profiles"),
            context.get_device_access(simulation.SCOPE_NAME),
            context.get_device_access(simulation.CAMERA_NAME),
        )


def _instrument(profile: Path, **settings) -> TangoInstrument:
    instrument = TangoInstrument()
    instrument.settings.profile = str(profile)
    for name, value in settings.items():
        setattr(instrument.settings, name, value)
    instrument.open()
    return instrument


def test_free_running_oscilloscope(profiles: list[Path]) -> None:
    """A series of traces follows the free-running acquisitions, calibrated in ns."""
    instrument = _instrument(profiles[0], mode="series", count=3, timeout=10.0)
    try:
        signals = instrument.acquire().objects
        assert len(signals) == 3
        assert signals[0].xunit == "ns" and signals[0].yunit == "V"
        assert np.allclose(np.diff(signals[0].x), signals[0].x[1] - signals[0].x[0])
        assert not np.array_equal(signals[0].y, signals[1].y)
    finally:
        instrument.close()


def test_triggered_camera_frame(profiles: list[Path]) -> None:
    """A triggered frame is acquired from the simulated camera."""
    instrument = _instrument(profiles[1], mode="trigger")
    try:
        (image,) = instrument.acquire().objects
        assert image.data.shape == simulation.CAMERA_SHAPE
        assert image.zunit == "DN"
    finally:
        instrument.close()
