"""Simulated devices served by a child process, to try the plugin without hardware.

:class:`SimulatedDevices` runs ``python -m datalab_tango.simulation
--until-stdin-closes <folder>`` in a child process, with the Python interpreter
and the import path of the current process: a TANGO device server without
database starts on this computer (on a free port) with a simulated oscilloscope
and a simulated camera, and their profiles are written in a temporary folder.
The child process announces the profiles on its output once the devices are
served, then serves them until its standard input is closed.

:meth:`SimulatedDevices.stop` closes this input, so that the device server stops
cleanly, and kills the child processes if they do not stop in time. If the
current process ends without stopping the devices (even abruptly), the operating
system closes the input of the child process, which stops the devices too.

A standalone (frozen) application has no Python interpreter to run the child
process: simulated devices are not supported there (standalone installations of
DataLab are not qualified for this plugin).
"""

from __future__ import annotations

import atexit
import collections
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import weakref
from collections.abc import Callable, Sequence
from pathlib import Path

__all__ = [
    "DEVICES",
    "READY_MARKER",
    "SimulatedDevices",
    "simulation_command",
]

#: Prefix of the line announcing that the simulated devices are served, followed
#: by a JSON object giving the profile file of each device (see :data:`DEVICES`)
READY_MARKER = "datalab-tango-simulation-ready "
#: Keys of the simulated devices in the announcement
DEVICES = ("oscilloscope", "camera")
#: Longest wait for the simulated devices to be served (s): the device server
#: alone is given 60 s to start, which is needed on some machines
STARTUP_TIMEOUT = 90.0
#: Longest wait for the simulated devices to stop cleanly before being killed (s)
STOP_TIMEOUT = 20.0
#: Number of output lines of the child process kept to report a failure
OUTPUT_LINES = 20

FROZEN_MESSAGE = (
    "Simulated devices need a Python environment: they cannot be started from a "
    "standalone DataLab, which is not qualified for this plugin. Run "
    "'python -m datalab_tango.simulation profiles' in a Python environment with "
    "PyTango, then open the profiles in 'TANGO instrument...'"
)

#: Simulated devices running, stopped when the current process exits
_RUNNING: weakref.WeakSet[SimulatedDevices] = weakref.WeakSet()


def simulation_command(folder: Path) -> list[str]:
    """Return the command serving the simulated devices until stdin is closed.

    On Windows, the windowless interpreter is preferred: neither the child
    process nor the device server process it starts opens a console window.

    Args:
        folder: folder where the device profiles are written

    Raises:
        ValueError: in a standalone (frozen) application
    """
    if getattr(sys, "frozen", False):
        raise ValueError(FROZEN_MESSAGE)
    executable = Path(sys.executable)
    if sys.platform == "win32":
        windowless = executable.with_name("pythonw.exe")
        if windowless.is_file():
            executable = windowless
    return [
        str(executable),
        "-m",
        "datalab_tango.simulation",
        "--until-stdin-closes",
        str(folder),
    ]


def _child_environment() -> dict[str, str]:
    """Return the environment of the child process: that of the current process,
    with its import path (e.g. plugins loaded from a folder, not installed)."""
    environment = dict(os.environ)
    paths: list[str] = []
    for entry in sys.path:
        path = os.path.abspath(entry or os.curdir)
        if os.path.exists(path) and path not in paths:
            paths.append(path)
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def _kill_tree(process: subprocess.Popen) -> None:
    """Kill a child process and the processes it started."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        process.kill()
    except OSError:
        pass


class _Launch:
    """Child process serving the simulated devices, and what it announced.

    Args:
        process: child process
        folder: temporary folder of the profiles
    """

    def __init__(self, process: subprocess.Popen, folder: Path) -> None:
        self.process = process
        self.folder = folder
        self.profiles: dict[str, Path] = {}
        self.output: collections.deque[str] = collections.deque(maxlen=OUTPUT_LINES)
        self.ready = threading.Event()
        self.reader = threading.Thread(
            target=self._read_output, name="TANGO simulation output", daemon=True
        )
        self.reader.start()

    def _read_output(self) -> None:
        """Read the output of the child process until it ends (reader thread).

        The output is always read, so that the child process never blocks on a
        full pipe.
        """
        try:
            for line in self.process.stdout:
                line = line.rstrip()
                if line.startswith(READY_MARKER) and not self.ready.is_set():
                    try:
                        profiles = json.loads(line[len(READY_MARKER) :])
                        self.profiles = {
                            str(key): Path(value) for key, value in profiles.items()
                        }
                    except (ValueError, AttributeError):
                        self.output.append(line)
                        continue
                    self.ready.set()
                elif line:
                    self.output.append(line)
            self.process.stdout.close()
        except (OSError, ValueError):
            pass

    def wait_until_ready(self, timeout: float) -> str | None:
        """Wait until the devices are served; return why not, if they are not."""
        deadline = time.monotonic() + timeout
        while not self.ready.wait(0.1):
            code = self.process.poll()
            if code is not None:
                # Let the output reader store the last lines
                self.reader.join(2.0)
                if self.ready.is_set():
                    break
                details = "\n".join(self.output)
                return f"Simulated devices stopped while starting (code {code})" + (
                    f":\n{details}" if details else ""
                )
            if time.monotonic() > deadline:
                return f"Simulated devices did not start within {timeout:g} s"
        missing = [key for key in DEVICES if key not in self.profiles]
        if missing:
            return f"Simulated devices did not announce: {', '.join(missing)}"
        return None

    def stop(self, timeout: float) -> None:
        """Stop the child process, killing it after a timeout, and remove the
        profiles."""
        process = self.process
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(process)
            try:
                process.wait(5.0)
            except subprocess.TimeoutExpired:
                pass
        shutil.rmtree(self.folder, ignore_errors=True)


class SimulatedDevices:
    """Simulated oscilloscope and camera, served by a child process.

    :meth:`start` waits for the devices without blocking :meth:`stop`: devices
    stopped while starting (e.g. when Python exits) make :meth:`start` fail.

    Args:
        command_factory: returns the command serving the devices in a folder
         (tests use a fake one)
        startup_timeout: longest wait for the devices to be served (s)
        stop_timeout: longest wait for the devices to stop cleanly (s)
    """

    def __init__(
        self,
        command_factory: Callable[[Path], Sequence[str]] = simulation_command,
        startup_timeout: float = STARTUP_TIMEOUT,
        stop_timeout: float = STOP_TIMEOUT,
    ) -> None:
        self._command_factory = command_factory
        self.startup_timeout = startup_timeout
        self.stop_timeout = stop_timeout
        #: Profile file of each simulated device, once served
        self.profiles: dict[str, Path] = {}
        self._launch: _Launch | None = None
        self._lock = threading.Lock()

    @property
    def pid(self) -> int | None:
        """Process ID of the child process, while it runs"""
        launch = self._launch
        return None if launch is None else launch.process.pid

    def is_running(self) -> bool:
        """Return True if the devices are served."""
        launch = self._launch
        return (
            launch is not None
            and launch.process.poll() is None
            and launch.ready.is_set()
        )

    def start(self) -> dict[str, Path]:
        """Serve the simulated devices, if not served yet.

        Returns:
            Profile file of each simulated device

        Raises:
            ValueError: if the devices cannot be served (with a user-facing
             message)
        """
        with self._lock:
            if self.is_running():
                return self.profiles
            self._stop()
            launch = self._launch = self._spawn()
        error = launch.wait_until_ready(self.startup_timeout)
        with self._lock:
            if self._launch is not launch:
                error = error or "Simulated devices were stopped while starting"
            elif error is not None:
                self._stop()
            else:
                self.profiles = dict(launch.profiles)
                return self.profiles
        raise ValueError(error)

    def _spawn(self) -> _Launch:
        """Start the child process serving the devices in a temporary folder."""
        folder = Path(tempfile.mkdtemp(prefix="datalab-tango-simulation-"))
        try:
            command = list(self._command_factory(folder))
            options: dict[str, object] = {}
            if sys.platform == "win32":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            else:
                options["start_new_session"] = True
            process = subprocess.Popen(  # pylint: disable=consider-using-with
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=folder,
                env=_child_environment(),
                text=True,
                encoding="utf-8",
                errors="replace",
                **options,
            )
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        _RUNNING.add(self)
        return _Launch(process, folder)

    def stop(self) -> None:
        """Stop serving the devices, and remove their profiles.

        Does nothing if the devices are not served.
        """
        with self._lock:
            self._stop()

    def _stop(self) -> None:
        """Stop the child process and remove the temporary folder."""
        launch, self._launch = self._launch, None
        self.profiles = {}
        _RUNNING.discard(self)
        if launch is not None:
            launch.stop(self.stop_timeout)


@atexit.register
def stop_all() -> None:
    """Stop all the simulated devices still served (e.g. when Python exits)."""
    for devices in list(_RUNNING):
        devices.stop()
