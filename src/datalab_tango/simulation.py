"""Simulated TANGO devices, to try the plugin without hardware.

Run ``python -m datalab_tango.simulation [folder]``: a TANGO device server
without database starts on this computer with a simulated oscilloscope and a
simulated camera, and a device profile is written for each of them in the
folder (default: current folder). Open these profiles in DataLab's TANGO
instrument; stop the server with Ctrl+C.

When the DataLab characterization plugins are installed, the devices use
their simulators (``datalab_pulse_characterization`` oscilloscope traces,
``datalab_camera_characterization`` sensor model); otherwise they generate
simple synthetic data. Both devices acquire continuously, and acquire at once
when their trigger command runs; this command returns the time stamp of the
value it acquired, so that DataLab tells it apart from free-running ones.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
from tango import AttrQuality, DevState
from tango.server import Device, attribute, command
from tango.test_context import MultiDeviceTestContext

__all__ = ["SimulatedCamera", "SimulatedOscilloscope", "main"]

#: Interval between two acquisitions of a free-running device (s)
FREE_RUN_INTERVAL = 0.2

SCOPE_NAME, CAMERA_NAME = "sim/oscilloscope/1", "sim/camera/1"
CAMERA_SHAPE = (128, 160)


def _scope_trace(number: int) -> tuple[np.ndarray, float, float]:
    """Return one trace (V), its first sample time and its sample period (ns)."""
    try:
        from datalab_pulse_characterization.core.oscilloscope import (
            OscilloscopeSettings,
            PulseSource,
            acquire_traces,
        )
    except ImportError:
        t = np.linspace(-20.0, 80.0, 501)
        rng = np.random.default_rng(number)
        trace = 0.5 * np.exp(-0.5 * ((t - rng.normal(0.0, 0.05)) / 0.85) ** 2)
        return trace + rng.normal(0.0, 0.005, t.size), float(t[0]), float(t[1] - t[0])
    scope = OscilloscopeSettings()
    t, ((trace,),) = acquire_traces(
        PulseSource(), scope, 1, np.random.SeedSequence((20261021, number))
    )
    return trace, float(t[0]), 1.0 / scope.sample_rate_gsps


def _camera_frame(number: int) -> np.ndarray:
    """Return one camera frame (DN)."""
    try:
        from datalab_camera_characterization.core.simulation import (
            CameraSimulationParameters,
            simulate_camera_frames,
        )
    except ImportError:
        rng = np.random.default_rng(number)
        y, x = np.mgrid[: CAMERA_SHAPE[0], : CAMERA_SHAPE[1]]
        spot = 2000.0 * np.exp(-((x - 80.0) ** 2 + (y - 64.0) ** 2) / 800.0)
        return rng.poisson(100.0 + spot).astype(np.uint16)
    parameters = CameraSimulationParameters(
        shape=CAMERA_SHAPE, frame_count=1, vignetting_fraction=0.2, noise_stream=number
    )
    return np.array(simulate_camera_frames(parameters).frames_dn[0], dtype=np.uint16)


class _FreeRunningDevice(Device):
    """Device acquiring continuously in a thread, and at once on trigger.

    Acquisitions run one at a time. A triggered acquisition cancels the
    free-running one due during it, so that its value stays available for at
    least :data:`FREE_RUN_INTERVAL`.
    """

    def init_device(self) -> None:
        super().init_device()
        self._lock = threading.Lock()
        self._acquisition = threading.RLock()
        self._number = 0
        self._triggers = 0
        self._stamp = 0.0
        self._acquire()
        self._stop = threading.Event()
        threading.Thread(target=self._free_run, daemon=True).start()
        self.set_state(DevState.RUNNING)

    def delete_device(self) -> None:
        self._stop.set()

    def _free_run(self) -> None:
        while True:
            with self._lock:
                triggers = self._triggers
            if self._stop.wait(FREE_RUN_INTERVAL):
                return
            self._acquire(triggers)

    def _acquire(self, free_run_after: int | None = None) -> float | None:
        """Acquire a new value and return its time stamp.

        Args:
            free_run_after: for a free-running acquisition, number of triggered
             acquisitions when it was scheduled: it is cancelled (None returned)
             if another one ran since
        """
        with self._acquisition:
            with self._lock:
                if free_run_after is not None and free_run_after != self._triggers:
                    return None
                self._number += 1
                number = self._number
            value = self._measure(number)
            with self._lock:
                self._value, self._stamp = value, time.time()
                return self._stamp

    def _trigger(self) -> float:
        """Acquire a value now and return its time stamp."""
        with self._acquisition:
            with self._lock:
                self._triggers += 1
            return self._acquire()

    def _measure(self, number: int):
        raise NotImplementedError

    def _read(self):
        with self._lock:
            return self._value, self._stamp, AttrQuality.ATTR_VALID

    @attribute(dtype=int)
    def acquisitions(self) -> int:
        """Number of acquisitions since the device started."""
        return self._number


class SimulatedOscilloscope(_FreeRunningDevice):
    """Oscilloscope acquiring a laser pulse on CH1."""

    def _measure(self, number: int) -> np.ndarray:
        return _scope_trace(number)[0]

    @attribute(dtype=(float,), max_dim_x=100_000, unit="V")
    def ch1(self):
        """Last trace of channel 1."""
        return self._read()

    @command(dtype_out=float)
    def Trigger(self) -> float:  # pylint: disable=invalid-name
        """Acquire a trace now; return its time stamp."""
        return self._trigger()


class SimulatedCamera(_FreeRunningDevice):
    """Camera imaging a spot."""

    def _measure(self, number: int) -> np.ndarray:
        return _camera_frame(number)

    @attribute(dtype=((np.uint16,),), max_dim_x=4096, max_dim_y=4096, unit="DN")
    def frame(self):
        """Last frame."""
        return self._read()

    @command(dtype_out=float)
    def Snap(self) -> float:  # pylint: disable=invalid-name
        """Acquire a frame now; return its time stamp."""
        return self._trigger()


def write_profiles(folder: Path, scope_address: str, camera_address: str) -> list:
    """Write the device profiles of the simulated devices."""
    _trace, t0, dt = _scope_trace(0)
    profiles = {
        "simulated_oscilloscope.json": {
            "version": 1,
            "name": "Simulated oscilloscope",
            "device": scope_address,
            "attributes": [
                {
                    "name": "ch1",
                    "kind": "signal",
                    "label": "CH1",
                    "unit": "V",
                    "x": {"origin": t0, "step": dt, "unit": "ns", "label": "Time"},
                }
            ],
            "trigger": {"command": "Trigger", "returns": "time_stamp"},
            "polling_interval_ms": 100,
        },
        "simulated_camera.json": {
            "version": 1,
            "name": "Simulated camera",
            "device": camera_address,
            "attributes": [{"name": "frame", "kind": "image", "unit": "DN"}],
            "trigger": {"command": "Snap", "returns": "time_stamp"},
            "polling_interval_ms": 100,
        },
    }
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, profile in profiles.items():
        path = folder / name
        path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        paths.append(path)
    return paths


def main(folder: str = ".") -> None:
    """Serve the simulated devices until interrupted, with their profiles."""
    devices = (
        {"class": SimulatedOscilloscope, "devices": [{"name": SCOPE_NAME}]},
        {"class": SimulatedCamera, "devices": [{"name": CAMERA_NAME}]},
    )
    with MultiDeviceTestContext(devices, process=True, timeout=60.0) as context:
        paths = write_profiles(
            Path(folder),
            context.get_device_access(SCOPE_NAME),
            context.get_device_access(CAMERA_NAME),
        )
        print("Simulated devices running; profiles:")
        for path in paths:
            print(f"  {path.resolve()}")
        print("Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main(*sys.argv[1:2])
