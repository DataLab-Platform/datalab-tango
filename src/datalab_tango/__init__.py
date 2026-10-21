"""DataLab plugin package."""

PLUGIN_DESCRIPTION = (
    "Observe TANGO device attributes live and acquire them as signals or images"
)
PLUGIN_ID = "org.datalab.tango"
PLUGIN_NAME = "TANGO Instruments"
__version__ = "0.1.0"

__all__ = [
    "PLUGIN_DESCRIPTION",
    "PLUGIN_ID",
    "PLUGIN_NAME",
    "__version__",
]
