"""DataLab Desktop adapter: plugin declaration and instrument window."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from datalab.env import execenv
from datalab.plugins import PluginCapability
from datalab.tests import datalab_test_app_context
from sigima.objects import get_experimental_source
from support.fake_backend import FakeBackend, FakeDevice, write_profile

from datalab_tango import PLUGIN_ID, __version__
from datalab_tango.adapters.desktop import TangoPlugin
from datalab_tango.instrument import TangoInstrument


def test_plugin_descriptor() -> None:
    """The entry point declares one instrument tool, listed in both panels."""
    assert TangoPlugin.get_plugin_id() == PLUGIN_ID
    assert TangoPlugin.PLUGIN_INFO.version == __version__
    assert TangoPlugin.PLUGIN_INFO.capabilities == frozenset(
        {PluginCapability.APPLICATION}
    )
    (tool,) = TangoPlugin.TOOLS
    assert (tool.instrument, tool.object_type) == ("tango_instrument", None)


def test_instrument_window_acquires_into_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window shows the device, acquires into a new group, then disconnects."""
    device = FakeDevice()
    instrument = TangoInstrument(lambda: FakeBackend(device))
    instrument.settings.profile = write_profile(tmp_path / "bench.json")
    instrument.settings.mode = "trigger"
    with (
        execenv.context(unattended=True),
        datalab_test_app_context(console=False, exec_loop=False) as main,
    ):
        plugin = TangoPlugin()
        plugin.main = main
        monkeypatch.setattr(plugin, "tango_instrument", lambda: instrument)
        window = plugin.launch_tool("tango-instrument")
        assert window.wait_until_idle()
        assert len(window.items) == 1
        assert device.connections == 1

        window.acquire()
        assert window.wait_until_idle()
        group = main.imagepanel.objmodel.get_groups()[-1]
        (image,) = group.get_objects()
        assert group.title == "Bench camera - frame - acquisition 001"
        assert np.all(image.data == 1)
        assert get_experimental_source(image)["entry"] == "frame"

        window.close()
        assert window.wait_closed()
        assert device.connections == 0
