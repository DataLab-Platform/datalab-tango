"""Reception buffer and periodic reads."""

from __future__ import annotations

import threading
import time

import pytest

from datalab_tango.core import FrameBuffer, PollingReceiver, Reading


def test_wait_for_counts_lost_values() -> None:
    """Values pushed out of a full buffer before being taken are counted."""
    buffer = FrameBuffer(2)
    after = buffer.count
    for index in range(5):
        buffer.push(Reading.create([index], float(index)))
    kept, lost = buffer.wait_for(after, 5, 1.0)
    assert [int(reading.value[0]) for reading in kept] == [3, 4]
    assert [reading.number for reading in kept] == [4, 5]
    assert lost == 3


def test_wait_for_timeout_reports_error() -> None:
    """A timeout tells how many values arrived and the last reception error."""
    buffer = FrameBuffer(4)
    buffer.push(Reading.create([1.0], 1.0))
    buffer.push_error("Device timeout")
    with pytest.raises(TimeoutError, match="0 of 2 values received.*Device timeout"):
        buffer.wait_for(buffer.count, 2, 0.05)


def test_wait_for_values_pushed_later() -> None:
    """Values pushed by another thread end the wait."""
    buffer = FrameBuffer(8)
    after = buffer.count

    def push() -> None:
        for index in range(3):
            time.sleep(0.01)
            buffer.push(Reading.create([index], float(index)))

    thread = threading.Thread(target=push)
    thread.start()
    kept, lost = buffer.wait_for(after, 3, 5.0)
    thread.join()
    assert (len(kept), lost) == (3, 0)


def test_readings_are_read_only_copies() -> None:
    """Received values cannot change once stored."""
    source = [1.0, 2.0]
    reading = Reading.create(source, None)
    source[0] = 9.0
    assert reading.value[0] == 1.0
    with pytest.raises(ValueError):
        reading.value[0] = 3.0


def test_polling_skips_unchanged_values() -> None:
    """Periodic reads store a value only when its device time stamp changes."""
    stamps = iter([1.0, 1.0, 1.0, 2.0, 2.0, 3.0] + [3.0] * 1000)
    buffer = FrameBuffer(8)
    receiver = PollingReceiver(
        lambda: Reading.create([0.0], next(stamps)), buffer, interval=0.001
    )
    receiver.start()
    kept, lost = buffer.wait_for(0, 3, 5.0)
    receiver.stop()
    assert [reading.source_time for reading in kept] == [1.0, 2.0, 3.0]
    assert lost == 0


def test_polling_reports_read_errors() -> None:
    """Read errors are stored as the last reception error."""

    def failing_read() -> Reading:
        raise ValueError("Cannot read 'lab/cam/1/frame': device timeout")

    buffer = FrameBuffer(2)
    receiver = PollingReceiver(failing_read, buffer, interval=0.001)
    receiver.start()
    deadline = time.monotonic() + 5.0
    while buffer.error is None and time.monotonic() < deadline:
        time.sleep(0.001)
    receiver.stop()
    assert "device timeout" in buffer.error
