"""Qualification of the packaged Desktop demonstration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

from datalab_tango import PLUGIN_ID, __version__

PROJECT_ROOT = Path(__file__).parents[2]


def test_wheel_installs_with_entry_point_and_resources(tmp_path: Path) -> None:
    """The actual wheel exposes its Python-only limits outside the checkout."""
    wheel_dir = tmp_path / "wheel"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", os.fspath(wheel_dir)],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    (wheel,) = wheel_dir.glob("*-py3-none-any.whl")
    install_dir = tmp_path / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            "--target",
            os.fspath(install_dir),
            os.fspath(wheel),
        ],
        check=True,
    )
    probe = """
import importlib
import importlib.metadata as metadata
import importlib.resources as resources
import json

distribution = next(metadata.distributions(path=[INSTALL_DIR]))
entry_points = list(distribution.entry_points)
entry_point = next(point for point in entry_points if point.group == "datalab.plugins")
plugin = entry_point.load()
module = importlib.import_module(plugin.__module__)
package = resources.files("datalab_tango")
print(json.dumps({
    "version": distribution.version,
    "summary": distribution.metadata["Summary"],
    "requires_python": distribution.metadata["Requires-Python"],
    "requires": distribution.requires,
    "groups": [point.group for point in entry_points],
    "entry_point": entry_point.name,
    "module": module.__file__,
    "plugin_id": plugin.get_plugin_id(),
    "description": plugin.PLUGIN_INFO.description,
    "resources": [
        package.joinpath("icons", "tango.svg").is_file(),
        package.joinpath("profiles", "example_camera.json").is_file(),
    ],
}))
""".replace("INSTALL_DIR", repr(os.fspath(install_dir)))
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (os.fspath(install_dir), environment.get("PYTHONPATH", ""))
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["version"] == __version__
    assert result["requires_python"] == ">=3.10"
    assert result["groups"] == ["datalab.plugins"]
    assert result["entry_point"] == "datalab_tango"
    assert result["module"] == os.fspath(
        install_dir / "datalab_tango" / "adapters" / "desktop.py"
    )
    assert result["plugin_id"] == PLUGIN_ID
    for text in (result["summary"], result["description"]):
        assert all(
            word in text.lower() for word in ("demonstration", "python", "standalone")
        )
    assert "msi" in result["summary"].lower()
    assert all(result["resources"])
    requirements = {
        Requirement(raw).name: Requirement(raw) for raw in result["requires"]
    }
    assert Version("1.4.0") in requirements["datalab-platform"].specifier
    assert Version("1.3.0") not in requirements["datalab-platform"].specifier
    assert Version("9.5.1") in requirements["pytango"].specifier
    assert Version("10.0.0") in requirements["pytango"].specifier
    assert Version("9.5.0") not in requirements["pytango"].specifier
