"""TANGO device attribute shown as a DataLab instrument.

The live view shows the last value received from the device. **Acquire**
copies received values into the workspace: the last one, the one measured
after running the trigger command of the profile, or the next values received.
Acquisitions go to the current group of the panel, unless the user turns on the
**New group** option of the instrument window. Received values are kept by a
bounded buffer: an acquisition of several values fails, instead of silently
missing some, if values were lost.

A triggered value is identified by its device time stamp when the trigger
command returns it (``"returns": "time_stamp"`` in the profile): other values
received meanwhile are ignored. Otherwise, the first value received after the
command started is taken, which may not be the triggered one (free-running
device, value delivered late); the origin of the acquired object tells which.

The simulated devices instrument works the same way, with the simulated
oscilloscope and camera served by a child process while its window is open: the
plugin can be tried without hardware nor command line.
"""

from __future__ import annotations

import math
import numbers
import os.path as osp
from collections.abc import Callable

import guidata.dataset as gds
from datalab.plugins.instruments import (
    InstrumentAcquisition,
    InstrumentFrame,
    PluginInstrument,
)
from datalab.plugins.tools import PluginTool

from .core import (
    AttributeSession,
    DeviceBackend,
    PyTangoBackend,
    Reading,
    SimulatedDevices,
    load_profile,
    reading_to_object,
)

__all__ = [
    "SIMULATED_DEVICES_TOOL",
    "TANGO_INSTRUMENT_TOOL",
    "SimulatedTangoInstrument",
    "SimulatedTangoSettings",
    "TangoInstrument",
    "TangoInstrumentSettings",
]

TANGO_INSTRUMENT_TOOL = PluginTool(
    id="tango-instrument",
    title="TANGO instrument...",
    description="Show a TANGO device attribute live and acquire its values",
    instrument="tango_instrument",
)

SIMULATED_DEVICES_TOOL = PluginTool(
    id="tango-simulation",
    title="Simulated TANGO devices...",
    description=(
        "Try without hardware: a simulated oscilloscope and camera, served by a "
        "TANGO device server started on this computer while the window is open"
    ),
    instrument="simulated_tango_instrument",
)

#: Longest wait for a first value before a preview reports that none arrived (s)
FIRST_VALUE_TIMEOUT = 2.0


def _time_stamp(value: object, command: str) -> float:
    """Return the time stamp returned by a trigger command.

    Raises:
        ValueError: if the command did not return a time stamp
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, numbers.Real)
        or not math.isfinite(value)
    ):
        raise ValueError(
            f"Trigger command '{command}' returned {value!r}, not a time stamp: "
            "check the 'returns' field of the profile trigger"
        )
    return float(value)


MODES = (
    ("latest", "Last received value"),
    ("trigger", "Trigger a measurement, then its value"),
    ("series", "Next received values"),
)
_MODE = gds.ValueProp("latest")


class TangoInstrumentSettings(gds.DataSet):
    """TANGO instrument"""

    profile = gds.FileOpenItem(
        "Device profile", formats=("json",), help="JSON file describing the device"
    )
    attribute = gds.StringItem(
        "Attribute", default="", help="Empty: first attribute of the profile"
    )
    mode = gds.ChoiceItem("Acquisition", MODES, default="latest").set_prop(
        "display", store=_MODE
    )
    count = gds.IntItem("Number of values", default=10, min=1, max=100_000).set_prop(
        "display", active=gds.FuncProp(_MODE, lambda mode: mode == "series")
    )
    timeout = gds.FloatItem("Timeout", default=10.0, min=0.1, unit="s")


SIMULATED_DEVICES = (
    ("oscilloscope", "Oscilloscope (laser pulse on CH1)"),
    ("camera", "Camera (spot image)"),
)
_SIMULATED_MODE = gds.ValueProp("trigger")


class SimulatedTangoSettings(gds.DataSet):
    """Simulated TANGO devices"""

    device = gds.ChoiceItem(
        "Simulated device",
        SIMULATED_DEVICES,
        default="oscilloscope",
        help="Device served by the simulated TANGO device server",
    )
    mode = gds.ChoiceItem("Acquisition", MODES, default="trigger").set_prop(
        "display", store=_SIMULATED_MODE
    )
    count = gds.IntItem("Number of values", default=10, min=1, max=100_000).set_prop(
        "display", active=gds.FuncProp(_SIMULATED_MODE, lambda mode: mode == "series")
    )
    timeout = gds.FloatItem("Timeout", default=10.0, min=0.1, unit="s")


class TangoInstrument(PluginInstrument):
    """TANGO device attribute, received while the instrument window is open.

    Args:
        backend_factory: returns a new device connection (tests use a fake one)
        settings: instrument settings (default: device profile and attribute)
    """

    live_interval_ms = 200
    # Acquisitions are usually single values: they accumulate in the current
    # group, unless the user turns on the "New group" option
    new_group = False

    def __init__(
        self,
        backend_factory: Callable[[], DeviceBackend] = PyTangoBackend,
        settings: gds.DataSet | None = None,
    ) -> None:
        super().__init__(TangoInstrumentSettings() if settings is None else settings)
        self._backend_factory = backend_factory
        self._session: AttributeSession | None = None
        self._session_key: tuple[str, str] | None = None
        self._acquisition_count = 0

    def open(self) -> None:
        """Connect to the device of the last used profile, if any."""
        if self.settings.profile and osp.isfile(self.settings.profile):
            self._get_session()

    def close(self) -> None:
        """Stop receiving values and disconnect."""
        self._disconnect()

    def _disconnect(self) -> None:
        """Stop receiving values and disconnect, if connected."""
        if self._session is not None:
            session, self._session, self._session_key = self._session, None, None
            session.stop()

    def _target(self) -> tuple[str, str]:
        """Return the profile file and the attribute set by the settings."""
        return (str(self.settings.profile or ""), str(self.settings.attribute or ""))

    def _get_session(self) -> AttributeSession:
        """Return the session matching the settings, (re)connecting if needed."""
        key = self._target()
        if self._session is not None and key == self._session_key:
            return self._session
        self._disconnect()
        if not key[0]:
            raise ValueError("Select a device profile")
        profile = load_profile(key[0])
        session = AttributeSession(
            profile, profile.get_attribute(key[1]), self._backend_factory()
        )
        try:
            session.start()
        except Exception:
            session.stop()
            raise
        self._session, self._session_key = session, key
        return session

    def _latest(self, session: AttributeSession, timeout: float) -> Reading:
        """Return the last received value."""
        reading = session.buffer.latest(timeout)
        if reading is None:
            error = session.buffer.error
            raise ValueError(
                error or f"No value received from '{session.profile.device}'"
            )
        return reading

    def _title(self, session: AttributeSession, reading: Reading) -> str:
        """Return the title of an object holding a received value."""
        attribute = session.attribute
        return f"{attribute.label or attribute.name} #{reading.number}"

    def preview(self) -> InstrumentFrame:
        """Return the last value received from the device."""
        session = self._get_session()
        reading = self._latest(session, FIRST_VALUE_TIMEOUT)
        obj = reading_to_object(
            reading, session.profile, session.attribute, self._title(session, reading)
        )
        summary = (
            f"{session.profile.name} - {session.attribute.name}: "
            f"{session.buffer.count} values received, quality {reading.quality}"
        )
        if session.buffer.error:
            summary += f" - last error: {session.buffer.error}"
        return InstrumentFrame((obj,), summary)

    def acquire(self) -> InstrumentAcquisition:
        """Copy received values into the workspace, as set by the acquisition mode."""
        session = self._get_session()
        timeout = float(self.settings.timeout)
        mode = self.settings.mode
        details = None
        if mode == "latest":
            readings = [self._latest(session, timeout)]
        elif mode == "trigger":
            reading, trigger = self._trigger(session, timeout)
            readings, details = [reading], {"trigger": trigger}
        else:
            count = int(self.settings.count)
            readings = self._next(session, session.buffer.count, count, timeout)
        objects = [
            reading_to_object(
                reading,
                session.profile,
                session.attribute,
                self._title(session, reading),
                details,
            )
            for reading in readings
        ]
        self._acquisition_count += 1
        return InstrumentAcquisition(
            f"{session.profile.name} - {session.attribute.name} - "
            f"acquisition {self._acquisition_count:03d}",
            objects,
        )

    @staticmethod
    def _next(
        session: AttributeSession, after: int, count: int, timeout: float
    ) -> list[Reading]:
        """Return the values received after a given one, refusing lost values."""
        try:
            readings, lost = session.buffer.wait_for(after, count, timeout)
        except TimeoutError as exc:
            raise ValueError(f"Acquisition incomplete: {exc}") from exc
        if lost:
            raise ValueError(
                f"{lost} of {count} values were lost: reduce the number of "
                "values, or increase the buffer size of the profile"
            )
        return readings

    def _trigger(
        self, session: AttributeSession, timeout: float
    ) -> tuple[Reading, dict[str, str]]:
        """Run the trigger command, and return the value measured after it.

        If the profile tells that the command returns the time stamp of its
        measurement, the value of this time stamp is returned: values received
        meanwhile (free-running device, values delivered late) are ignored.
        Otherwise, the first value received after the command started is
        returned: it may be another value than the triggered one.

        Returns:
            Value, and how it was identified (``synchronization``: ``time_stamp``
             or ``first_after_command``)
        """
        after = session.buffer.count
        result = session.trigger()
        trigger = session.profile.trigger
        if trigger.returns == "time_stamp":
            stamp = _time_stamp(result, trigger.command)
            try:
                reading = session.buffer.wait_for_stamp(after, stamp, timeout)
            except TimeoutError as exc:
                raise ValueError(f"Triggered value not received: {exc}") from exc
            synchronization = "time_stamp"
        else:
            (reading,) = self._next(session, after, 1, timeout)
            synchronization = "first_after_command"
        return reading, {"command": trigger.command, "synchronization": synchronization}


class SimulatedTangoInstrument(TangoInstrument):
    """Simulated TANGO devices, served while the instrument window is open.

    Opening the instrument starts a simulated oscilloscope and camera in a child
    process (see :class:`~datalab_tango.core.SimulatedDevices`), then connects to
    the selected one through TANGO, as to a real device; closing it disconnects,
    then stops the child process. Devices which stopped unexpectedly are started
    again by the next call.

    Args:
        backend_factory: returns a new device connection (tests use a fake one)
        devices_factory: returns new simulated devices, not started yet (tests use
         fake ones)
    """

    def __init__(
        self,
        backend_factory: Callable[[], DeviceBackend] = PyTangoBackend,
        devices_factory: Callable[[], SimulatedDevices] = SimulatedDevices,
    ) -> None:
        super().__init__(backend_factory, SimulatedTangoSettings())
        self._devices_factory = devices_factory
        self._devices: SimulatedDevices | None = None

    @property
    def devices(self) -> SimulatedDevices | None:
        """Simulated devices, once started by the instrument (None once closed)"""
        return self._devices

    def open(self) -> None:
        """Start the simulated devices, then connect to the selected one."""
        self._get_session()

    def close(self) -> None:
        """Disconnect, then stop the simulated devices."""
        try:
            self._disconnect()
        finally:
            devices, self._devices = self._devices, None
            if devices is not None:
                devices.stop()

    def _target(self) -> tuple[str, str]:
        """Return the profile of the selected device, starting the devices if
        needed, and its first attribute."""
        if self._devices is None or not self._devices.is_running():
            self._disconnect()
            if self._devices is not None:
                self._devices.stop()
            self._devices = self._devices_factory()
            self._devices.start()
        return str(self._devices.profiles[self.settings.device]), ""
