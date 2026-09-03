"""Validate a Raspberry Pi 5 Python 3.13 runtime before starting the station."""

from __future__ import annotations

import argparse
import importlib.metadata
import platform
import struct
import sys
import sysconfig
from pathlib import Path
from typing import Optional

from runtime_control import (
    _read_available_memory_mb,
    _read_temperature_c,
    _read_throttled_flags,
    _memory_total_mb,
    raspberry_pi_model,
)
#

MINIMUM_PYTHON = (3, 13, 5)
MAXIMUM_PYTHON = (3, 14, 0)
MINIMUM_NUMPY = (2, 1, 0)
MINIMUM_OPENCV = (4, 8, 0)
MINIMUM_AVAILABLE_MEMORY_MB = 512.0
MAXIMUM_START_TEMPERATURE_C = 70.0


def parse_version(value: str) -> tuple[int, ...]:
    """Return the leading numeric components of a package version."""
    components: list[int] = []
    for part in value.split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        components.append(int(digits))
    return tuple(components)


def version_at_least(value: str, minimum: tuple[int, ...]) -> bool:
    current = parse_version(value)
    padded = current + (0,) * max(0, len(minimum) - len(current))
    return padded[: len(minimum)] >= minimum


def opencv_gui_backend(build_information: str) -> Optional[str]:
    for line in build_information.splitlines():
        stripped = line.strip()
        if stripped.startswith("GUI:"):
            return stripped.split(":", 1)[1].strip()
    return None


def installed_opencv_packages() -> list[str]:
    names = (
        "opencv-python",
        "opencv-python-headless",
        "opencv-contrib-python",
        "opencv-contrib-python-headless",
    )
    installed: list[str] = []
    for name in names:
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        installed.append(f"{name}=={version}")
    return installed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the Pi 5/Python 3.13.5 station runtime."
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print only the final status and any warnings/errors",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    errors: list[str] = []
    warnings: list[str] = []

    python_version = tuple(sys.version_info[:3])
    python_text = ".".join(str(value) for value in python_version)
    if python_version < MINIMUM_PYTHON or python_version >= MAXIMUM_PYTHON:
        errors.append(
            "ต้องใช้ standard CPython >=3.13.5 และ <3.14 "
            f"(พบ {python_text})"
        )

    if sys.implementation.name != "cpython":
        errors.append(f"ต้องใช้ CPython (พบ {sys.implementation.name})")
    if bool(sysconfig.get_config_var("Py_GIL_DISABLED")):
        errors.append("ยังไม่รองรับ free-threaded CPython 3.13t; ให้ใช้รุ่นปกติ")
    if struct.calcsize("P") * 8 != 64:
        errors.append("ต้องใช้ Raspberry Pi OS 64-bit และ Python 64-bit")

    model = raspberry_pi_model()
    machine = platform.machine()
    if "raspberry pi 5" not in model.lower():
        warnings.append("ไม่พบ Raspberry Pi 5; ผลนี้เป็นการตรวจบนเครื่องอื่น")
    if model and machine.lower() not in {"aarch64", "arm64"}:
        errors.append(f"Pi 5 ต้องใช้ระบบ ARM64 (พบ {machine})")

    try:
        import numpy as np
    except ImportError as error:
        errors.append(f"นำเข้า NumPy ไม่ได้: {error}")
        numpy_version = "missing"
    else:
        numpy_version = np.__version__
        if not version_at_least(numpy_version, MINIMUM_NUMPY):
            errors.append(
                f"Python 3.13 ต้องใช้ NumPy >=2.1 (พบ {numpy_version})"
            )

    try:
        import cv2
    except ImportError as error:
        errors.append(f"นำเข้า OpenCV ไม่ได้: {error}")
        opencv_version = "missing"
        gui_backend = None
    else:
        opencv_version = cv2.__version__
        if not version_at_least(opencv_version, MINIMUM_OPENCV):
            errors.append(f"ต้องใช้ OpenCV >=4.8 (พบ {opencv_version})")
        gui_backend = opencv_gui_backend(cv2.getBuildInformation())
        if not gui_backend or gui_backend.upper() == "NONE":
            errors.append(
                "OpenCV ไม่มี GUI backend; ห้ามใช้แพ็กเกจ headless กับหน้าจอ station"
            )

    opencv_packages = installed_opencv_packages()
    if len(opencv_packages) > 1:
        errors.append(
            "พบ OpenCV หลายแพ็กเกจใน environment เดียว: "
            + ", ".join(opencv_packages)
        )

    cameras = sorted(Path("/dev").glob("video*")) if Path("/dev").exists() else []
    if "raspberry pi 5" in model.lower() and not cameras:
        warnings.append("ไม่พบ /dev/video*; ตรวจสายกล้องและสิทธิ์กลุ่ม video")

    total_memory = _memory_total_mb()
    available_memory = _read_available_memory_mb()
    temperature = _read_temperature_c()
    throttled_flags = _read_throttled_flags()
    if total_memory is not None and total_memory < 1500:
        warnings.append(f"RAM ที่ระบบเห็นต่ำผิดปกติ ({total_memory:.0f} MB)")
    if (
        "raspberry pi 5" in model.lower()
        and available_memory is not None
        and available_memory < MINIMUM_AVAILABLE_MEMORY_MB
    ):
        errors.append(
            f"RAM ว่างเหลือ {available_memory:.0f} MB; ต้องมีอย่างน้อย "
            f"{MINIMUM_AVAILABLE_MEMORY_MB:.0f} MB ก่อนเปิด station"
        )
    if (
        "raspberry pi 5" in model.lower()
        and temperature is not None
        and temperature >= MAXIMUM_START_TEMPERATURE_C
    ):
        errors.append(
            f"CPU ร้อน {temperature:.1f} C; รอให้ต่ำกว่า "
            f"{MAXIMUM_START_TEMPERATURE_C:.0f} C ก่อนเปิด station"
        )
    if (
        "raspberry pi 5" in model.lower()
        and throttled_flags is not None
        and throttled_flags & 0x5
    ):
        errors.append(
            f"พบ power limit ปัจจุบัน (get_throttled=0x{throttled_flags:x}); "
            "ยังไม่เปิด station"
        )
    elif throttled_flags is not None and throttled_flags & 0x50000:
        warnings.append(
            f"เคยเกิด power/throttle event ตั้งแต่บูต "
            f"(get_throttled=0x{throttled_flags:x})"
        )

    if not args.quiet:
        print(f"Board: {model or 'not detected'}")
        print(f"Architecture: {machine}, {struct.calcsize('P') * 8}-bit")
        print(f"Python: {python_text} ({sys.implementation.name})")
        print(f"NumPy: {numpy_version}")
        print(f"OpenCV: {opencv_version}; GUI: {gui_backend or 'not detected'}")
        if opencv_packages:
            print("OpenCV package: " + ", ".join(opencv_packages))
        print(f"Cameras: {', '.join(str(path) for path in cameras) or 'none'}")
        if total_memory is not None:
            print(f"RAM: {available_memory or 0:.0f}/{total_memory:.0f} MB available")
        if temperature is not None:
            print(f"CPU temperature: {temperature:.1f} C")
        if throttled_flags is not None:
            print(f"Power flags: 0x{throttled_flags:x}")

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if errors:
        print("Pi 5 preflight: FAILED")
        return 2
    print(
        f"Pi 5 preflight: OK (Python {python_text}, NumPy {numpy_version}, "
        f"OpenCV {opencv_version})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
