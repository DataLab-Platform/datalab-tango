"""Simulation command startup and profile generation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("tango.test_context")

from datalab_tango import simulation  # noqa: E402


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
