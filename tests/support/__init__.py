"""Test helpers."""

#: Startup timeout of the device servers of the integration tests (s): PyTango's
#: default (7 s) is too short on some machines, e.g. CI runners
SERVER_STARTUP_TIMEOUT = 60.0
