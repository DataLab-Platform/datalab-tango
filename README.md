# <img src="src/datalab_tango/icons/tango.svg" alt="" width="48" align="absmiddle"> TANGO Instruments

A [DataLab](https://datalab-platform.com/) plugin to observe [TANGO](https://www.tango-controls.org/) device attributes live and acquire them as signals or images, ready for DataLab's processing.

> **Example plugin.** This plugin shows how DataLab can work with TANGO-controlled instruments. It is a demonstration, not a finished or supported feature: its scope is limited to what is described below, it has been validated only with simulated devices served by PyTango (real devices are described by profiles, untested so far), and its interface may change without notice.

## What it does

- **TANGO instrument...** opens a DataLab instrument window: a live view of the selected attribute, refreshed in **Live** mode, and its settings.
- A spectrum (`SPECTRUM` attribute) becomes a signal, an image (`IMAGE` attribute) an image, with the units and axis calibrations of the device profile. Integer counts are kept exactly.
- **Acquire** copies values into a new group of the workspace, in one of three modes: the last received value, the value measured after running the trigger command of the profile, or the next received values (a series fails, instead of silently missing values, if some were lost).
- Each acquired object records its origin in its `experimental_source` metadata: device, attribute, device and reception times, quality and profile. A saved workspace reopens without the device or the plugin.
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
| `trigger` | Command (and optional scalar `argument`) measuring a new value | none |
| `reception` | `polling`: periodic reads, a value being kept when its device time stamp changes; `events`: change events pushed by the device | `polling` |
| `polling_interval_ms`, `timeout_ms` | Interval between reads, timeout of device calls | 200, 3000 |
| `buffer_size` | Number of received values kept until they are acquired | 16 |

The packaged [example profile](src/datalab_tango/profiles/example_camera.json) is a starting point.

## Trying without hardware

```bash
python -m datalab_tango.simulation profiles
```

This starts a TANGO device server without database, on this computer, with a simulated oscilloscope and a simulated camera acquiring continuously, and writes their profiles in the `profiles` folder: open one of them in **TANGO instrument...**. The devices use the simulators of the Pulse & Transient and Camera characterization plugins when these are installed, and simple synthetic data otherwise. Stop the server with Ctrl+C.

## Installation

The plugin needs DataLab 1.4 or later (not released yet) and PyTango. PyTango is a compiled package: install the plugin with pip or conda in the Python environment of DataLab. The plugin catalog of DataLab, which installs pure-Python plugins only, cannot install it.

```bash
pip install git+https://github.com/DataLab-Platform/datalab-tango.git
```

DataLab-Web is not supported: TANGO cannot be reached from a browser.

## Documentation

- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## License

BSD 3-Clause, see [LICENSE](LICENSE).
