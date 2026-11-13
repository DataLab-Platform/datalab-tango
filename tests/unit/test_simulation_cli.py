"""Simulation command startup and profile generation."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("tango.test_context")

from datalab_tango import simulation  # noqa: E402
from datalab_tango.core.simulated import DEVICES, READY_MARKER  # noqa: E402


def test_main_startup_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The command allows slow server startup and still writes both profiles."""
    context = MagicMock()
    context.__enter__.return_value = context
    addresses = {
        simulation.SCOPE_NAME: "tango://localhost:12345/sim/oscilloscope/1#dbase=no",
        simulation.CAMERA_NAME: "tango://localhost:12345/sim/camera/1#dbase=no",
    }
    context.get_device_access.side_effect = addresses.__getitem__
    factory = MagicMock(return_value=context)
    monkeypatch.setattr(simulation, "MultiDeviceTestContext", factory)

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(simulation, "time", SimpleNamespace(sleep=interrupt))
    folder = tmp_path / "profiles"
    simulation.main(str(folder))

    factory.assert_called_once_with(
        (
            {
                "class": simulation.SimulatedOscilloscope,
                "devices": [{"name": simulation.SCOPE_NAME}],
            },
            {
                "class": simulation.SimulatedCamera,
                "devices": [{"name": simulation.CAMERA_NAME}],
            },
        ),
        process=True,
        timeout=60.0,
    )
    for filename, name in [
        ("simulated_oscilloscope.json", simulation.SCOPE_NAME),
        ("simulated_camera.json", simulation.CAMERA_NAME),
    ]:
        profile = json.loads((folder / filename).read_text(encoding="utf-8"))
        assert profile["device"] == addresses[name]
    context.__exit__.assert_called_once_with(None, None, None)


def test_main_until_stdin_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Started by DataLab, the simulation announces the profiles on one line,
    then serves the devices until its standard input is closed."""
    context = MagicMock()
    context.__enter__.return_value = context
    context.get_device_access.side_effect = lambda name: (
        f"tango://localhost:12345/{name}#dbase=no"
    )
    monkeypatch.setattr(
        simulation, "MultiDeviceTestContext", MagicMock(return_value=context)
    )
    monkeypatch.setattr(simulation.sys, "stdin", io.StringIO("ignored\n"))
    folder = tmp_path / "profiles"
    simulation.main(str(folder), until_stdin_closes=True)

    (line,) = capsys.readouterr().out.splitlines()
    assert line.startswith(READY_MARKER)
    profiles = json.loads(line[len(READY_MARKER) :])
    assert set(profiles) == set(DEVICES)
    camera = json.loads(Path(profiles["camera"]).read_text(encoding="utf-8"))
    assert camera["device"].endswith(f"/{simulation.CAMERA_NAME}#dbase=no")
    context.__exit__.assert_called_once_with(None, None, None)


def test_command_line_arguments() -> None:
    """The folder defaults to the current one; DataLab adds an option."""
    arguments = simulation.parse_arguments([])
    assert (arguments.folder, arguments.until_stdin_closes) == (".", False)
    arguments = simulation.parse_arguments(["--until-stdin-closes", "profiles"])
    assert (arguments.folder, arguments.until_stdin_closes) == ("profiles", True)
