"""DataLab Desktop adapter: plugin declaration and instrument window."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import numpy as np
import pytest
from datalab.config import Conf
from datalab.env import execenv
from datalab.plugins import PluginCapability
from datalab.tests import datalab_test_app_context
from sigima.objects import get_experimental_source
from support.fake_backend import (
    FakeBackend,
    FakeDevice,
    FakeSimulatedDevices,
    write_profile,
)

from datalab_tango import PLUGIN_ID, __version__
from datalab_tango.adapters.desktop import PLUGIN_ICON, TangoPlugin
from datalab_tango.instrument import SimulatedTangoInstrument, TangoInstrument


def test_plugin_descriptor() -> None:
    """The entry point declares two instrument tools, listed in both panels:
    the simulated devices first, which work without hardware."""
    assert TangoPlugin.get_plugin_id() == PLUGIN_ID
    assert TangoPlugin.PLUGIN_INFO.version == __version__
    assert TangoPlugin.PLUGIN_INFO.capabilities == frozenset(
        {PluginCapability.APPLICATION}
    )
    assert [
        (tool.id, tool.instrument, tool.object_type) for tool in TangoPlugin.TOOLS
    ] == [
        ("tango-simulation", "simulated_tango_instrument", None),
        ("tango-instrument", "tango_instrument", None),
    ]
    assert isinstance(TangoPlugin().simulated_tango_instrument(), TangoInstrument)


def test_plugin_icon() -> None:
    """The plugin, its welcome tile and its instruments use the shipped icon."""
    package, path = PLUGIN_ICON.split(":")
    assert resources.files(package).joinpath(path).is_file()
    assert TangoPlugin.PLUGIN_INFO.icon == PLUGIN_ICON
    assert [tile.icon for tile in TangoPlugin.get_welcome_tiles()] == [PLUGIN_ICON]
    assert [tool.icon for tool in TangoPlugin.get_tools()] == [PLUGIN_ICON] * 2


def test_instrument_window_acquires_into_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window shows the device, acquires into a group, then disconnects.

    Acquisitions accumulate in the current group, unless "New group" is on."""
    device = FakeDevice()
    instrument = TangoInstrument(lambda: FakeBackend(device))
    instrument.settings.profile = write_profile(tmp_path / "bench.json")
    instrument.settings.mode = "trigger"
    with (
        execenv.context(unattended=True),
        Conf.instrument_new_group.context({}),
        datalab_test_app_context(console=False, exec_loop=False) as main,
    ):
        plugin = TangoPlugin()
        plugin.main = main
        monkeypatch.setattr(plugin, "tango_instrument", lambda: instrument)
        window = plugin.launch_tool("tango-instrument")
        assert window.wait_until_idle()
        assert len(window.items) == 1
        assert device.connections == 1
        assert not window.new_group_box.isChecked()

        window.acquire()
        assert window.wait_until_idle()
        group = main.imagepanel.objmodel.get_groups()[-1]
        (image,) = group.get_objects()
        assert group.title == "Bench camera - frame - acquisition 001"
        assert np.all(image.data == 1)
        assert get_experimental_source(image)["entry"] == "frame"

        window.acquire()
        assert window.wait_until_idle()
        assert main.imagepanel.objmodel.get_groups() == [group]
        assert len(group.get_objects()) == 2

        window.new_group_box.setChecked(True)
        window.acquire()
        assert window.wait_until_idle()
        groups = main.imagepanel.objmodel.get_groups()
        assert len(groups) == 2
        assert groups[-1].title == "Bench camera - frame - acquisition 003"

        window.close()
        assert window.wait_closed()
        assert device.connections == 0


def test_simulated_devices_window_starts_and_stops_the_devices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The simulated devices window shows the oscilloscope at once, then stops
    the devices when it closes."""
    device = FakeDevice()
    log: list[str] = []
    instrument = SimulatedTangoInstrument(
        lambda: FakeBackend(device), lambda: FakeSimulatedDevices(tmp_path, log)
    )
    with (
        execenv.context(unattended=True),
        Conf.instrument_new_group.context({}),
        datalab_test_app_context(console=False, exec_loop=False) as main,
    ):
        plugin = TangoPlugin()
        plugin.main = main
        monkeypatch.setattr(plugin, "simulated_tango_instrument", lambda: instrument)
        window = plugin.launch_tool("tango-simulation")
        assert window.windowTitle() == "Simulated TANGO devices"
        assert window.wait_until_idle()
        assert len(window.items) == 1 and log == ["start"]

        window.acquire()
        assert window.wait_until_idle()
        (signal,) = main.signalpanel.objmodel.get_groups()[-1].get_objects()
        assert get_experimental_source(signal)["entry"] == "spectrum"

        window.close()
        assert window.wait_closed()
        assert log == ["start", "stop"] and device.connections == 0
