# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

First version of the TANGO Instruments example plugin: a demonstration of DataLab with TANGO-controlled instruments, not a finished or supported feature.

- **TANGO instrument** tool: live view of a device attribute (spectrum as a signal, image as an image) in DataLab's instrument window, with calibrated axes and units, and acquisition into a new workspace group.
- Acquisition modes: last received value, value measured after the trigger command of the profile, or series of the next received values, refused if values were lost.
- Device profiles (JSON): device address, attributes, units and axis calibrations, trigger command, reception by periodic reads or change events, timeouts and buffer size.
- Origin of each acquired object in its `experimental_source` metadata (device, attribute, times, quality, profile); integer counts converted exactly.
- Connection opened with the instrument window and released when it closes, including on plugin reload and DataLab exit; device calls never run in DataLab's user interface thread.
- Simulated oscilloscope and camera served by `python -m datalab_tango.simulation`, with their profiles, to try the plugin without hardware.
- Plugin icon, shown on its welcome page tile and its instrument tool.
