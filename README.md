# <img src="src/datalab_tango/icons/tango.svg" alt="" width="48" align="absmiddle"> TANGO Instruments

A [DataLab](https://datalab-platform.com/) plugin to observe [TANGO](https://www.tango-controls.org/) device attributes live and acquire them as signals or images, ready for DataLab's processing.

> **Example plugin.** This plugin shows how DataLab can work with TANGO-controlled instruments. It is a demonstration, not a finished or supported feature: its scope is limited to what is described below, it has been validated only with simulated devices served by PyTango (real devices are described by profiles, untested so far), and its interface may change without notice.

## What it does

- **TANGO instrument...** opens a DataLab instrument window: a live view of the selected attribute, refreshed in **Live** mode, and its settings.
- A spectrum (`SPECTRUM` attribute) becomes a signal, an image (`IMAGE` attribute) an image, with the units and axis calibrations of the device profile. Integer counts are kept exactly.
- **Acquire** copies values into a new group of the workspace, in one of three modes: the last received value, the value measured after running the trigger command of the profile, or the next received values (a series fails, instead of silently missing values, if some were lost).
- A triggered value is identified as the one measured by the trigger command when this command returns the time stamp of its value (`"returns": "time_stamp"` in the profile): values received meanwhile are ignored, provided that their device time stamps differ from the triggered one by at least the resolution of the device time stamps (1 µs, or 1 ms when they are truncated to the millisecond, e.g. on Windows). Otherwise, the first value received after the command started is taken: with a free-running device, or a value delivered late, it may be another one. The origin of the acquired object tells which (`trigger.synchronization`: `time_stamp` or `first_after_command`).
- Each acquired object records its origin in its `experimental_source` metadata: device, attribute, device and reception times, quality, profile and, for a triggered value, the trigger command and how its value was identified. A saved workspace reopens without the device or the plugin.
- DataLab calls the device outside its user interface thread: a slow or unreachable device does not freeze DataLab, and the connection is released when the window closes.

## Device profiles

A profile is a JSON file describing one device. Site-specific values (device names, calibrations, commands) belong to profiles, never to the code:

```json
{
  "version": 1,
  "name": "Example camera",
  "device": "lab/camera/1",
  "attributes": [
    {"name": "frame", "kind": "image", "unit": "counts", "x": {"step": 6.5, "unit": "µm"}, "y": {"step": 6.5, "unit": "µm"}},
    {"name": "profile", "kind": "signal", "unit": "counts", "x": {"step": 6.5, "unit": "µm"}}
  ],
  "trigger": {"command": "Snap"},
  "reception": "polling",
  "polling_interval_ms": 200,
  "timeout_ms": 3000,
  "buffer_size": 32
}
```

| Field | Meaning | Default |
| --- | --- | --- |
| `device` | TANGO device name (with `TANGO_HOST`), or full address `tango://host:port/domain/family/member` | required |
| `attributes` | Attributes shown and acquired: `kind` is `signal` or `image`; `label`, `unit`, and axis calibrations `x`/`y` (`origin`, `step`, `unit`, `label`) are optional | required |
| `trigger` | Command (and optional scalar `argument`) measuring a new value; `"returns": "time_stamp"` if the command returns the device time stamp (s since the epoch) of the value it measured, so that this value is told apart from the others (an attribute time stamp matches the returned one if it is the same, truncated to the microsecond, or to the millisecond if it is a whole number of milliseconds: values measured within the same millisecond cannot be told apart then) | none |
| `reception` | `polling`: periodic reads, a value being kept when its device time stamp changes, which requires the device to date its values (an attribute not dated by the device gets a new time stamp at every read, so that every read is kept as a new value: use `events` for it); `events`: change events pushed by the device | `polling` |
| `polling_interval_ms`, `timeout_ms` | Interval between reads, timeout of device calls | 200, 3000 |
| `buffer_size` | Number of received values kept until they are acquired | 16 |

The packaged [example profile](src/datalab_tango/profiles/example_camera.json) is a starting point.

## Trying without hardware

```bash
python -m datalab_tango.simulation profiles
```

This starts a TANGO device server without database, on this computer, with a simulated oscilloscope and a simulated camera acquiring continuously, and writes their profiles in the `profiles` folder: open one of them in **TANGO instrument...**. Their trigger commands return the time stamp of the value they measure, so that a triggered acquisition is not mistaken for a free-running one. The devices use the simulators of the Pulse & Transient and Camera characterization plugins when these are installed, and simple synthetic data otherwise. Stop the server with Ctrl+C.

The server is given a 60 s startup timeout, since PyTango's default of 7 s can be too short, especially on Windows. Wait for the profile paths to be printed before connecting from DataLab.

## Installation

The plugin needs DataLab 1.4 or later (not released yet) and PyTango. The plugin wheel itself is pure Python; PyTango is a native dependency. DataLab's dependency-enabled Desktop installer can install it, including in the standalone application, when the catalog supplies compatible PyTango wheels and their transitive dependencies. A complete local catalog works without Internet access: no existing package versions are changed, and added dependencies are activated after restarting DataLab.

To prepare a local catalog, put the plugin wheel in a folder and run `datalab-plugin catalog prepare <folder>` from the target reference environment with Internet access. Distribute the resulting `catalog.json`, plugin wheel and `dependencies` folder together. For **Install from file...**, keep the `dependencies` folder next to the plugin wheel. Native wheels must match the Python/ABI/platform of DataLab; incompatible existing versions are refused and system prerequisites are not installed automatically. Uninstalling the plugin keeps its shared dependencies.

Installing in DataLab's Python environment with pip or conda remains available:

```bash
pip install git+https://github.com/DataLab-Platform/datalab-tango.git
```

DataLab-Web is not supported: TANGO cannot be reached from a browser.

## Documentation

- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## License

BSD 3-Clause, see [LICENSE](LICENSE).
