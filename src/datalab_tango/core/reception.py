"""Reception of attribute values, in the threads of the device connection.

Values are received either by periodic reads or by change events, in threads
which are not DataLab's: they are stored in a bounded :class:`FrameBuffer`,
from which the instrument takes them when DataLab asks for a preview or an
acquisition. The buffer counts every received value, so that an acquisition
of several values can tell how many of them were lost.
"""

from __future__ import annotations

import collections
import dataclasses
import threading
import time
from collections.abc import Callable

import numpy as np

__all__ = ["STAMP_TOLERANCE", "FrameBuffer", "PollingReceiver", "Reading"]

#: Largest difference between two device time stamps of the same value (s): TANGO
#: time stamps of attribute values may be truncated to the millisecond (e.g. on
#: Windows), while a command returns the full value
STAMP_TOLERANCE = 1e-3


@dataclasses.dataclass(frozen=True)
class Reading:
    """Attribute value received from the device.

    Args:
        value: read-only copy of the value
        source_time: time stamped by the device (s since the epoch), if any
        reception_time: time of reception by DataLab (s since the epoch)
        quality: TANGO quality of the value (e.g. ``ATTR_VALID``)
        number: rank of the value among the values received by the buffer
    """

    value: np.ndarray
    source_time: float | None
    reception_time: float
    quality: str
    number: int = 0

    @classmethod
    def create(
        cls, value, source_time: float | None, quality: str = "ATTR_VALID"
    ) -> Reading:
        """Return a reading holding an independent, read-only copy of value."""
        array = np.array(value, copy=True)
        array.setflags(write=False)
        return cls(array, source_time, time.time(), quality)


class FrameBuffer:
    """Bounded buffer of the last values received for an attribute.

    Args:
        size: number of values kept
    """

    def __init__(self, size: int) -> None:
        self._readings: collections.deque[Reading] = collections.deque(maxlen=size)
        self._condition = threading.Condition()
        self._count = 0
        self._error: str | None = None

    @property
    def count(self) -> int:
        """Number of values received since the buffer was created."""
        with self._condition:
            return self._count

    @property
    def error(self) -> str | None:
        """Last reception error, cleared by the next received value."""
        with self._condition:
            return self._error

    def push(self, reading: Reading) -> None:
        """Store a received value (reception thread)."""
        with self._condition:
            self._count += 1
            self._readings.append(dataclasses.replace(reading, number=self._count))
            self._error = None
            self._condition.notify_all()

    def push_error(self, message: str) -> None:
        """Store a reception error (reception thread)."""
        with self._condition:
            self._error = message
            self._condition.notify_all()

    def latest(self, timeout: float = 0.0) -> Reading | None:
        """Return the last received value, waiting for a first one if needed."""
        with self._condition:
            self._condition.wait_for(lambda: self._count > 0, timeout)
            return self._readings[-1] if self._readings else None

    def wait_for(
        self, after: int, count: int, timeout: float
    ) -> tuple[list[Reading], int]:
        """Wait for the values received after a given one.

        Args:
            after: number of the last value received before waiting
            count: number of values to wait for
            timeout: maximum waiting time (s)

        Returns:
            Values still kept by the buffer, and number of values received but
            lost because the buffer was full

        Raises:
            TimeoutError: if fewer values were received before the timeout
        """
        with self._condition:
            if not self._condition.wait_for(
                lambda: self._count >= after + count, timeout
            ):
                received = self._count - after
                detail = f": {self._error}" if self._error else ""
                raise TimeoutError(
                    f"{received} of {count} values received in {timeout:g} s{detail}"
                )
            last = after + count
            kept = [r for r in self._readings if after < r.number <= last]
            return kept, count - len(kept)

    def wait_for_stamp(self, after: int, stamp: float, timeout: float) -> Reading:
        """Wait for the value of a given device time stamp, ignoring other values.

        Args:
            after: number of the last value received before waiting
            stamp: device time stamp of the expected value (s since the epoch),
             matched within :data:`STAMP_TOLERANCE`
            timeout: maximum waiting time (s)

        Returns:
            Value received after the given one, with this time stamp

        Raises:
            TimeoutError: if no such value was received before the timeout
        """

        def find() -> Reading | None:
            for reading in self._readings:
                if (
                    reading.number > after
                    and reading.source_time is not None
                    and abs(reading.source_time - stamp) <= STAMP_TOLERANCE
                ):
                    return reading
            return None

        with self._condition:
            found = self._condition.wait_for(find, timeout)
            if found is None:
                received = self._count - after
                kept = sum(1 for reading in self._readings if reading.number > after)
                details = [f"values received meanwhile: {received}"]
                if received > kept:
                    details.append(f"{received - kept} lost, the buffer being full")
                if self._error:
                    details.append(f"last error: {self._error}")
                raise TimeoutError(
                    f"value of time stamp {stamp:.6f} not received in {timeout:g} s "
                    f"({'; '.join(details)})"
                )
            return found


class PollingReceiver:
    """Read an attribute periodically, in a daemon thread.

    A value is stored only if its device time stamp changed, so that reading
    faster than the device updates its value does not duplicate it.

    Args:
        read: function returning the current value of the attribute
        buffer: buffer receiving the values
        interval: interval between two reads (s)
    """

    def __init__(
        self, read: Callable[[], Reading], buffer: FrameBuffer, interval: float
    ) -> None:
        self._read = read
        self._buffer = buffer
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="tango-poll", daemon=True
        )
        self._last_time: float | None = None

    def start(self) -> None:
        """Start reading."""
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop reading, waiting for the current read to end."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _run(self) -> None:
        """Read until stopped."""
        while not self._stop.is_set():
            try:
                reading = self._read()
            except Exception as exc:  # pylint: disable=broad-except
                self._buffer.push_error(str(exc))
            else:
                stamp = reading.source_time
                if stamp is None or stamp != self._last_time:
                    self._last_time = stamp
                    self._buffer.push(reading)
            self._stop.wait(self._interval)
