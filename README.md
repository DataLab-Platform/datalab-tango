# <img src="src/datalab_tango/icons/tango.svg" alt="" width="48" align="absmiddle"> TANGO Instruments

A [DataLab](https://datalab-platform.com/) plugin to observe [TANGO](https://www.tango-controls.org/) device attributes live and acquire them as signals or images, ready for DataLab's processing.

> **Example plugin.** This plugin shows how DataLab can work with TANGO-controlled instruments. It is a demonstration, not a finished or supported feature: its scope is limited to what is described below, it has been validated only with simulated devices served by PyTango (real devices are described by profiles, untested so far), and its interface may change without notice.

## What it does

The demonstration targets a Python environment with Python 3.10 or later. MSI and standalone DataLab installations are not qualified.

- **TANGO instrument...** opens a DataLab instrument window: a live view of the selected attribute, refreshed in **Live** mode, and its settings.
- **Simulated TANGO devices...** opens the same window on a simulated oscilloscope or camera, served on this computer while the window is open: the plugin can be tried without hardware nor command line (see [Trying without hardware](#trying-without-hardware)).
- A spectrum (`SPECTRUM` attribute) becomes a signal, an image (`IMAGE` attribute) an image, with the units and axis calibrations of the device profile. Integer counts are kept exactly.
- **Acquire** copies values into the workspace, in one of three modes: the last received value, the value measured after running the trigger command of the profile, or the next received values (a series fails, instead of silently missing values, if some were lost). Acquisitions accumulate in the current group of the panel; turn on the **New group** option of the instrument window to add each acquisition to a new group (DataLab remembers this choice).
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

In DataLab, open **Simulated TANGO devices...** from the Applications panel or from the plugin's submenu of the **Plugins** menu: a TANGO device server without database starts on this computer, on a free port, with a simulated oscilloscope and a simulated camera acquiring continuously, and the instrument window shows the selected device live, as a real one. Choose the device and the acquisition mode in the settings, then **Acquire**. Starting the devices takes a few seconds, more on slower machines (DataLab waits up to 90 s).

The device server runs in a child process while the window is open: it stops when the window closes, including when the plugins are reloaded and when DataLab quits, and by itself if DataLab ends abruptly. Its profiles are written in a temporary folder, removed when it stops.

The trigger commands of the simulated devices return the time stamp of the value they measure, so that a triggered acquisition is not mistaken for a free-running one. The devices use the simulators of the Pulse & Transient and Camera characterization plugins when these are installed, and simple synthetic data otherwise.

The same devices can be served from a command line, e.g. for another DataLab or another TANGO client:

```bash
python -m datalab_tango.simulation profiles
```

This writes their profiles in the `profiles` folder: open one of them in **TANGO instrument...**. Stop the server with Ctrl+C. The server is given a 60 s startup timeout, since PyTango's default of 7 s can be too short, especially on Windows. Wait for the profile paths to be printed before connecting from DataLab.

**Simulated TANGO devices...** runs this module with the Python interpreter of DataLab (windowless on Windows) and its import path, so it needs a Python environment. A standalone (MSI) DataLab, which is not qualified for this plugin, has no Python interpreter to run it: the window then tells to serve the devices with the command above, from a Python environment with PyTango.

## Installation

The plugin needs DataLab 1.4 or later and PyTango 9.5.1 or later in a Python environment. The plugin wheel itself is pure Python; PyTango is a native dependency. Only Python environments are in the qualification scope; MSI and standalone DataLab installations are not qualified.

To install it from the [DataLab plugin catalog](https://datalab-platform.com/plugins/), first install PyTango in DataLab's Python environment (for example `pip install "pytango>=9.5.1"`), then open **Plugins > Configure plugins...**, select the **Catalog** tab and click **Install** next to **TANGO Instruments**. The catalog does not distribute PyTango: until it is installed, DataLab 1.4.1 or later shows the requirement instead of the **Install** button, and DataLab 1.4.0 refuses the installation. The standalone application cannot install PyTango, so the plugin is not available there.

On Windows with CPython 3.11, simulated-device acquisitions have been tested with PyTango 9.5.1 and NumPy 1.26.4, and with PyTango 10.0.0 and 10.0.4 and NumPy 2.4.6. PyTango 9.5.1 requires NumPy below 2; PyTango 9.5.0 is excluded because its Windows wheel permits NumPy 2 in its metadata but its native extension is incompatible with it. Other platforms and combinations must be qualified separately.

To prepare a local catalog for a Python environment, put the plugin wheel in a folder and run `datalab-plugin catalog prepare <folder>` from that target environment with Internet access. Distribute the resulting `catalog.json`, plugin wheel and `dependencies` folder together. For **Install from file...**, keep the `dependencies` folder next to the plugin wheel. Native wheels must match the Python/ABI/platform of DataLab; incompatible existing versions are refused and system prerequisites are not installed automatically. Uninstalling the plugin keeps its shared dependencies.

On Windows, very long plugin-store paths can prevent PyTango's native DLLs from loading. If this occurs, install PyTango directly in a Python environment with a shorter path. PyTango has its own LGPL license and includes third-party native libraries; anyone redistributing those dependencies must check their applicable licenses and notices separately from this plugin's BSD license.

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
