# Changelog

All notable changes to this project will be documented in this file.

## [0.1.1] - 2026-11-13

Requirements are unchanged: Python 3.10 or later, DataLab 1.4 or later and PyTango 9.5.1 or later.

- **Simulated TANGO devices** tool: the simulated oscilloscope and camera, served from DataLab without command line while the instrument window is open, in a child process on a free port; it stops when the window closes (including on plugin reload and DataLab exit), or by itself if DataLab ends abruptly. The tool comes first in the Applications panel and in the plugin's submenu of the **Plugins** menu. Not available in standalone DataLab, which is not qualified.
- Simulated devices start faster: their simulators are imported while the device server starts.
- The README tells how to install the plugin from the [DataLab plugin catalog](https://datalab-platform.com/plugins/), after installing PyTango in DataLab's Python environment.
- Releases are published from a draft release prepared by the CI, with the wheel, its `SHA256SUMS` and its build provenance attestation (see `RELEASING.md`).

## [0.1.0] - 2026-11-07

Python 3.10 or later and PyTango 9.5.1 or later are required. PyTango 9.5.0 is excluded because its Windows wheel can be installed with NumPy 2 even though its native extension is incompatible.

First version of the TANGO Instruments example plugin: a demonstration of DataLab with TANGO-controlled instruments, not a finished or supported feature.

- **TANGO instrument** tool: live view of a device attribute (spectrum as a signal, image as an image) in DataLab's instrument window, with calibrated axes and units, and acquisition into the workspace.
- Acquisitions accumulate in the current group of the panel by default, instead of creating a group for each of them; the **New group** option of the instrument window restores one group per acquisition, and DataLab remembers this choice.
- Acquisition modes: last received value, value measured after the trigger command of the profile, or series of the next received values, refused if values were lost.
- Triggered value identified by its device time stamp when the trigger command returns it (`"returns": "time_stamp"` in the profile), instead of taking the first value received after the command, which may be a value measured on its own by a free-running device; values measured within the same millisecond cannot be told apart when the device time stamps are truncated to the millisecond (e.g. on Windows); the origin of a triggered value records how it was identified.
- Device profiles (JSON): device address, attributes, units and axis calibrations, trigger command, reception by periodic reads or change events, timeouts and buffer size.
- Origin of each acquired object in its `experimental_source` metadata (device, attribute, times, quality, profile); integer counts converted exactly.
- Connection opened with the instrument window and released when it closes, including on plugin reload and DataLab exit; device calls never run in DataLab's user interface thread.
- Simulated oscilloscope and camera served by `python -m datalab_tango.simulation`, with their profiles, to try the plugin without hardware; their trigger commands return the time stamp of the value they measure.
- Fixed simulated device startup failing on slower machines, especially on Windows, by allowing 60 s instead of PyTango's default of 7 s.
- Plugin icon, shown on its welcome page tile and its instrument tool.
- Continuous integration: lint and tests on Linux and Windows, with simulated devices and PyTango 9.5.1/NumPy 1, PyTango 10.0.0/NumPy 2 and the latest PyTango compatible with NumPy 2.
