# ADR-002: Use a bounded passive Raspberry Pi 5 runtime profile

- Status: Accepted
- Date: 2026-09-02

## Context

The station must also run on a Raspberry Pi 5 with 2 GB RAM and no fan. The
camera delivers 2560x1440 MJPG at 15 FPS in the 5V/3A profile; continuously copying,
drawing and processing every full-resolution frame wastes memory bandwidth and
creates sustained heat. A passive Pi can protect itself through firmware
throttling, but reaching that point makes station latency unpredictable.

## Decision

Add an automatically selected `rpi5-passive` runtime profile while keeping the
measurement geometry and product rules unchanged.

The profile:

1. Keeps camera capture at 2560x1440 MJPG, capped at 15 FPS.
2. Uses a one-frame latest-frame buffer, V4L2 on Linux, and no queued old frames.
3. Resizes a display copy to 1024x600 and caps HDMI refresh at 10 FPS.
4. Keeps at most one analysis frame in flight. The five-frame burst stores only
   compact measurement results and inserts a 120 ms idle gap between analyses.
5. Limits OpenCV to one thread and, through `run_pi5.sh`, confines the process
   to CPU cores 0-1 when `taskset` is available.
6. Locates the seam/ROI on a 1024 px copy, then computes profiles only inside
   the selected full-resolution ROI to preserve count accuracy.
7. Samples `/sys/class/thermal/thermal_zone0/temp` and `/proc/meminfo` at low
   frequency. It reduces preview load at 70 C and refuses to start another
   measurement at 75 C or when available RAM is below 512 MB. After one
   accepted five-frame burst, processing sleeps until the scene changes.
8. Reads `vcgencmd get_throttled`; current under-voltage/throttling pauses the
   worker and lowers display refresh to 3 FPS.
9. Disables OpenCL probing and bounds OpenMP/OpenBLAS worker pools on Raspberry
   Pi 5.

## Consequences

- The UI remains responsive because slow processing cannot build a camera-frame
  backlog.
- Peak burst memory is roughly one retained full frame rather than a list of
  full frames.
- Thermal protection is proactive, but it cannot replace a passive heatsink,
  adequate airflow, a stable power supply, or testing on the final enclosure.
- The profile can be forced with `--runtime-profile rpi5-passive` or bypassed
  for comparison with `--runtime-profile desktop`.
- Final performance and temperature must be measured on the real Pi, camera,
  display and enclosure. Desktop timings are not Pi acceptance data.
