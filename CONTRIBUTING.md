# Contributing

## Setup and Checks

Install the project in editable mode, in a Python environment where DataLab 1.4 or later and PyTango are available, then run the checks before submitting a change:

```bash
python -m pip install -e ".[test]"
python -m ruff check .
python -m pytest
```

## Architecture

Dependencies point inward:

```text
adapters -> instrument -> core
```

- `core` holds the connection layer. `profile` validates device profiles; `reception` stores received values in a bounded, thread-safe buffer and reads attributes periodically; `backend` connects to devices (`PyTangoBackend`, the only module importing PyTango, inside its methods); `session` combines them for one attribute; `convert` turns values into Sigima signals and images with their `experimental_source`. The core does not import DataLab.
- `instrument.py` exposes an attribute session as a DataLab instrument (`PluginInstrument`): DataLab calls it outside its user interface thread, opens it with its window and closes it with the window.
- `adapters/desktop.py` declares the plugin and its tool. There is no DataLab-Web adapter.

`tests/unit/test_architecture.py` checks the layer boundaries.

## Tests

- `tests/unit`: profiles, reception, conversion and instrument, with a fake device (`tests/support/fake_backend.py`).
- `tests/integration`: a simulated device served by PyTango's `DeviceTestContext` in another process (`tests/support/devices.py`), reached through the TANGO protocol, and the instrument window in DataLab. These tests receive values by periodic reads: change events depend on the network setup of the test machine.

## Branches

Day-to-day work lands on `develop`, the default branch: open pull requests against it. `main` is the release branch, created at the first release; after that, `develop` is merged into `main` only to cut a release.
