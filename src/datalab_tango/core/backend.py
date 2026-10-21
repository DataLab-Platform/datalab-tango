"""Connection to a TANGO device.

:class:`DeviceBackend` is what the instrument needs from a device; tests use a
fake implementation. :class:`PyTangoBackend` implements it with PyTango, which
is imported only when a device is connected.
"""

from __future__ import annotations

import abc
import threading
from collections.abc import Callable

from .reception import Reading

__all__ = ["DeviceBackend", "PyTangoBackend"]

#: Called with each value pushed by the device, or with the event error
EventCallback = Callable[[object], None]


class DeviceBackend(abc.ABC):
    """Connection to one device. Methods may be called from several threads."""

    @abc.abstractmethod
    def connect(self, device: str, timeout_ms: int) -> None:
        """Connect to a device.

        Raises:
            ValueError: with a user-facing message if the device is unreachable
        """

    @abc.abstractmethod
    def read(self, attribute: str) -> Reading:
        """Read the current value of an attribute.

        Raises:
            ValueError: with a user-facing message if the value cannot be read
        """

    @abc.abstractmethod
    def subscribe(self, attribute: str, callback: EventCallback) -> object:
        """Subscribe to the change events of an attribute.

        Args:
            attribute: attribute name
            callback: called in a device thread with a :class:`Reading`, or with
             an exception describing an event error

        Returns:
            Subscription handle
        """

    @abc.abstractmethod
    def unsubscribe(self, handle: object) -> None:
        """Cancel a subscription."""

    @abc.abstractmethod
    def command(self, name: str, argument=None) -> object:
        """Run a device command.

        Raises:
            ValueError: with a user-facing message if the command failed
        """

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Release the connection (called once, after unsubscribing)."""


def _describe(exc: Exception) -> str:
    """Return the user-facing description of a PyTango error."""
    errors = getattr(exc, "args", ())
    if errors and hasattr(errors[0], "desc"):
        return str(errors[0].desc).strip()
    return str(exc)


class PyTangoBackend(DeviceBackend):
    """Device connection through PyTango.

    Device calls are serialized: the instrument and the polling thread share
    the device proxy.
    """

    def __init__(self) -> None:
        self._proxy = None
        self._device = ""
        self._lock = threading.Lock()

    def connect(self, device: str, timeout_ms: int) -> None:
        """Connect to a device and check that it answers."""
        import tango  # pylint: disable=import-outside-toplevel

        try:
            proxy = tango.DeviceProxy(device)
            proxy.set_timeout_millis(timeout_ms)
            proxy.ping()
        except tango.DevFailed as exc:
            raise ValueError(f"Cannot connect to '{device}': {_describe(exc)}") from exc
        self._proxy, self._device = proxy, device

    def read(self, attribute: str) -> Reading:
        """Read the current value of an attribute."""
        import tango  # pylint: disable=import-outside-toplevel

        try:
            with self._lock:
                data = self._proxy.read_attribute(attribute)
        except tango.DevFailed as exc:
            raise ValueError(
                f"Cannot read '{self._device}/{attribute}': {_describe(exc)}"
            ) from exc
        return self._reading(attribute, data)

    def _reading(self, attribute: str, data) -> Reading:
        """Return the reading of a device attribute value."""
        if data.value is None:
            raise ValueError(
                f"'{self._device}/{attribute}' has no value (quality {data.quality})"
            )
        return Reading.create(data.value, data.time.totime(), str(data.quality))

    def subscribe(self, attribute: str, callback: EventCallback) -> object:
        """Subscribe to the change events of an attribute."""
        import tango  # pylint: disable=import-outside-toplevel

        def on_event(event) -> None:
            if event.err:
                callback(ValueError(str(event.errors[0].desc).strip()))
                return
            try:
                callback(self._reading(attribute, event.attr_value))
            except ValueError as exc:
                callback(exc)

        try:
            with self._lock:
                return self._proxy.subscribe_event(
                    attribute, tango.EventType.CHANGE_EVENT, on_event
                )
        except tango.DevFailed as exc:
            raise ValueError(
                f"Cannot subscribe to '{self._device}/{attribute}' events: "
                f"{_describe(exc)}"
            ) from exc

    def unsubscribe(self, handle: object) -> None:
        """Cancel a subscription."""
        with self._lock:
            self._proxy.unsubscribe_event(handle)

    def command(self, name: str, argument=None) -> object:
        """Run a device command."""
        import tango  # pylint: disable=import-outside-toplevel

        try:
            with self._lock:
                if argument is None:
                    return self._proxy.command_inout(name)
                return self._proxy.command_inout(name, argument)
        except tango.DevFailed as exc:
            raise ValueError(
                f"Command '{name}' of '{self._device}' failed: {_describe(exc)}"
            ) from exc

    def disconnect(self) -> None:
        """Release the device proxy."""
        self._proxy = None
