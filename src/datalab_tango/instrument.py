"""TANGO device attribute shown as a DataLab instrument.

The live view shows the last value received from the device. **Acquire**
copies received values into the workspace: the last one, the one measured
after running the trigger command of the profile, or the next values received.
Received values are kept by a bounded buffer: an acquisition of several values
fails, instead of silently missing some, if values were lost.
"""

from __future__ import annotations

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
    load_profile,
    reading_to_object,
)

__all__ = ["TANGO_INSTRUMENT_TOOL", "TangoInstrument", "TangoInstrumentSettings"]

TANGO_INSTRUMENT_TOOL = PluginTool(
    id="tango-instrument",
    title="TANGO instrument...",
    description="Show a TANGO device attribute live and acquire its values",
    instrument="tango_instrument",
)

#: Longest wait for a first value before a preview reports that none arrived (s)
FIRST_VALUE_TIMEOUT = 2.0

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


class TangoInstrument(PluginInstrument):
    """TANGO device attribute, received while the instrument window is open.

    Args:
        backend_factory: returns a new device connection (tests use a fake one)
    """

    live_interval_ms = 200

    def __init__(
        self, backend_factory: Callable[[], DeviceBackend] = PyTangoBackend
    ) -> None:
        super().__init__(TangoInstrumentSettings())
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
        if self._session is not None:
            session, self._session, self._session_key = self._session, None, None
            session.stop()

    def _get_session(self) -> AttributeSession:
        """Return the session matching the settings, (re)connecting if needed."""
        key = (str(self.settings.profile or ""), str(self.settings.attribute or ""))
        if self._session is not None and key == self._session_key:
            return self._session
        self.close()
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
        if mode == "latest":
            readings = [self._latest(session, timeout)]
        else:
            count = int(self.settings.count) if mode == "series" else 1
            after = session.buffer.count
            if mode == "trigger":
                session.trigger()
            try:
                readings, lost = session.buffer.wait_for(after, count, timeout)
            except TimeoutError as exc:
                raise ValueError(f"Acquisition incomplete: {exc}") from exc
            if lost:
                raise ValueError(
                    f"{lost} of {count} values were lost: reduce the number of "
                    "values, or increase the buffer size of the profile"
                )
        objects = [
            reading_to_object(
                reading,
                session.profile,
                session.attribute,
                self._title(session, reading),
            )
            for reading in readings
        ]
        self._acquisition_count += 1
        return InstrumentAcquisition(
            f"{session.profile.name} - {session.attribute.name} - "
            f"acquisition {self._acquisition_count:03d}",
            objects,
        )
