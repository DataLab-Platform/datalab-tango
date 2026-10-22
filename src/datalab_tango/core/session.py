"""Session with a device attribute: connection and reception of its values."""

from __future__ import annotations

from .backend import DeviceBackend
from .profile import AttributeProfile, DeviceProfile, Reception
from .reception import FrameBuffer, PollingReceiver, Reading

__all__ = ["AttributeSession"]


class AttributeSession:
    """Connection to a device, receiving the values of one attribute.

    Args:
        profile: device profile
        attribute: received attribute
        backend: device connection, not connected yet
    """

    def __init__(
        self,
        profile: DeviceProfile,
        attribute: AttributeProfile,
        backend: DeviceBackend,
    ) -> None:
        self.profile = profile
        self.attribute = attribute
        self.backend = backend
        self.buffer = FrameBuffer(profile.buffer_size)
        self._receiver: PollingReceiver | None = None
        self._subscription: object | None = None
        self._connected = False

    def start(self) -> None:
        """Connect to the device and start receiving values.

        Raises:
            ValueError: if the device cannot be reached
        """
        self.backend.connect(self.profile.device, self.profile.timeout_ms)
        self._connected = True
        name = self.attribute.name
        if self.profile.reception is Reception.EVENTS:
            self._subscription = self.backend.subscribe(name, self._on_event)
        else:
            self._receiver = PollingReceiver(
                lambda: self.backend.read(name),
                self.buffer,
                self.profile.polling_interval_ms / 1000.0,
            )
            self._receiver.start()

    def _on_event(self, value: object) -> None:
        """Store a value pushed by the device (device thread)."""
        if isinstance(value, Reading):
            self.buffer.push(value)
        else:
            self.buffer.push_error(str(value))

    def stop(self) -> None:
        """Stop receiving values and disconnect; does nothing if already stopped."""
        if self._receiver is not None:
            self._receiver.stop()
            self._receiver = None
        if self._subscription is not None:
            subscription, self._subscription = self._subscription, None
            self.backend.unsubscribe(subscription)
        if self._connected:
            self._connected = False
            self.backend.disconnect()

    def trigger(self) -> object:
        """Run the trigger command of the profile.

        Returns:
            Value returned by the command

        Raises:
            ValueError: if the profile has no trigger, or if the command failed
        """
        trigger = self.profile.trigger
        if trigger is None:
            raise ValueError(f"Profile '{self.profile.name}' has no trigger command")
        return self.backend.command(trigger.command, trigger.argument)
