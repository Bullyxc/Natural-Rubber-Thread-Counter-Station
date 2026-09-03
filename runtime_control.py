"""Small, dependency-free runtime policy for desktop and passive Raspberry Pi 5."""

from __future__ import annotations

import os
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip("\x00\n ")
    except OSError:
        return ""


def raspberry_pi_model() -> str:
    """Return the board model without importing OpenCV or other heavy modules."""
    model = _read_text(Path("/proc/device-tree/model"))
    if model:
        return model
    cpuinfo = _read_text(Path("/proc/cpuinfo"))
    for line in cpuinfo.splitlines():
        if line.lower().startswith("model") and ":" in line:
            candidate = line.split(":", 1)[1].strip()
            if "raspberry pi" in candidate.lower():
                return candidate
    return ""


def is_raspberry_pi5() -> bool:
    return "raspberry pi 5" in raspberry_pi_model().lower()


def bootstrap_environment() -> None:
    """Bound native worker pools before NumPy/OpenCV are imported on a Pi 5."""
    if not is_raspberry_pi5():
        return
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MALLOC_ARENA_MAX", "2")
    os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "disabled")


@dataclass
class RuntimeProfile:
    name: str = "desktop"
    board_model: str = ""
    total_memory_mb: Optional[float] = None
    opencv_threads: int = 0
    preview_fps: float = 30.0
    process_max_side: Optional[int] = None
    alignment_max_side: int = 1200
    alignment_fallback_step_deg: float = 2.0
    max_num_strips: Optional[int] = None
    max_burst_frames: Optional[int] = None
    max_preview_width: Optional[int] = None
    sharpness_max_side: int = 720
    temperature_warn_c: float = 65.0
    temperature_hot_c: float = 70.0
    temperature_critical_c: float = 75.0
    memory_floor_mb: float = 512.0
    monitor_interval_seconds: float = 1.0

    @property
    def is_pi_profile(self) -> bool:
        return self.name == "rpi5-passive"

    def apply_to_settings(self, settings: Any) -> None:
        """Apply performance caps while preserving geometry and measurement config."""
        if self.process_max_side is not None:
            settings.process_max_side = min(
                int(settings.process_max_side), int(self.process_max_side)
            )
        if self.max_num_strips is not None:
            settings.num_strips = min(
                int(settings.num_strips), int(self.max_num_strips)
            )
        if self.max_burst_frames is not None:
            settings.burst_frames = min(
                int(settings.burst_frames), int(self.max_burst_frames)
            )
        if self.max_preview_width is not None:
            settings.preview_width = min(
                int(settings.preview_width), int(self.max_preview_width)
            )
        settings.alignment_max_side = int(self.alignment_max_side)
        settings.alignment_fallback_step_deg = float(
            self.alignment_fallback_step_deg
        )


def _memory_total_mb() -> Optional[float]:
    meminfo = _read_text(Path("/proc/meminfo"))
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            try:
                return float(line.split()[1]) / 1024.0
            except (IndexError, ValueError):
                return None
    return None


def build_runtime_profile(
    config: dict[str, Any],
    override: Optional[str] = None,
) -> RuntimeProfile:
    runtime = config.get("runtime", {}) or {}
    requested = str(override or runtime.get("profile", "auto")).lower()
    model = raspberry_pi_model()
    if requested == "auto":
        name = "rpi5-passive" if "raspberry pi 5" in model.lower() else "desktop"
    else:
        name = requested

    if name != "rpi5-passive":
        desktop = runtime.get("desktop", {}) or {}
        return RuntimeProfile(
            name="desktop",
            board_model=model or platform.machine(),
            total_memory_mb=_memory_total_mb(),
            opencv_threads=int(desktop.get("opencv_threads", 0)),
            preview_fps=float(desktop.get("preview_fps", 30.0)),
            alignment_max_side=int(desktop.get("alignment_max_side", 1200)),
            alignment_fallback_step_deg=float(
                desktop.get("alignment_fallback_step_deg", 2.0)
            ),
            sharpness_max_side=int(desktop.get("sharpness_max_side", 720)),
        )

    pi = runtime.get("rpi5_passive", {}) or {}
    return RuntimeProfile(
        name="rpi5-passive",
        board_model=model or "Raspberry Pi 5 (forced profile)",
        total_memory_mb=_memory_total_mb(),
        opencv_threads=max(1, int(pi.get("opencv_threads", 1))),
        preview_fps=max(5.0, float(pi.get("preview_fps", 12.0))),
        process_max_side=max(480, int(pi.get("process_max_side", 960))),
        alignment_max_side=max(480, int(pi.get("alignment_max_side", 1200))),
        alignment_fallback_step_deg=max(
            1.0, float(pi.get("alignment_fallback_step_deg", 2.0))
        ),
        max_num_strips=max(4, int(pi.get("num_strips", 10))),
        max_burst_frames=max(1, int(pi.get("burst_frames", 3))),
        max_preview_width=max(640, int(pi.get("preview_width", 1280))),
        sharpness_max_side=max(320, int(pi.get("sharpness_max_side", 560))),
        temperature_warn_c=float(pi.get("temperature_warn_c", 65.0)),
        temperature_hot_c=float(pi.get("temperature_hot_c", 70.0)),
        temperature_critical_c=float(pi.get("temperature_critical_c", 75.0)),
        memory_floor_mb=max(256.0, float(pi.get("memory_floor_mb", 512.0))),
        monitor_interval_seconds=max(
            0.25, float(pi.get("monitor_interval_seconds", 1.0))
        ),
    )


def configure_opencv(profile: RuntimeProfile) -> None:
    """Enable optimized kernels and prevent worker-pool oversubscription."""
    import cv2

    cv2.setUseOptimized(True)
    if hasattr(cv2, "ocl"):
        cv2.ocl.setUseOpenCL(False)
    if profile.opencv_threads > 0:
        cv2.setNumThreads(profile.opencv_threads)


def _read_temperature_c() -> Optional[float]:
    candidates = (
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/devices/virtual/thermal/thermal_zone0/temp"),
    )
    for path in candidates:
        value = _read_text(path)
        if not value:
            continue
        try:
            temperature = float(value)
        except ValueError:
            continue
        return temperature / 1000.0 if temperature > 1000.0 else temperature
    return None


def _read_available_memory_mb() -> Optional[float]:
    meminfo = _read_text(Path("/proc/meminfo"))
    for line in meminfo.splitlines():
        if line.startswith("MemAvailable:"):
            try:
                return float(line.split()[1]) / 1024.0
            except (IndexError, ValueError):
                return None
    return None


def _read_throttled_flags() -> Optional[int]:
    """Read current/sticky Pi power flags without adding a dependency."""
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            timeout=0.75,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or "=" not in result.stdout:
        return None
    try:
        return int(result.stdout.strip().split("=", 1)[1], 0)
    except ValueError:
        return None


@dataclass
class SystemStatus:
    temperature_c: Optional[float]
    available_memory_mb: Optional[float]
    thermal_level: str
    processing_allowed: bool
    throttled_flags: Optional[int] = None
    reason: str = ""

    def summary(self) -> str:
        fields: list[str] = []
        if self.temperature_c is not None:
            fields.append(f"CPU {self.temperature_c:.1f}C")
        if self.available_memory_mb is not None:
            fields.append(f"RAM {self.available_memory_mb:.0f}MB")
        if self.thermal_level != "normal":
            fields.append(self.thermal_level.upper())
        if self.throttled_flags is not None:
            if self.throttled_flags & 0x5:
                fields.append("POWER LIMIT")
            elif self.throttled_flags & 0x50000:
                fields.append("POWER EVENT SEEN")
        return " | ".join(fields)


class SystemMonitor:
    """Low-cost temperature/RAM guard used only for the passive Pi profile."""

    def __init__(self, profile: RuntimeProfile) -> None:
        self.profile = profile
        self._last_sample = 0.0
        self._status = SystemStatus(None, None, "normal", True)

    def sample(self, force: bool = False) -> SystemStatus:
        if not self.profile.is_pi_profile:
            return self._status
        now = time.monotonic()
        if (
            not force
            and now - self._last_sample < self.profile.monitor_interval_seconds
        ):
            return self._status
        self._last_sample = now
        temperature = _read_temperature_c()
        available = _read_available_memory_mb()
        throttled_flags = _read_throttled_flags()
        if temperature is None:
            level = "normal"
        elif temperature >= self.profile.temperature_critical_c:
            level = "critical"
        elif temperature >= self.profile.temperature_hot_c:
            level = "hot"
        elif temperature >= self.profile.temperature_warn_c:
            level = "warm"
        else:
            level = "normal"

        reasons: list[str] = []
        if level == "critical":
            reasons.append("CPU TOO HOT")
        if available is not None and available < self.profile.memory_floor_mb:
            reasons.append("LOW MEMORY")
        if throttled_flags is not None and throttled_flags & 0x5:
            reasons.append("POWER LIMIT")
        self._status = SystemStatus(
            temperature_c=temperature,
            available_memory_mb=available,
            thermal_level=level,
            processing_allowed=not reasons,
            throttled_flags=throttled_flags,
            reason=" + ".join(reasons),
        )
        return self._status

    def preview_fps(self, status: Optional[SystemStatus] = None) -> float:
        status = status or self.sample()
        base = self.profile.preview_fps
        if status.throttled_flags is not None and status.throttled_flags & 0x5:
            return 3.0
        if status.thermal_level == "critical":
            return max(3.0, base / 4.0)
        if status.thermal_level == "hot":
            return max(5.0, base / 2.0)
        return base

    def processing_threads(self, status: Optional[SystemStatus] = None) -> int:
        status = status or self.sample()
        if status.thermal_level in {"hot", "critical"}:
            return 1
        return max(1, self.profile.opencv_threads)
