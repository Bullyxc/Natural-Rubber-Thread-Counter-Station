# ADR-003: Standard CPython 3.13.5 runtime on Raspberry Pi 5

- Status: Accepted
- Date: 2026-09-02

## Context

The deployment Raspberry Pi 5 uses Python 3.13.5. NumPy versions before 2.1 do
not support Python 3.13, and allowing pip to fall back to a source build on a
passively cooled 2 GB Pi creates excessive memory, time and thermal load. The
station also needs OpenCV HighGUI for its fullscreen window, so a headless
OpenCV package is not a valid substitute.

## Decision

1. Keep the source compatible with the original desktop Python 3.10 target and
   add a Pi target of standard CPython `>=3.13.5,<3.14` on a 64-bit OS.
2. Do not target the experimental free-threaded `3.13t` interpreter. OpenCV's
   native kernels already provide parallelism, and the station intentionally
   bounds those workers for thermal control.
3. Install Raspberry Pi OS `python3`, `python3-numpy` and `python3-opencv`
   directly with apt. Do not create a virtual environment and do not modify the
   system interpreter with pip or `--break-system-packages`.
4. Provide `install_pi5_system.sh` as the repeatable system installer and make
   `/usr/bin/python3` the default interpreter in `run_pi5.sh`.
5. Run `pi5_preflight.py` from `run_pi5.sh` before the application. The check
   rejects an incompatible interpreter, 32-bit runtime, missing/incompatible
   libraries, GUI-less OpenCV, and multiple pip OpenCV distributions.

## Consequences

- Deployment uses the distribution's ARM64 binaries and never compiles NumPy or
  OpenCV on the Pi.
- Package upgrades remain owned by apt and cannot be shadowed by a venv or pip
  package with a conflicting OpenCV build.
- `opencv-python-headless` cannot be used for the fullscreen station.
- Syntax and image regression can be tested on the development computer, but
  final acceptance still requires the actual Python 3.13.5 Pi, USB camera,
  display, passive heatsink and enclosure.
