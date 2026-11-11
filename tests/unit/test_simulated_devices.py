"""Simulated devices served by a child process: start, announcement and stop."""

from __future__ import annotations

import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from datalab_tango.core import simulated
from datalab_tango.core.simulated import (
    DEVICES,
    READY_MARKER,
    SimulatedDevices,
    simulation_command,
)

psutil = pytest.importorskip("psutil")

#: Child process announcing profiles, then serving until its input is closed
SERVING = """
for path in profiles.values():
    Path(path).write_text("{}", encoding="utf-8")
print("Starting the simulated devices", flush=True)
print(MARKER + json.dumps(profiles), flush=True)
for _line in sys.stdin:
    pass
"""
#: Child process failing while starting
FAILING = """
print("Device server failed: port in use", flush=True)
sys.exit(3)
"""
#: Child process which never announces its profiles
SILENT = """
time.sleep(60)
"""
#: Child process announcing its profiles, then ignoring that its input closes
STUCK = """
print(MARKER + json.dumps(profiles), flush=True)
time.sleep(60)
"""


class FakeCommand:
    """Command factory running a script in a child process, recording folders."""

    def __init__(self, body: str) -> None:
        header = textwrap.dedent(
            f"""
            import json, sys, time
            from pathlib import Path
            MARKER = {READY_MARKER!r}
            folder = Path(sys.argv[1])
            profiles = {{key: str(folder / (key + ".json")) for key in {DEVICES!r}}}
            """
        )
        self.script = header + textwrap.dedent(body)
        self.folders: list[Path] = []

    def __call__(self, folder: Path) -> list[str]:
        self.folders.append(folder)
        return [sys.executable, "-c", self.script, str(folder)]


def _processes_using(folder: Path) -> list[psutil.Process]:
    """Return the processes whose command line mentions a folder."""
    found = []
    for process in psutil.process_iter(["cmdline"]):
        if any(str(folder) in part for part in process.info["cmdline"] or ()):
            found.append(process)
    return found


def test_devices_are_served_until_stopped() -> None:
    """The announced profiles are given; stopping ends the child process and
    removes the profiles."""
    command = FakeCommand(SERVING)
    devices = SimulatedDevices(command, startup_timeout=30.0)
    try:
        profiles = devices.start()
        assert set(profiles) == set(DEVICES)
        assert all(path.is_file() for path in profiles.values())
        assert devices.is_running()
        pid = devices.pid
        assert devices.start() == profiles and devices.pid == pid
    finally:
        devices.stop()
    assert not devices.is_running() and devices.pid is None
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == "zombie"
    assert not command.folders[0].exists()
    devices.stop()  # Stopping again does nothing


def test_failure_while_starting_is_reported() -> None:
    """A child process stopping while starting gives its exit code and output."""
    command = FakeCommand(FAILING)
    devices = SimulatedDevices(command, startup_timeout=30.0)
    with pytest.raises(ValueError, match=r"code 3[\s\S]*port in use"):
        devices.start()
    assert not devices.is_running()
    assert not command.folders[0].exists()


def test_startup_timeout_kills_the_child_process() -> None:
    """Devices not announced in time are reported, and their process killed."""
    command = FakeCommand(SILENT)
    devices = SimulatedDevices(command, startup_timeout=1.0, stop_timeout=1.0)
    start = time.monotonic()
    with pytest.raises(ValueError, match="did not start within 1 s"):
        devices.start()
    assert time.monotonic() - start < 20.0
    assert not _processes_using(command.folders[0])
    assert not command.folders[0].exists()


def test_child_process_ignoring_stop_is_killed() -> None:
    """A child process which does not stop when its input closes is killed."""
    command = FakeCommand(STUCK)
    devices = SimulatedDevices(command, startup_timeout=30.0, stop_timeout=1.0)
    devices.start()
    pid = devices.pid
    start = time.monotonic()
    devices.stop()
    assert time.monotonic() - start < 15.0
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == "zombie"


def test_devices_still_served_are_stopped_at_exit() -> None:
    """Devices left running are stopped when Python exits."""
    devices = SimulatedDevices(FakeCommand(SERVING), startup_timeout=30.0)
    devices.start()
    simulated.stop_all()
    assert not devices.is_running()


def test_devices_stopped_while_starting() -> None:
    """Stopping does not wait for devices which are starting: they fail to start."""
    command = FakeCommand(SILENT)
    devices = SimulatedDevices(command, startup_timeout=60.0, stop_timeout=1.0)
    errors: list[str] = []

    def start() -> None:
        try:
            devices.start()
        except ValueError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=start)
    thread.start()
    deadline = time.monotonic() + 30.0
    while devices.pid is None and time.monotonic() < deadline:
        time.sleep(0.05)
    start_time = time.monotonic()
    devices.stop()
    thread.join(30.0)
    assert time.monotonic() - start_time < 20.0
    assert len(errors) == 1 and "stopped while starting" in errors[0]
    assert not devices.is_running()
    assert not _processes_using(command.folders[0])
    assert not command.folders[0].exists()


def test_simulation_command(tmp_path: Path) -> None:
    """The child process runs the simulation module with the current Python,
    windowless on Windows."""
    command = simulation_command(tmp_path)
    assert command[1:] == [
        "-m",
        "datalab_tango.simulation",
        "--until-stdin-closes",
        str(tmp_path),
    ]
    executable = Path(command[0])
    assert executable.parent == Path(sys.executable).parent
    if (
        sys.platform == "win32"
        and Path(sys.executable).with_name("pythonw.exe").exists()
    ):
        assert executable.name.lower() == "pythonw.exe"


def test_child_process_imports_like_the_current_process() -> None:
    """The child process gets the import path of the current process, e.g. a
    plugin loaded from its folder by DataLab without being installed."""
    environment = simulated._child_environment()  # pylint: disable=protected-access
    paths = environment["PYTHONPATH"].split(simulated.os.pathsep)
    package_root = str(Path(simulated.__file__).resolve().parents[2])
    assert any(Path(path).resolve() == Path(package_root) for path in paths)


def test_standalone_application_is_not_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A standalone application has no Python interpreter to serve the devices."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    folders: list[Path] = []
    mkdtemp = simulated.tempfile.mkdtemp

    def record_mkdtemp(*args, **kwargs) -> str:
        folders.append(Path(mkdtemp(*args, **kwargs)))
        return str(folders[-1])

    monkeypatch.setattr(simulated.tempfile, "mkdtemp", record_mkdtemp)
    with pytest.raises(ValueError, match="standalone DataLab"):
        SimulatedDevices().start()
    assert folders and not folders[0].exists()
