"""Shared camera backend and latest-frame reader for smooth UVC preview."""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import cv2


@dataclass
class CameraInfo:
    backend: str
    requested_width: int
    requested_height: int
    requested_fps: int
    actual_width: int
    actual_height: int
    driver_fps: float


def _backend_candidates() -> list[tuple[int, str]]:
    if sys.platform.startswith("win"):
        # Media Foundation is normally smoother for modern UVC cameras. Keep
        # DirectShow and CAP_ANY as fallbacks for older drivers.
        return [
            (cv2.CAP_MSMF, "MSMF"),
            (cv2.CAP_DSHOW, "DSHOW"),
            (cv2.CAP_ANY, "ANY"),
        ]
    if sys.platform.startswith("linux"):
        # V4L2 gives predictable UVC/MJPG behaviour and buffer controls on Pi OS.
        return [
            (cv2.CAP_V4L2, "V4L2"),
            (cv2.CAP_ANY, "ANY"),
        ]
    return [(cv2.CAP_ANY, "ANY")]


def open_camera_backend(
    camera_index: int,
    width: int,
    height: int,
    fps: int,
    use_mjpg: bool = True,
) -> tuple[cv2.VideoCapture, CameraInfo]:
    last_backend = "NONE"
    for backend, backend_name in _backend_candidates():
        capture = cv2.VideoCapture(camera_index, backend)
        if not capture.isOpened():
            capture.release()
            continue

        last_backend = backend_name
        if use_mjpg:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        capture.set(cv2.CAP_PROP_FPS, fps)
        # Keep latency bounded. Some backends ignore this property.
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        ok, _ = capture.read()
        if not ok:
            capture.release()
            continue

        info = CameraInfo(
            backend=backend_name,
            requested_width=width,
            requested_height=height,
            requested_fps=fps,
            actual_width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            actual_height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            driver_fps=float(capture.get(cv2.CAP_PROP_FPS)),
        )
        return capture, info

    info = CameraInfo(
        backend=last_backend,
        requested_width=width,
        requested_height=height,
        requested_fps=fps,
        actual_width=0,
        actual_height=0,
        driver_fps=0.0,
    )
    return cv2.VideoCapture(), info


class LatestFrameReader:
    """Read the camera continuously while the UI consumes only the newest frame."""

    def __init__(self, capture: cv2.VideoCapture) -> None:
        self.capture = capture
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._frame: Any = None
        self._sequence = 0
        self._timestamp = 0.0
        self.read_fps = 0.0

    def start(self) -> "LatestFrameReader":
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="camera-capture",
            daemon=True,
        )
        self._thread.start()
        return self

    def _capture_loop(self) -> None:
        count = 0
        window_start = time.perf_counter()
        while not self._stop.is_set():
            ok, frame = self.capture.read()
            if not ok or frame is None:
                time.sleep(0.005)
                continue
            now = time.perf_counter()
            with self._condition:
                self._frame = frame
                self._sequence += 1
                self._timestamp = now
                self._condition.notify_all()
            count += 1
            elapsed = now - window_start
            if elapsed >= 1.0:
                self.read_fps = count / elapsed
                count = 0
                window_start = now

    def latest(self, copy: bool = True) -> Optional[tuple[Any, int, float]]:
        with self._lock:
            if self._frame is None:
                return None
            frame = self._frame.copy() if copy else self._frame
            return frame, self._sequence, self._timestamp

    def wait_latest(
        self,
        after_sequence: int = -1,
        timeout: float = 0.05,
        copy: bool = False,
    ) -> Optional[tuple[Any, int, float]]:
        """Wait efficiently for a newer frame instead of busy-polling the CPU."""
        with self._condition:
            if self._frame is None or self._sequence <= after_sequence:
                self._condition.wait(timeout=max(0.0, timeout))
            if self._frame is None:
                return None
            frame = self._frame.copy() if copy else self._frame
            return frame, self._sequence, self._timestamp

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.capture.release()
        self._thread = None


class FpsMeter:
    """Measured display/update FPS, independent of the camera driver's FPS property."""

    def __init__(self, interval_seconds: float = 1.0) -> None:
        self.interval_seconds = interval_seconds
        self._start = time.perf_counter()
        self._count = 0
        self.fps = 0.0

    def tick(self) -> float:
        self._count += 1
        now = time.perf_counter()
        elapsed = now - self._start
        if elapsed >= self.interval_seconds:
            self.fps = self._count / elapsed
            self._count = 0
            self._start = now
        return self.fps


def resize_for_preview(frame: Any, max_width: int) -> Any:
    """Resize only the display copy; the frame saved to disk stays full resolution."""
    if not max_width or frame.shape[1] <= max_width:
        return frame
    scale = max_width / float(frame.shape[1])
    return cv2.resize(
        frame,
        (max_width, max(1, int(round(frame.shape[0] * scale)))),
        interpolation=cv2.INTER_AREA,
    )
