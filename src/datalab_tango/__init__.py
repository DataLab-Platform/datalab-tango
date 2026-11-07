"""DataLab plugin package."""

PLUGIN_DESCRIPTION = (
    "Demonstration plugin: observe and acquire TANGO device attributes in a Python "
    "environment; MSI and standalone DataLab are not qualified"
)
PLUGIN_ID = "org.datalab.tango"
PLUGIN_NAME = "TANGO Instruments"
__version__ = "0.1.1rc1"

__all__ = [
    "PLUGIN_DESCRIPTION",
    "PLUGIN_ID",
    "PLUGIN_NAME",
    "__version__",
]
