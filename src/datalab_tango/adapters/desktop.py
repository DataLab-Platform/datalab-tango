"""DataLab Desktop plugin adapter."""

from __future__ import annotations

from datalab.plugins import PluginBase, PluginCapability, PluginInfo

from .. import PLUGIN_DESCRIPTION, PLUGIN_ID, PLUGIN_NAME, __version__
from ..instrument import TANGO_INSTRUMENT_TOOL, TangoInstrument

#: Icon of the plugin, its welcome tile and its instrument
PLUGIN_ICON = "datalab_tango:icons/tango.svg"


class TangoPlugin(PluginBase):
    """Expose TANGO device attributes as DataLab instruments."""

    PLUGIN_INFO = PluginInfo(
        id=PLUGIN_ID,
        name=PLUGIN_NAME,
        version=__version__,
        description=PLUGIN_DESCRIPTION,
        icon=PLUGIN_ICON,
        capabilities=(PluginCapability.APPLICATION,),
        documentation_url="https://github.com/DataLab-Platform/datalab-tango",
    )
    TOOLS = (TANGO_INSTRUMENT_TOOL,)

    def tango_instrument(self) -> TangoInstrument:
        """Return a new TANGO instrument."""
        return TangoInstrument()

    def create_actions(self) -> None:
        """The instrument is listed by DataLab with the plugin tools."""
