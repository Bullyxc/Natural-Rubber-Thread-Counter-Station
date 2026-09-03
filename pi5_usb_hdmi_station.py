"""Continuous USB-camera station for Raspberry Pi 5 and a 1024x600 HDMI LCD.

The station starts inspection immediately.  It never requires an operator key
to capture or count.  Q/Escape remain available only as maintenance exits.
"""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from runtime_control import bootstrap_environment

bootstrap_environment()

import cv2
import numpy as np

from camera_stream import FpsMeter, LatestFrameReader, open_camera_backend
from dual_background_counter import (
    DualBackgroundConfig,
    DualBackgroundResult,
    analyse_dual_background,
    classify_count_qc,
)
from runtime_control import (
    RuntimeProfile,
    SystemMonitor,
    build_runtime_profile,
    configure_opencv,
)


@dataclass(frozen=True)
class LiveSettings:
    camera_index: int = 0
    camera_width: int = 2560
    camera_height: int = 1440
    camera_fps: int = 15
    screen_width: int = 1024
    screen_height: int = 600
    display_fps: float = 10.0
    analysis_gap_ms: int = 120
    anti_flicker_hz: int = 50
    burst_frames: int = 5
    stable_frames: int = 3
    motion_width: int = 320
    min_count: int = 30
    max_count: int = 50
    locator_max_side: int = 1024
    pixels_per_mm: float = 0.0
    fullscreen: bool = True
    window_title: str = "Thread Counter Station"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LiveSettings":
        section = config.get("pi5_hdmi_station", {}) or {}
        processing = config.get("processing", {}) or {}
        return cls(
            camera_index=int(section.get("camera_index", cls.camera_index)),
            camera_width=int(section.get("camera_width", cls.camera_width)),
            camera_height=int(section.get("camera_height", cls.camera_height)),
            camera_fps=int(section.get("camera_fps", cls.camera_fps)),
            screen_width=max(640, int(section.get("screen_width", cls.screen_width))),
            screen_height=max(360, int(section.get("screen_height", cls.screen_height))),
            display_fps=max(5.0, float(section.get("display_fps", cls.display_fps))),
            analysis_gap_ms=max(
                0, int(section.get("analysis_gap_ms", cls.analysis_gap_ms))
            ),
            anti_flicker_hz=int(
                section.get("anti_flicker_hz", cls.anti_flicker_hz)
            ),
            burst_frames=5,
            stable_frames=3,
            motion_width=max(160, int(section.get("motion_width", cls.motion_width))),
            min_count=max(1, int(section.get("min_count", cls.min_count))),
            max_count=max(2, int(section.get("max_count", cls.max_count))),
            locator_max_side=max(
                640, int(section.get("locator_max_side", cls.locator_max_side))
            ),
            pixels_per_mm=max(
                0.0, float(processing.get("pixels_per_mm", cls.pixels_per_mm))
            ),
            fullscreen=bool(section.get("fullscreen", cls.fullscreen)),
            window_title=str(section.get("window_title", cls.window_title)),
        )


@dataclass(frozen=True)
class ProductPitchRule:
    product_id: str
    name: str
    nominal_count: int
    pitch_mm_min: Optional[float] = None
    pitch_mm_max: Optional[float] = None
    pitch_px_min: Optional[float] = None
    pitch_px_max: Optional[float] = None

    def matches(self, pitch_px: float, pixels_per_mm: float) -> bool:
        if (
            pixels_per_mm > 0
            and self.pitch_mm_min is not None
            and self.pitch_mm_max is not None
        ):
            pitch_mm = pitch_px / pixels_per_mm
            return self.pitch_mm_min <= pitch_mm <= self.pitch_mm_max
        if self.pitch_px_min is not None and self.pitch_px_max is not None:
            return self.pitch_px_min <= pitch_px <= self.pitch_px_max
        return False


@dataclass(frozen=True)
class ProductMatch:
    product_id: str
    name: str
    nominal_count: int


class ProductPitchCatalog:
    def __init__(self, rules: list[ProductPitchRule]) -> None:
        self.rules = rules

    @classmethod
    def load(cls, path: Path) -> "ProductPitchCatalog":
        if not path.exists():
            return cls([])
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        rules = []
        for raw in data.get("products", []):
            nominal = raw.get("nominal_count")
            if nominal is None:
                continue
            rules.append(
                ProductPitchRule(
                    product_id=str(raw.get("id", "UNNAMED")),
                    name=str(raw.get("name", raw.get("id", "UNNAMED"))),
                    nominal_count=int(nominal),
                    pitch_mm_min=_optional_float(raw.get("pitch_mm_min")),
                    pitch_mm_max=_optional_float(raw.get("pitch_mm_max")),
                    pitch_px_min=_optional_float(raw.get("pitch_px_min")),
                    pitch_px_max=_optional_float(raw.get("pitch_px_max")),
                )
            )
        return cls(rules)

    def match(self, pitch_px: float, pixels_per_mm: float) -> Optional[ProductMatch]:
        matches = [
            rule for rule in self.rules if rule.matches(pitch_px, pixels_per_mm)
        ]
        if len(matches) != 1:
            return None
        rule = matches[0]
        return ProductMatch(rule.product_id, rule.name, rule.nominal_count)


@dataclass
class Measurement:
    result: DualBackgroundResult
    frame_width: int
    frame_height: int
    product: Optional[ProductMatch] = None


@dataclass(frozen=True)
class BurstDecision:
    accepted: bool
    count: Optional[int]
    reason: str
    retained_counts: tuple[int, ...] = ()


@dataclass(frozen=True)
class AnalysisTask:
    generation: int
    sequence: int
    frame: np.ndarray


@dataclass(frozen=True)
class AnalysisReply:
    generation: int
    sequence: int
    frame_width: int
    frame_height: int
    result: Optional[DualBackgroundResult]


class AnalysisWorker:
    """Run one analysis at a time without blocking the HDMI preview."""

    def __init__(self, detector_config: DualBackgroundConfig) -> None:
        self.detector_config = detector_config
        self.tasks: queue.Queue[AnalysisTask] = queue.Queue(maxsize=1)
        self.replies: queue.SimpleQueue[AnalysisReply] = queue.SimpleQueue()
        self.stop_event = threading.Event()
        self.busy = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            name="strand-analysis",
            daemon=True,
        )

    def start(self) -> "AnalysisWorker":
        self.thread.start()
        return self

    def submit(self, task: AnalysisTask) -> bool:
        if self.busy.is_set():
            return False
        self.busy.set()
        try:
            self.tasks.put_nowait(task)
        except queue.Full:
            self.busy.clear()
            return False
        return True

    def drain(self) -> list[AnalysisReply]:
        replies = []
        while True:
            try:
                replies.append(self.replies.get_nowait())
            except queue.Empty:
                return replies

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                task = self.tasks.get(timeout=0.10)
            except queue.Empty:
                continue
            try:
                try:
                    result = analyse_dual_background(
                        task.frame, self.detector_config
                    )
                except (ValueError, cv2.error):
                    result = None
                self.replies.put(
                    AnalysisReply(
                        generation=task.generation,
                        sequence=task.sequence,
                        frame_width=task.frame.shape[1],
                        frame_height=task.frame.shape[0],
                        result=result,
                    )
                )
            finally:
                self.tasks.task_done()
                self.busy.clear()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=3.0)


class MotionGate:
    """Noise-aware scene-change detector with a three-frame stability gate."""

    def __init__(self, width: int, stable_frames: int) -> None:
        self.width = width
        self.required = stable_frames
        self.previous: Optional[np.ndarray] = None
        self.motion_history = deque(maxlen=60)
        self.stable_count = 0
        self.score = float("inf")
        self.threshold = 8.0

    def update(self, frame: np.ndarray) -> tuple[bool, bool]:
        height, width = frame.shape[:2]
        scale = self.width / float(width)
        small = cv2.resize(
            frame,
            (self.width, max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        if self.previous is None:
            self.previous = gray
            self.stable_count = 0
            return True, False

        difference = gray.astype(np.int16) - self.previous.astype(np.int16)
        # Auto exposure changes most pixels by the same amount. Remove that
        # global shift so it is not mistaken for physical product movement.
        difference -= int(round(float(np.median(difference))))
        self.score = float(np.mean(np.abs(difference), dtype=np.float64))
        self.previous = gray
        self.motion_history.append(self.score)
        if len(self.motion_history) >= 6:
            history = np.asarray(self.motion_history, dtype=np.float32)
            quiet_limit = float(np.percentile(history, 40))
            quiet = history[history <= quiet_limit]
            if len(quiet) > 0:
                noise = float(np.median(quiet))
                spread = float(np.median(np.abs(quiet - noise)))
                adaptive = noise + max(1.0, 6.0 * spread)
                self.threshold = float(np.clip(adaptive, 2.5, 15.0))

        stationary_now = self.score <= self.threshold
        changed = self.score > max(18.0, self.threshold * 1.8)
        if not stationary_now:
            self.stable_count = 0
        else:
            self.stable_count += 1
        return changed, self.stable_count >= self.required


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def decide_five_frame_counts(counts: list[int]) -> BurstDecision:
    """Apply the confirmed five-frame, Tukey-IQR and median rules."""
    if len(counts) != 5:
        return BurstDecision(False, None, "INCOMPLETE BURST")
    values = np.asarray(counts, dtype=np.float64)
    q1, q3 = np.percentile(values, [25, 75])
    iqr = float(q3 - q1)
    lower = float(q1 - 1.5 * iqr)
    upper = float(q3 + 1.5 * iqr)
    retained = sorted(int(value) for value in values[(values >= lower) & (values <= upper)])
    if len(retained) < 3:
        return BurstDecision(False, None, "TOO MANY OUTLIERS", tuple(retained))
    if len(retained) == 4 and retained[1] != retained[2]:
        return BurstDecision(False, None, "AMBIGUOUS COUNT", tuple(retained))
    median = float(np.median(np.asarray(retained, dtype=np.float64)))
    if not median.is_integer():
        return BurstDecision(False, None, "AMBIGUOUS COUNT", tuple(retained))
    return BurstDecision(True, int(median), "OK", tuple(retained))


def _open_usb_camera(settings: LiveSettings, preferred: Optional[int]):
    first = settings.camera_index if preferred is None else int(preferred)
    candidates = [first] + [index for index in range(6) if index != first]
    last_info = None
    for index in candidates:
        capture, info = open_camera_backend(
            index,
            settings.camera_width,
            settings.camera_height,
            settings.camera_fps,
            use_mjpg=True,
        )
        last_info = info
        if capture.isOpened():
            return capture, info, index
        capture.release()
    raise RuntimeError(
        "USB camera not found"
        if last_info is None
        else f"USB camera not found; last backend={last_info.backend}"
    )


def _apply_v4l2_anti_flicker(camera_index: int, frequency_hz: int) -> None:
    """Select the UVC mains-frequency filter when the camera exposes it."""
    menu_value = {50: 1, 60: 2}.get(int(frequency_hz))
    if menu_value is None:
        print(f"Anti-flicker disabled: unsupported frequency {frequency_hz} Hz")
        return
    device = f"/dev/video{camera_index}"
    try:
        result = subprocess.run(
            [
                "v4l2-ctl",
                "-d",
                device,
                f"--set-ctrl=power_line_frequency={menu_value}",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        print(f"WARNING: Could not set {frequency_hz} Hz anti-flicker: {error}")
        return
    if result.returncode == 0:
        print(f"Camera anti-flicker: {frequency_hz} Hz ({device})")
        return
    detail = (result.stderr or result.stdout).strip().replace("\n", " ")
    print(
        f"WARNING: Camera has no usable {frequency_hz} Hz anti-flicker control"
        + (f": {detail}" if detail else "")
    )


def _letterbox(frame: np.ndarray, width: int, height: int):
    source_height, source_width = frame.shape[:2]
    scale = min(width / float(source_width), height / float(source_height))
    target_width = max(1, int(round(source_width * scale)))
    target_height = max(1, int(round(source_height * scale)))
    resized = cv2.resize(
        frame,
        (target_width, target_height),
        interpolation=cv2.INTER_AREA,
    )
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    offset_x = (width - target_width) // 2
    offset_y = (height - target_height) // 2
    canvas[offset_y : offset_y + target_height, offset_x : offset_x + target_width] = resized
    return canvas, scale, offset_x, offset_y


def _draw_measurement_geometry(
    canvas: np.ndarray,
    measurement: Measurement,
    scale: float,
    offset_x: int,
    offset_y: int,
) -> None:
    result = measurement.result
    seam_top = offset_y + int(round(result.seam_top * scale))
    seam_bottom = offset_y + int(round(result.seam_bottom * scale))
    cv2.rectangle(
        canvas,
        (offset_x, seam_top),
        (offset_x + int(round(measurement.frame_width * scale)) - 1, seam_bottom),
        (0, 180, 255),
        1,
    )
    top = offset_y + int(round(result.top * scale))
    bottom = offset_y + int(round(result.bottom * scale))
    for index in range(result.count):
        left = offset_x + int(round(result.boundaries_x[index] * scale))
        right = offset_x + int(round(result.boundaries_x[index + 1] * scale))
        centre = int(round((left + right) / 2.0))
        cv2.rectangle(canvas, (left, top), (right, bottom), (0, 210, 0), 1)
        cv2.line(canvas, (centre, top), (centre, bottom), (255, 100, 0), 1)


def _draw_hud(
    canvas: np.ndarray,
    measurement: Optional[Measurement],
    state: str,
    progress: int,
    camera_fps: float,
    display_fps: float,
    system_text: str,
    motion_text: str,
) -> None:
    width = canvas.shape[1]
    panel_width = min(width - 20, 620)
    panel_height = 154
    panel_colour = (20, 20, 20)
    status_line = state
    if measurement is not None:
        product = measurement.product
        if product is None:
            product_line = "PRODUCT NO_MATCH"
        else:
            qc_status, qc_reason = classify_count_qc(
                measurement.result.count, product.nominal_count
            )
            product_line = (
                f"{product.name}  EXPECTED {product.nominal_count}  QC {qc_status}"
            )
            if qc_reason:
                product_line += f" - {qc_reason}"
            panel_colour = (25, 115, 25) if qc_status == "PASS" else (20, 20, 175)
        count_text = f"COUNT {measurement.result.count}"
        detail = (
            f"WIDTH {measurement.result.width_px:.0f}px  "
            f"PITCH {measurement.result.pitch_px:.1f}px  "
            f"Q {measurement.result.quality:.2f}"
        )
        if state.startswith("MEASURING"):
            status_line = f"MEASURING {progress}/5"
    else:
        count_text = state
        detail = f"MEASURING {progress}/5" if state == "MEASURING" else ""
        product_line = ""

    overlay = canvas.copy()
    cv2.rectangle(overlay, (10, 10), (10 + panel_width, 10 + panel_height), panel_colour, -1)
    cv2.addWeighted(overlay, 0.90, canvas, 0.10, 0.0, canvas)
    cv2.putText(
        canvas,
        count_text,
        (24, 60),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.35,
        (255, 255, 255),
        3,
        cv2.LINE_AA,
    )
    if detail:
        cv2.putText(
            canvas,
            detail,
            (25, 91),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (230, 230, 230),
            1,
            cv2.LINE_AA,
        )
    if product_line:
        cv2.putText(
            canvas,
            product_line,
            (25, 119),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    cv2.putText(
        canvas,
        status_line,
        (25, 148),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (0, 255, 255),
        1,
        cv2.LINE_AA,
    )
    footer = (
        f"USB {camera_fps:.1f} FPS | DISPLAY {display_fps:.1f} FPS | "
        f"{motion_text}"
    )
    if system_text:
        footer += f" | {system_text}"
    cv2.rectangle(canvas, (0, canvas.shape[0] - 27), (width, canvas.shape[0]), (15, 15, 15), -1)
    cv2.putText(
        canvas,
        footer,
        (12, canvas.shape[0] - 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (210, 210, 210),
        1,
        cv2.LINE_AA,
    )


def _create_window(settings: LiveSettings, windowed: bool) -> None:
    cv2.namedWindow(settings.window_title, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(
        settings.window_title, settings.screen_width, settings.screen_height
    )
    if settings.fullscreen and not windowed:
        cv2.setWindowProperty(
            settings.window_title,
            cv2.WND_PROP_FULLSCREEN,
            cv2.WINDOW_FULLSCREEN,
        )


def run_station(
    settings: LiveSettings,
    runtime: RuntimeProfile,
    catalog: ProductPitchCatalog,
    camera_override: Optional[int],
    windowed: bool,
) -> int:
    capture, camera_info, camera_index = _open_usb_camera(settings, camera_override)
    _apply_v4l2_anti_flicker(camera_index, settings.anti_flicker_hz)
    reader = LatestFrameReader(capture).start()
    monitor = SystemMonitor(runtime)
    motion = MotionGate(settings.motion_width, settings.stable_frames)
    detector_config = DualBackgroundConfig(
        min_count=settings.min_count,
        max_count=settings.max_count,
        locator_max_side=settings.locator_max_side,
    )
    analysis = AnalysisWorker(detector_config).start()
    _create_window(settings, windowed)
    display_meter = FpsMeter()
    last_sequence = -1
    burst: list[Measurement] = []
    accepted: Optional[Measurement] = None
    state = "WAITING FOR CAMERA"
    last_display = 0.0
    last_threads = -1
    generation = 0
    status_hold_until = 0.0
    next_retry_at = 0.0
    next_analysis_at = 0.0
    measurement_locked = False

    print(
        f"USB camera index {camera_index}: {camera_info.actual_width}x"
        f"{camera_info.actual_height} {camera_info.driver_fps:.1f} FPS "
        f"backend={camera_info.backend}"
    )
    print("Continuous inspection active. Q/ESC exits maintenance mode.")

    try:
        while True:
            packet = reader.wait_latest(last_sequence, timeout=0.10, copy=False)
            if packet is None:
                continue
            frame, sequence, _ = packet
            if sequence <= last_sequence:
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                continue
            last_sequence = sequence

            system_status = monitor.sample()
            threads = monitor.processing_threads(system_status)
            if threads != last_threads:
                cv2.setNumThreads(threads)
                last_threads = threads

            for reply in analysis.drain():
                if reply.generation != generation:
                    continue
                if reply.result is None:
                    burst.clear()
                    accepted = None
                    state = "NO PRODUCT"
                    generation += 1
                    status_hold_until = time.monotonic() + 1.0
                    next_retry_at = status_hold_until
                    continue
                product = catalog.match(
                    reply.result.pitch_px, settings.pixels_per_mm
                )
                burst.append(
                    Measurement(
                        result=reply.result,
                        frame_width=reply.frame_width,
                        frame_height=reply.frame_height,
                        product=product,
                    )
                )
                next_analysis_at = (
                    time.monotonic() + settings.analysis_gap_ms / 1000.0
                )
                if len(burst) == settings.burst_frames:
                    decision = decide_five_frame_counts(
                        [item.result.count for item in burst]
                    )
                    if decision.accepted and decision.count is not None:
                        candidates = [
                            item
                            for item in burst
                            if item.result.count == decision.count
                        ]
                        accepted = max(
                            candidates, key=lambda item: item.result.quality
                        )
                        state = "RESULT ACCEPTED"
                        measurement_locked = True
                    else:
                        accepted = None
                        state = decision.reason
                        status_hold_until = time.monotonic() + 1.0
                        next_retry_at = status_hold_until
                        measurement_locked = False
                    burst.clear()

            changed, stationary = motion.update(frame)
            if changed:
                generation += 1
                status_hold_until = 0.0
                next_retry_at = 0.0
                next_analysis_at = 0.0
                measurement_locked = False
                burst.clear()
                accepted = None
                state = "WAITING FOR STABLE IMAGE"
            elif not stationary:
                generation += 1
                measurement_locked = False
                burst.clear()
                accepted = None
                state = "WAITING FOR STABLE IMAGE"
            elif not system_status.processing_allowed:
                generation += 1
                measurement_locked = False
                burst.clear()
                accepted = None
                state = system_status.reason or "PROCESSING PAUSED"
            else:
                submitted = False
                current_time = time.monotonic()
                if (
                    not measurement_locked
                    and current_time >= next_retry_at
                    and current_time >= next_analysis_at
                ):
                    submitted = analysis.submit(
                        AnalysisTask(generation, sequence, frame)
                    )
                if (
                    submitted
                    and state != "RESULT ACCEPTED"
                    and time.monotonic() >= status_hold_until
                ):
                    state = "MEASURING"

            now = time.perf_counter()
            display_target_fps = min(
                settings.display_fps, monitor.preview_fps(system_status)
            )
            display_interval = 1.0 / max(1.0, display_target_fps)
            if now - last_display >= display_interval:
                canvas, scale, offset_x, offset_y = _letterbox(
                    frame, settings.screen_width, settings.screen_height
                )
                if accepted is not None:
                    _draw_measurement_geometry(
                        canvas, accepted, scale, offset_x, offset_y
                    )
                motion_text = (
                    f"MOTION {motion.score:.2f}/{motion.threshold:.2f} "
                    f"STABLE {motion.stable_count}/{settings.stable_frames}"
                )
                progress = len(burst)
                _draw_hud(
                    canvas,
                    accepted,
                    state,
                    progress,
                    reader.read_fps,
                    display_meter.fps,
                    system_status.summary(),
                    motion_text,
                )
                cv2.imshow(settings.window_title, canvas)
                display_meter.tick()
                last_display = now

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
    finally:
        analysis.stop()
        reader.stop()
        cv2.destroyAllWindows()
    return 0


def _self_test() -> int:
    cases = [
        ([40, 40, 40, 40, 40], True, 40),
        ([40, 40, 40, 41, 50], True, 40),
        ([39, 40, 41, 42, 50], False, None),
        ([37, 37, 37, 37, 37], True, 37),
    ]
    for counts, expected_ok, expected_count in cases:
        decision = decide_five_frame_counts(counts)
        if decision.accepted != expected_ok or decision.count != expected_count:
            raise AssertionError((counts, decision))
    gate = MotionGate(width=160, stable_frames=3)
    base = np.full((90, 160, 3), 100, dtype=np.uint8)
    assert gate.update(base) == (True, False)
    for brightness in (103, 98, 102):
        changed, stationary = gate.update(
            np.full_like(base, brightness)
        )
        assert not changed
    assert stationary
    moved = base.copy()
    moved[:, :80] = 230
    changed, stationary = gate.update(moved)
    assert changed and not stationary
    print("pi5 station self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Continuous dual-background counter for Pi 5 HDMI LCD"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("station_config.json"),
    )
    parser.add_argument(
        "--products",
        type=Path,
        default=Path(__file__).with_name("products.json"),
    )
    parser.add_argument("--camera", type=int, default=None)
    parser.add_argument(
        "--runtime-profile",
        choices=("auto", "desktop", "rpi5-passive"),
        default="rpi5-passive",
    )
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        return _self_test()
    try:
        with args.config.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        settings = LiveSettings.from_config(config)
        runtime = build_runtime_profile(config, override=args.runtime_profile)
        configure_opencv(runtime)
        catalog = ProductPitchCatalog.load(args.products)
        return run_station(
            settings, runtime, catalog, args.camera, args.windowed
        )
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        print(f"ERROR: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
