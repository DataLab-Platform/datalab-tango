"""Reception buffer and periodic reads."""

from __future__ import annotations

import threading
import time

import pytest

from datalab_tango.core import FrameBuffer, PollingReceiver, Reading, stamp_matches

#: Realistic device time stamp (s since the epoch), a whole number of milliseconds
EPOCH = 1_790_000_000.0


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


def test_wait_for_stamp_ignores_other_values() -> None:
    """The value of the given time stamp is returned, received before or during
    the wait, among other values; values received before ``after`` do not count."""
    buffer = FrameBuffer(8)
    buffer.push(Reading.create([0], 10.0))
    after = buffer.count
    buffer.push(Reading.create([1], 11.0))
    buffer.push(Reading.create([2], 12.0))
    # Device time stamp truncated to the millisecond, as returned by the command
    reading = buffer.wait_for_stamp(after, 12.0004, 1.0)
    assert (int(reading.value[0]), reading.number) == (2, 3)
    with pytest.raises(TimeoutError, match="values received meanwhile: 2\\)"):
        buffer.wait_for_stamp(after, 10.0, 0.05)

    def push() -> None:
        time.sleep(0.02)
        buffer.push(Reading.create([3], 13.0))
        buffer.push(Reading.create([4], 14.0))

    thread = threading.Thread(target=push)
    thread.start()
    reading = buffer.wait_for_stamp(after, 14.0, 5.0)
    thread.join()
    assert int(reading.value[0]) == 4


def test_stamp_matches_within_resolution() -> None:
    """A time stamp truncated to the microsecond matches only within a microsecond,
    and one truncated to the millisecond only the millisecond following it."""
    assert stamp_matches(EPOCH + 0.000123, EPOCH + 0.0001234)
    assert not stamp_matches(EPOCH + 0.000123, EPOCH + 0.000623)
    assert not stamp_matches(EPOCH + 0.000623, EPOCH + 0.000123)
    assert stamp_matches(EPOCH + 0.001, EPOCH + 0.0019)
    assert not stamp_matches(EPOCH + 0.001, EPOCH + 0.0021)
    assert not stamp_matches(EPOCH + 0.001, EPOCH + 0.0006)


def test_wait_for_stamp_tells_values_apart_within_a_millisecond() -> None:
    """A value measured on its own less than 1 ms before or after the triggered
    one is not taken for it, unless both time stamps are truncated to the same
    millisecond."""
    buffer = FrameBuffer(8)
    after = buffer.count
    buffer.push(Reading.create([1], EPOCH + 0.000200))
    buffer.push(Reading.create([2], EPOCH + 0.000700))
    reading = buffer.wait_for_stamp(after, EPOCH + 0.0007004, 1.0)
    assert int(reading.value[0]) == 2
    # Time stamps truncated to the millisecond: a value measured less than 1 ms
    # after the triggered one, which was missed, is not taken for it
    buffer = FrameBuffer(8)
    after = buffer.count
    buffer.push(Reading.create([3], EPOCH + 0.001))
    with pytest.raises(TimeoutError, match="values received meanwhile: 1\\)"):
        buffer.wait_for_stamp(after, EPOCH + 0.0006, 0.05)
    buffer.push(Reading.create([4], EPOCH + 0.002))
    reading = buffer.wait_for_stamp(after, EPOCH + 0.0024, 1.0)
    assert int(reading.value[0]) == 4


def test_wait_for_stamp_reports_lost_values() -> None:
    """A value pushed out of a full buffer is reported as possibly lost."""
    buffer = FrameBuffer(2)
    after = buffer.count
    for index in range(4):
        buffer.push(Reading.create([index], float(index)))
    buffer.push_error("Device timeout")
    with pytest.raises(TimeoutError, match="2 lost.*Device timeout"):
        buffer.wait_for_stamp(after, 0.0, 0.05)


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
