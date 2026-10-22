"""Simulated TANGO devices, served by PyTango's test context."""

from __future__ import annotations

import time

import numpy as np
from tango import AttrQuality, DevState
from tango.server import Device, attribute, command


class SimulatedCamera(Device):
    """Camera whose frame changes when ``Snap`` runs; counts may exceed int32."""

    def init_device(self) -> None:
        super().init_device()
        self._shots = 0
        self._stamp = time.time()
        self.set_state(DevState.ON)

    @attribute(dtype=((np.uint32,),), max_dim_x=4096, max_dim_y=4096, unit="counts")
    def frame(self):
        frame = np.full((3, 4), self._shots, dtype=np.uint32)
        frame[0, 0] = 2**32 - 1
        return frame, self._stamp, AttrQuality.ATTR_VALID

    @attribute(dtype=(float,), max_dim_x=4096)
    def spectrum(self):
        values = np.linspace(0.0, 1.0, 5) + self._shots
        return values, self._stamp, AttrQuality.ATTR_VALID

    @command
    def Snap(self) -> None:  # pylint: disable=invalid-name
        """Acquire a new frame."""
        self._shots += 1
        self._stamp = time.time()

    @command(dtype_out=float)
    def SnapTimed(self) -> float:  # pylint: disable=invalid-name
        """Acquire a new frame; return its time stamp."""
        self.Snap()
        return self._stamp
