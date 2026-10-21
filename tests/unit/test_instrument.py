"""TANGO instrument: preview, acquisition modes, losses and connection life cycle."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest
from sigima.objects import ImageObj, SignalObj, get_experimental_source
from support.fake_backend import FakeBackend, FakeDevice
from support.fake_backend import write_profile as _write_profile

from datalab_tango.instrument import TangoInstrument


@pytest.fixture(name="device")
def fixture_device() -> FakeDevice:
    """Fake device."""
    return FakeDevice()


def _instrument(device: FakeDevice, profile: str, **settings) -> TangoInstrument:
    """Return a TANGO instrument connected to the fake device by DataLab."""
    instrument = TangoInstrument(lambda: FakeBackend(device))
    instrument.settings.profile = profile
    for name, value in settings.items():
        setattr(instrument.settings, name, value)
    instrument.open()
    return instrument


def test_preview_and_latest_acquisition(tmp_path: Path, device: FakeDevice) -> None:
    """Values are calibrated, copied, and record their origin."""
    instrument = _instrument(device, _write_profile(tmp_path / "p.json"))
    try:
        frame = instrument.preview()
        image = frame.objects[0]
        assert isinstance(image, ImageObj)
        assert (image.x0, image.dx, image.xunit, image.zunit) == (
            1.0,
            0.5,
            "mm",
            "counts",
        )
        assert "Bench camera - frame" in frame.summary
        device.step(7)
        acquisition = None
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            acquisition = instrument.acquire()
            if acquisition.objects[0].data[0, 0] == 7:
                break
        image = acquisition.objects[0]
        assert image.data[0, 0] == 7
        assert acquisition.group_title.startswith("Bench camera - frame - acquisition")
        source = get_experimental_source(image)
        assert (source["kind"], source["location"], source["entry"]) == (
            "tango",
            "lab/cam/1",
            "frame",
        )
        assert source["details"]["profile"] == "Bench camera"
        assert source["details"]["quality"] == "ATTR_VALID"
        assert set(source["timestamps"]) == {"source", "reception"}
        device.step(8)
        assert image.data[0, 0] == 7, "Acquired objects must not follow the device"
    finally:
        instrument.close()


def test_trigger_acquires_the_triggered_value(
    tmp_path: Path, device: FakeDevice
) -> None:
    """The trigger command runs, and the value measured after it is acquired."""
    profile = _write_profile(tmp_path / "p.json", reception="events")
    instrument = _instrument(device, profile, mode="trigger", attribute="spectrum")
    try:
        acquisition = instrument.acquire()
        (signal,) = acquisition.objects
        assert isinstance(signal, SignalObj)
        assert device.counter == 1
        assert np.array_equal(signal.y, np.arange(5) + 1)
        assert np.array_equal(signal.x, [0.0, 2.0, 4.0, 6.0, 8.0])
        assert signal.xunit == "eV"
        assert get_experimental_source(signal)["conversions"] == ["int32 -> float64"]
    finally:
        instrument.close()


def test_series_and_lost_values(tmp_path: Path, device: FakeDevice) -> None:
    """A series is acquired completely, or refused if values were lost."""
    profile = _write_profile(tmp_path / "p.json", reception="events", buffer_size=2)
    instrument = _instrument(device, profile, mode="series", count=2, timeout=5.0)
    try:

        def push(count: int) -> None:
            time.sleep(0.05)
            for _index in range(count):
                device.step()

        thread = threading.Thread(target=push, args=(2,))
        thread.start()
        acquisition = instrument.acquire()
        thread.join()
        assert [obj.data[0, 0] for obj in acquisition.objects] == [1, 2]

        instrument.settings.count = 5
        thread = threading.Thread(target=push, args=(5,))
        thread.start()
        with pytest.raises(ValueError, match="3 of 5 values were lost"):
            instrument.acquire()
        thread.join()

        instrument.settings.timeout = 0.1
        with pytest.raises(ValueError, match="Acquisition incomplete: 0 of 5"):
            instrument.acquire()
    finally:
        instrument.close()


def test_exact_detector_counts(tmp_path: Path) -> None:
    """uint32 counts beyond the int32 range are acquired exactly."""
    device = FakeDevice(np.uint32)
    device.step(2**32 - 1)
    instrument = _instrument(device, _write_profile(tmp_path / "p.json"))
    try:
        image = instrument.preview().objects[0]
        assert image.data.dtype == np.float64
        assert image.data[0, 0] == 2**32 - 1
        conversions = get_experimental_source(image)["conversions"]
        assert conversions == ["uint32 -> float64"]
    finally:
        instrument.close()


def test_connection_life_cycle(tmp_path: Path, device: FakeDevice) -> None:
    """Connections, subscriptions and threads are released by every close."""
    polling = _write_profile(tmp_path / "polling.json")
    events = _write_profile(tmp_path / "events.json", reception="events")
    for profile in (polling, events) * 3:
        instrument = _instrument(device, profile)
        instrument.preview()
        instrument.settings.attribute = "spectrum"
        instrument.preview()
        assert device.connections == 1
        instrument.close()
        instrument.close()
    assert device.connections == 0
    assert device.subscriptions == {}
    assert not [t for t in threading.enumerate() if t.name == "tango-poll"]


def test_user_facing_errors(tmp_path: Path, device: FakeDevice) -> None:
    """Unusable settings and unreachable devices give user-facing messages."""
    instrument = TangoInstrument(lambda: FakeBackend(device))
    instrument.open()
    with pytest.raises(ValueError, match="Select a device profile"):
        instrument.preview()
    instrument.settings.profile = _write_profile(tmp_path / "p.json")
    instrument.settings.attribute = "counts"
    with pytest.raises(ValueError, match="no attribute 'counts'"):
        instrument.preview()
    instrument.settings.attribute = ""
    device.unreachable = True
    with pytest.raises(ValueError, match="unreachable"):
        instrument.preview()
    assert device.connections == 0
    instrument.settings.mode = "trigger"
    profile = _write_profile(tmp_path / "notrigger.json", trigger=None)
    instrument.settings.profile = profile
    device.unreachable = False
    with pytest.raises(ValueError, match="has no trigger command"):
        instrument.acquire()
    instrument.close()
    assert device.connections == 0
