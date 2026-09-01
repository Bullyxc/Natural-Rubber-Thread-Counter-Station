"""
Thread Counter Station
======================

Classical computer-vision pipeline for a fixed USB webcam station.  The
program counts repeated elastic-thread bands/edges in a configured ROI,
estimates product width, classifies neutral colour (black/white), and maps
the measurement to a user-editable product catalog.

No machine-learning model is used.  The only runtime dependencies are
OpenCV and NumPy.

Examples:
    python thread_counter_station.py
    python thread_counter_station.py --camera 1 --windowed
    python thread_counter_station.py --image samples\\white_band.jpg --save

Live controls:
    SPACE  capture a short burst and count the sharpest frame
    R      reset the adaptive calibration
    S      save the last annotated result
    Q/ESC  quit
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from camera_stream import open_camera_backend, resize_for_preview


# ---------------------------------------------------------------------------
# Configuration and result models
# ---------------------------------------------------------------------------


@dataclass
class StationSettings:
    # Typically index 0 is the laptop camera and index 1 is the first USB
    # camera. Override with --camera if Windows enumerates differently.
    camera_index: int = 1
    camera_width: int = 2560
    camera_height: int = 1440
    camera_fps: int = 30
    process_max_side: int = 1280
    roi_x: float = 0.30
    roi_y: float = 0.00
    roi_width: float = 0.40
    roi_height: float = 1.00
    num_strips: int = 12
    burst_frames: int = 5
    burst_delay_ms: int = 40
    polarity: str = "auto"
    count_axis: str = "y"
    alignment_mode: str = "auto"
    alignment_angle_deg: Optional[float] = None
    max_tilt_deg: float = 45.0
    pitch_override_px: Optional[float] = None
    pixels_per_mm: float = 0.0
    edge_weight: float = 0.20
    white_l_min: float = 150.0
    black_l_max: float = 95.0
    min_agreement: float = 0.50
    fullscreen: bool = True
    window_title: str = "Thread Counter Station"
    preview_width: int = 1600
    output_dir: str = "results"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StationSettings":
        camera = data.get("camera", {}) or {}
        processing = data.get("processing", {}) or {}
        roi = processing.get("roi", data.get("roi", {})) or {}
        color = data.get("color", {}) or {}
        ui = data.get("ui", {}) or {}
        capture = data.get("capture", {}) or {}
        alignment = data.get("alignment", {}) or {}
        output = data.get("output", {}) or {}

        return cls(
            camera_index=int(camera.get("index", cls.camera_index)),
            camera_width=int(camera.get("width", cls.camera_width)),
            camera_height=int(camera.get("height", cls.camera_height)),
            camera_fps=int(camera.get("fps", cls.camera_fps)),
            process_max_side=int(
                processing.get("max_side", cls.process_max_side)
            ),
            roi_x=float(roi.get("x", cls.roi_x)),
            roi_y=float(roi.get("y", cls.roi_y)),
            roi_width=float(roi.get("width", cls.roi_width)),
            roi_height=float(roi.get("height", cls.roi_height)),
            num_strips=int(
                processing.get("num_strips", cls.num_strips)
            ),
            burst_frames=int(
                processing.get("burst_frames", cls.burst_frames)
            ),
            burst_delay_ms=int(
                processing.get("burst_delay_ms", cls.burst_delay_ms)
            ),
            polarity=str(processing.get("polarity", cls.polarity)).lower(),
            count_axis=str(
                processing.get("count_axis", cls.count_axis)
            ).lower(),
            alignment_mode=str(
                alignment.get("mode", cls.alignment_mode)
            ).lower(),
            alignment_angle_deg=_optional_float(
                alignment.get("angle_deg", cls.alignment_angle_deg)
            ),
            max_tilt_deg=float(
                alignment.get("max_tilt_deg", cls.max_tilt_deg)
            ),
            pitch_override_px=_optional_float(
                processing.get("pitch_override_px", cls.pitch_override_px)
            ),
            pixels_per_mm=float(
                processing.get("pixels_per_mm", cls.pixels_per_mm)
            ),
            edge_weight=float(
                processing.get("edge_weight", cls.edge_weight)
            ),
            white_l_min=float(
                color.get("white_l_min", cls.white_l_min)
            ),
            black_l_max=float(
                color.get("black_l_max", cls.black_l_max)
            ),
            min_agreement=float(
                processing.get("min_agreement", cls.min_agreement)
            ),
            fullscreen=bool(ui.get("fullscreen", cls.fullscreen)),
            window_title=str(
                ui.get("window_title", cls.window_title)
            ),
            preview_width=int(
                capture.get("preview_width", cls.preview_width)
            ),
            output_dir=str(output.get("directory", cls.output_dir)),
        ).validated()

    def validated(self) -> "StationSettings":
        self.roi_x = float(np.clip(self.roi_x, 0.0, 0.95))
        self.roi_y = float(np.clip(self.roi_y, 0.0, 0.95))
        self.roi_width = float(np.clip(self.roi_width, 0.05, 1.0 - self.roi_x))
        self.roi_height = float(
            np.clip(self.roi_height, 0.05, 1.0 - self.roi_y)
        )
        self.process_max_side = max(320, int(self.process_max_side))
        self.preview_width = max(640, int(self.preview_width))
        self.num_strips = max(4, min(80, int(self.num_strips)))
        self.burst_frames = max(1, min(20, int(self.burst_frames)))
        self.burst_delay_ms = max(0, min(500, int(self.burst_delay_ms)))
        self.edge_weight = float(np.clip(self.edge_weight, 0.0, 1.0))
        self.min_agreement = float(np.clip(self.min_agreement, 0.0, 1.0))
        if self.polarity not in {"auto", "black", "white"}:
            self.polarity = "auto"
        if self.count_axis not in {"x", "y"}:
            self.count_axis = "y"
        if self.alignment_mode not in {"auto", "none", "manual"}:
            self.alignment_mode = "auto"
        self.max_tilt_deg = float(np.clip(self.max_tilt_deg, 0.0, 80.0))
        if self.pixels_per_mm < 0:
            self.pixels_per_mm = 0.0
        return self


@dataclass
class CounterParams:
    tophat_kw: int
    distance: int
    border_margin: int
    smooth_win: int
    merge_max: int


@dataclass
class CountResult:
    count: int
    agreement: float
    pitch_px: float
    polarity: str
    x_left: int
    x_right: int
    consensus_xs: list[float]
    tier1_count: int
    tier2_count: int
    spread: int
    votes: list[int]
    count_axis: str = "y"
    rotation_deg: float = 0.0
    scale_factor: float = 1.0
    width_px: float = 0.0
    width_mm: Optional[float] = None
    color: str = "unknown"
    lightness: float = 0.0
    product_id: str = "UNMATCHED"
    product_name: str = "NO_MATCH"


@dataclass
class ProductRule:
    product_id: str
    name: str
    colors: list[str] = field(default_factory=list)
    count_min: int = 0
    count_max: int = 1_000_000
    width_mm_min: Optional[float] = None
    width_mm_max: Optional[float] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProductRule":
        colors = data.get("colors", data.get("color", []))
        if isinstance(colors, str):
            colors = [colors]
        colors = [str(value).lower() for value in (colors or [])]
        return cls(
            product_id=str(data.get("id", "UNNAMED")),
            name=str(data.get("name", data.get("id", "UNNAMED"))),
            colors=colors,
            count_min=int(data.get("count_min", 0)),
            count_max=int(data.get("count_max", 1_000_000)),
            width_mm_min=_optional_float(data.get("width_mm_min")),
            width_mm_max=_optional_float(data.get("width_mm_max")),
        )


class ProductCatalog:
    """Ordered rule catalog; the first matching rule wins."""

    def __init__(self, rules: list[ProductRule]) -> None:
        self.rules = rules

    @classmethod
    def from_file(cls, path: Path) -> "ProductCatalog":
        if not path.exists():
            return cls([])
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        rules = [
            ProductRule.from_dict(item)
            for item in data.get("products", [])
            if isinstance(item, dict)
        ]
        return cls(rules)

    def classify(
        self,
        color: str,
        count: int,
        width_mm: Optional[float],
    ) -> tuple[str, str]:
        color = color.lower()
        for rule in self.rules:
            if rule.colors and color not in rule.colors:
                continue
            if not rule.count_min <= count <= rule.count_max:
                continue
            has_width_rule = (
                rule.width_mm_min is not None
                or rule.width_mm_max is not None
            )
            if has_width_rule and width_mm is None:
                continue
            if (
                rule.width_mm_min is not None
                and width_mm is not None
                and width_mm < rule.width_mm_min
            ):
                continue
            if (
                rule.width_mm_max is not None
                and width_mm is not None
                and width_mm > rule.width_mm_max
            ):
                continue
            return rule.product_id, rule.name
        return "UNMATCHED", "NO_MATCH"


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def load_settings(path: Path) -> StationSettings:
    if not path.exists():
        return StationSettings().validated()
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Settings file must contain a JSON object: {path}")
    return StationSettings.from_dict(data)


# ---------------------------------------------------------------------------
# Image preparation and classical counter
# ---------------------------------------------------------------------------


def crop_roi(
    image: np.ndarray,
    settings: StationSettings,
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Return the configured ROI and its (x0, y0, x1, y1) frame rectangle."""
    height, width = image.shape[:2]
    x0 = int(round(width * settings.roi_x))
    y0 = int(round(height * settings.roi_y))
    x1 = int(round(width * (settings.roi_x + settings.roi_width)))
    y1 = int(round(height * (settings.roi_y + settings.roi_height)))
    x0 = max(0, min(width - 1, x0))
    y0 = max(0, min(height - 1, y0))
    x1 = max(x0 + 1, min(width, x1))
    y1 = max(y0 + 1, min(height, y1))
    return image[y0:y1, x0:x1], (x0, y0, x1, y1)


def prepare_gray(
    image: np.ndarray,
    max_side: int,
) -> tuple[np.ndarray, float]:
    """Convert to gray and downscale only when larger than max_side."""
    height, width = image.shape[:2]
    scale = 1.0
    prepared = image
    longest = max(height, width)
    if longest > max_side:
        scale = max_side / float(longest)
        prepared = cv2.resize(
            image,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    if prepared.ndim == 3:
        prepared = cv2.cvtColor(prepared, cv2.COLOR_BGR2GRAY)
    if prepared.dtype != np.uint8:
        prepared = cv2.normalize(prepared, None, 0, 255, cv2.NORM_MINMAX).astype(
            np.uint8
        )
    return prepared, scale


def sharpness_score(gray: np.ndarray) -> float:
    """Variance of Laplacian; useful for choosing a sharp burst frame."""
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    return float(laplacian.var())


def _normalise01(values: np.ndarray) -> np.ndarray:
    values = values.astype(np.float32)
    low = float(np.percentile(values, 2))
    high = float(np.percentile(values, 98))
    if high - low < 1e-6:
        return np.zeros_like(values, dtype=np.float32)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def _safe_smooth(profile: np.ndarray, window: int) -> np.ndarray:
    if len(profile) < 2:
        return profile.astype(np.float32, copy=True)
    window = max(1, min(int(window), len(profile)))
    if window % 2 == 0:
        window = max(1, window - 1)
    if window == 1:
        return profile.astype(np.float32, copy=True)
    kernel = np.ones(window, dtype=np.float32) / float(window)
    return np.convolve(profile.astype(np.float32), kernel, mode="same")


def _find_peaks(
    signal: np.ndarray,
    min_distance: int,
    min_prominence: float,
) -> list[int]:
    """Small NumPy-only peak finder, replacing scipy.signal.find_peaks."""
    signal = np.asarray(signal, dtype=np.float32)
    if len(signal) < 3:
        return []
    distance = max(1, int(min_distance))
    window = max(2, distance * 2)
    candidates: list[tuple[float, int]] = []
    for index in range(1, len(signal) - 1):
        left = float(signal[index - 1])
        current = float(signal[index])
        right = float(signal[index + 1])
        if current < left or current < right:
            continue
        left_min = float(signal[max(0, index - window): index + 1].min())
        right_min = float(signal[index: min(len(signal), index + window + 1)].min())
        prominence = current - max(left_min, right_min)
        if prominence >= min_prominence:
            candidates.append((current, index))

    # Select strongest peaks first, then restore spatial ordering.
    selected: list[int] = []
    for _, index in sorted(candidates, reverse=True):
        if all(abs(index - other) >= distance for other in selected):
            selected.append(index)
    return sorted(selected)


class ThreadCounter:
    """Adaptive multi-strip counter using morphology, gradients and voting."""

    RECALIBRATE_EVERY = 60

    def __init__(
        self,
        edge_weight: float = 0.30,
        count_axis: str = "y",
    ) -> None:
        self.edge_weight = float(np.clip(edge_weight, 0.0, 1.0))
        self.count_axis = count_axis if count_axis in {"x", "y"} else "y"
        self.reset_calibration()

    def reset_calibration(self) -> None:
        self._locked_polarity: Optional[str] = None
        self._locked_pitch: Optional[float] = None
        self._locked_params: Optional[CounterParams] = None
        self._frames_since_calibration = 0

    @staticmethod
    def _bilateral(gray: np.ndarray) -> np.ndarray:
        return cv2.bilateralFilter(gray, 7, 40, 8)

    @staticmethod
    def _gaussian(gray: np.ndarray) -> np.ndarray:
        return cv2.GaussianBlur(gray, (7, 7), 2.0)

    @staticmethod
    def _clahe(gray: np.ndarray) -> np.ndarray:
        if float(gray.std()) < 6.0:
            return gray.copy()
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(6, 6))
        return clahe.apply(gray)

    def _morphology(
        self,
        gray: np.ndarray,
        kw: int,
        polarity: str,
    ) -> np.ndarray:
        kw = max(3, int(kw))
        if kw % 2 == 0:
            kw += 1
        # Horizontal threads are counted along Y, so a horizontal kernel
        # extracts their local line response.  The X-axis mode is retained
        # for products whose repeated structures run vertically.
        kernel_size = (kw, 1) if self.count_axis == "y" else (1, kw)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
        operation = (
            cv2.MORPH_TOPHAT if polarity == "white" else cv2.MORPH_BLACKHAT
        )
        return cv2.morphologyEx(
            gray, operation, kernel, borderType=cv2.BORDER_REFLECT
        )

    def _feature(self, gray: np.ndarray, kw: int, polarity: str) -> np.ndarray:
        morph = _normalise01(self._morphology(gray, kw, polarity))
        dx, dy = (0, 1) if self.count_axis == "y" else (1, 0)
        gradient = cv2.Sobel(gray, cv2.CV_32F, dx, dy, ksize=3)
        edge = _normalise01(np.abs(gradient))
        return (1.0 - self.edge_weight) * morph + self.edge_weight * edge

    def _detect_polarity(self, gray: np.ndarray, kw: int) -> str:
        scores: dict[str, float] = {}
        for polarity in ("white", "black"):
            feature = self._feature(gray, kw, polarity)
            scores[polarity] = float(
                np.percentile(feature, 95) + 0.25 * feature.std()
            )
        return "black" if scores["black"] > scores["white"] else "white"

    def _mean_profile(self, feature: np.ndarray) -> np.ndarray:
        # Profile coordinate is X for vertical repeated structures and Y for
        # horizontal repeated structures.
        profile_axis = 1 if self.count_axis == "y" else 0
        return feature.astype(np.float32).mean(axis=profile_axis)

    def _estimate_pitch(
        self,
        profile: np.ndarray,
        center_fraction: float = 0.70,
        min_pitch_scale: float = 1.0,
    ) -> Optional[float]:
        width = len(profile)
        margin = int(width * (1.0 - center_fraction) / 2.0)
        center = profile[margin: max(margin + 1, width - margin)]
        smooth = _safe_smooth(center, 5)
        dynamic_range = float(smooth.max() - smooth.min())
        if dynamic_range <= 1e-5:
            return None
        peaks = _find_peaks(
            smooth,
            min_distance=max(2, int(round(2 * min_pitch_scale))),
            min_prominence=max(0.03 * dynamic_range, 0.01),
        )
        if len(peaks) < 2:
            return None
        gaps = np.diff(np.asarray(peaks, dtype=np.float32))
        valid = gaps[
            (gaps >= 3.0 * min_pitch_scale)
            & (gaps <= max(4.0, len(center) / 3.0))
        ]
        if len(valid) == 0:
            valid = gaps
        return float(np.median(valid)) if len(valid) else None

    @staticmethod
    def _auto_params(pitch: float) -> CounterParams:
        pitch = max(2.0, float(pitch))
        kw = max(5, min(151, int(round(pitch * 1.5))))
        if kw % 2 == 0:
            kw += 1
        smooth = max(3, min(31, int(round(pitch * 0.30))))
        if smooth % 2 == 0:
            smooth += 1
        return CounterParams(
            tophat_kw=kw,
            distance=max(2, int(round(pitch * 0.50))),
            border_margin=max(3, kw // 2),
            smooth_win=smooth,
            merge_max=max(2, int(round(pitch * 0.25))),
        )

    @staticmethod
    def _find_bounds(
        profile: np.ndarray,
        border_margin: int,
        edge_threshold: float,
    ) -> tuple[int, int]:
        width = len(profile)
        if width < 4:
            return 0, max(0, width - 1)
        baseline = float(np.percentile(profile, 10))
        high = float(np.percentile(profile, 98))
        threshold = baseline + float(edge_threshold) * max(0.0, high - baseline)
        left = max(1, min(width // 2 - 1, border_margin))
        right = min(width - 2, max(width // 2 + 1, width - border_margin - 1))
        for index in range(left, width // 2):
            if profile[index] >= threshold:
                left = index
                break
        for index in range(width - border_margin - 1, width // 2, -1):
            if profile[index] >= threshold:
                right = index
                break
        if right - left < max(12, int(width * 0.30)):
            left = int(width * 0.05)
            right = int(width * 0.95)
        return left, max(left + 1, right)

    @staticmethod
    def _find_active_band(profile: np.ndarray) -> tuple[int, int]:
        """Locate the dominant textured product band inside a full-height ROI."""
        if len(profile) < 8:
            return 0, max(0, len(profile) - 1)
        smooth = _safe_smooth(profile, max(9, int(len(profile) * 0.015)))
        baseline = float(np.percentile(smooth, 50))
        high = float(np.percentile(smooth, 95))
        dynamic = high - baseline
        if dynamic <= 1e-5:
            return 0, len(profile) - 1

        threshold = baseline + 0.65 * dynamic
        active_indices = np.flatnonzero(smooth >= threshold)
        if len(active_indices) == 0:
            return 0, len(profile) - 1

        runs: list[tuple[int, int]] = []
        start = previous = int(active_indices[0])
        for value in active_indices[1:]:
            value = int(value)
            if value > previous + 1:
                runs.append((start, previous))
                start = value
            previous = value
        runs.append((start, previous))

        min_run = max(12, int(len(profile) * 0.04))
        long_runs = [run for run in runs if run[1] - run[0] + 1 >= min_run]
        if not long_runs:
            return 0, len(profile) - 1
        best_start, best_end = max(
            long_runs,
            key=lambda run: float(smooth[run[0]: run[1] + 1].mean())
            * (run[1] - run[0] + 1),
        )
        padding = max(3, int(len(profile) * 0.01))
        return max(0, best_start - padding), min(
            len(profile) - 1, best_end + padding
        )

    def _count_peaks_in_strip(
        self,
        profile: np.ndarray,
        params: CounterParams,
        x_left: int,
        x_right: int,
    ) -> tuple[int, np.ndarray]:
        smooth = _safe_smooth(profile, params.smooth_win)
        cable = smooth[x_left: x_right + 1] if x_left < x_right else smooth
        if len(cable) < 3:
            return 0, np.array([], dtype=np.float32)

        dynamic_range = float(cable.max() - cable.min())
        if dynamic_range <= 1e-5:
            return 0, np.array([], dtype=np.float32)
        pitch = self._locked_pitch or float(params.distance * 2)
        min_distance = max(params.distance, int(round(pitch * 0.55)))
        prominence = max(0.05 * dynamic_range, 0.012)
        peaks = _find_peaks(cable, min_distance, prominence)

        # A lower threshold at the two ends recovers partially visible threads.
        edge_zone = int(len(cable) * 0.15)
        edge_prominence = max(0.025 * dynamic_range, 0.008)
        if edge_zone >= 3:
            for peak in _find_peaks(cable[:edge_zone], min_distance, edge_prominence):
                if all(abs(peak - other) >= min_distance for other in peaks):
                    peaks.append(peak)
            right_start = len(cable) - edge_zone
            for peak in _find_peaks(
                cable[right_start:], min_distance, edge_prominence
            ):
                peak += right_start
                if all(abs(peak - other) >= min_distance for other in peaks):
                    peaks.append(peak)
        peaks.sort()

        merged: list[int] = []
        for peak in peaks:
            if merged and peak - merged[-1] < params.merge_max:
                merged[-1] = int(round((merged[-1] + peak) / 2.0))
            else:
                merged.append(peak)

        # Reject isolated weak ripples while keeping the first visible edge.
        validated: list[int] = []
        valley_drop = dynamic_range * 0.08
        for index, current in enumerate(merged):
            if index == 0:
                validated.append(current)
                continue
            previous = merged[index - 1]
            segment = cable[previous: current + 1]
            valley = float(segment.min()) if len(segment) else 0.0
            side_level = min(float(cable[previous]), float(cable[current]))
            if side_level - valley >= valley_drop:
                validated.append(current)
            elif float(cable[current]) > float(cable[previous]):
                if validated:
                    validated.pop()
                validated.append(current)

        if len(validated) > 3:
            gaps = np.diff(np.asarray(validated, dtype=np.float32))
            mean_gap = float(gaps.mean())
            coefficient = float(gaps.std() / mean_gap) if mean_gap > 0 else 1.0
            max_coefficient = (
                0.30 if dynamic_range < 0.20
                else 0.24 if dynamic_range < 0.40
                else 0.20
            )
            if coefficient > max_coefficient:
                return 0, np.array([], dtype=np.float32)

        global_peaks = np.asarray(validated, dtype=np.float32) + float(x_left)
        return len(validated), global_peaks

    def _strip_vote(
        self,
        feature: np.ndarray,
        params: CounterParams,
        x_left: int,
        x_right: int,
        num_strips: int,
    ) -> tuple[int, list[tuple[np.ndarray, bool]], list[int]]:
        height, width = feature.shape[:2]
        # Use independent strips perpendicular to the counting axis.  For
        # horizontal threads (count_axis=y), these are vertical slices so
        # each slice produces a profile over Y.
        strip_length = width if self.count_axis == "y" else height
        strip_step = max(1, strip_length // num_strips)
        strips: list[tuple[np.ndarray, bool]] = []
        votes: list[int] = []
        for index in range(num_strips):
            start = index * strip_step
            end = min(strip_length, start + strip_step)
            if start >= end:
                continue
            if self.count_axis == "y":
                strip = feature[:, start:end]
                profile = strip.mean(axis=1)
            else:
                strip = feature[start:end, :]
                profile = strip.mean(axis=0)
            count, peaks = self._count_peaks_in_strip(
                profile, params, x_left, x_right
            )
            uniform = False
            if len(peaks) > 1:
                gaps = np.diff(peaks)
                median_gap = float(np.median(gaps))
                uniform = bool(
                    median_gap > 0
                    and np.all(np.abs(gaps - median_gap) / median_gap <= 0.28)
                )
            strips.append((peaks, uniform))
            if count > 0:
                votes.append(count)
        final = int(round(float(np.median(votes)))) if votes else 0
        return final, strips, votes

    @staticmethod
    def _consensus_positions(
        strips: list[tuple[np.ndarray, bool]],
        final_count: int,
        x_left: int,
        x_right: int,
    ) -> list[float]:
        honest = [
            peaks for peaks, uniform in strips
            if len(peaks) == final_count and uniform
        ]
        if not honest:
            honest = [
                peaks for peaks, _ in strips if len(peaks) == final_count
            ]
        if not honest:
            return []
        matrix = np.asarray(honest, dtype=np.float32)
        median_xs = np.median(matrix, axis=0)
        return [
            float(value)
            for value in median_xs
            if x_left <= float(value) <= x_right
        ]

    def run(
        self,
        image: np.ndarray,
        polarity: str = "auto",
        pitch_override: Optional[float] = None,
        center_fraction: float = 0.70,
        edge_threshold: float = 0.08,
        num_strips: int = 12,
    ) -> Optional[CountResult]:
        if image is None or image.size == 0:
            return None
        gray = image
        if image.ndim == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if gray.dtype != np.uint8:
            gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(
                np.uint8
            )

        self._frames_since_calibration += 1
        needs_calibration = (
            self._locked_polarity is None
            or self._locked_pitch is None
            or self._frames_since_calibration >= self.RECALIBRATE_EVERY
        )
        smoothed = (
            self._bilateral(gray)
            if needs_calibration
            else self._gaussian(gray)
        )
        enhanced = self._clahe(smoothed)

        if needs_calibration:
            chosen = self._detect_polarity(enhanced, 15) if polarity == "auto" else polarity
            rough_feature = self._feature(enhanced, 15, chosen)
            rough_profile = self._mean_profile(rough_feature)
            if self.count_axis == "y":
                rough_start, rough_end = self._find_active_band(rough_profile)
                pitch_profile = rough_profile[rough_start: rough_end + 1]
            else:
                pitch_profile = rough_profile
            rough_pitch = self._estimate_pitch(
                pitch_profile, center_fraction
            )
            pitch = pitch_override or rough_pitch
            if pitch is None:
                return None
            params = self._auto_params(pitch)
            refined_feature = self._feature(
                enhanced, params.tophat_kw, chosen
            )
            refined_profile = self._mean_profile(refined_feature)
            if self.count_axis == "y":
                refined_start, refined_end = self._find_active_band(refined_profile)
                refined_pitch_profile = refined_profile[refined_start: refined_end + 1]
            else:
                refined_pitch_profile = refined_profile
            refined_pitch = (
                pitch_override
                or self._estimate_pitch(
                    refined_pitch_profile,
                    center_fraction,
                    min_pitch_scale=0.5,
                )
                or pitch
            )
            self._locked_polarity = chosen
            self._locked_pitch = float(refined_pitch)
            self._locked_params = self._auto_params(refined_pitch)
            self._frames_since_calibration = 0

        if (
            self._locked_polarity is None
            or self._locked_pitch is None
            or self._locked_params is None
        ):
            return None

        feature = self._feature(
            enhanced,
            self._locked_params.tophat_kw,
            self._locked_polarity,
        )
        profile = _safe_smooth(
            self._mean_profile(feature), self._locked_params.smooth_win
        )
        if self.count_axis == "y":
            band_start, band_end = self._find_active_band(profile)
            local_left, local_right = self._find_bounds(
                profile[band_start: band_end + 1],
                self._locked_params.border_margin,
                edge_threshold,
            )
            x_left = band_start + local_left
            x_right = band_start + local_right
        else:
            x_left, x_right = self._find_bounds(
                profile,
                self._locked_params.border_margin,
                edge_threshold,
            )
        final_count, strips, votes = self._strip_vote(
            feature,
            self._locked_params,
            x_left,
            x_right,
            num_strips,
        )
        if final_count <= 0 or not votes:
            return None

        band_width = float(x_right - x_left)
        if self._locked_pitch > 0 and band_width > 0 and self._frames_since_calibration > 10:
            predicted = max(1, int(round(band_width / self._locked_pitch)) + 1)
            tolerance = max(3, int(round(predicted * 0.12)))
            if abs(final_count - predicted) > tolerance:
                return None

        consensus = self._consensus_positions(
            strips, final_count, x_left, x_right
        )
        agreement = votes.count(final_count) / float(len(votes))
        tier1 = sum(
            1 for peaks, uniform in strips
            if len(peaks) == final_count and uniform
        )
        tier2 = sum(
            1 for peaks, uniform in strips
            if len(peaks) == final_count and not uniform
        )
        return CountResult(
            count=final_count,
            agreement=agreement,
            pitch_px=float(self._locked_pitch),
            polarity=self._locked_polarity,
            x_left=x_left,
            x_right=x_right,
            consensus_xs=consensus,
            tier1_count=tier1,
            tier2_count=tier2,
            spread=max(votes) - min(votes),
            votes=votes,
            count_axis=self.count_axis,
        )


def estimate_alignment_rotation(
    image_bgr: np.ndarray,
    count_axis: str,
    max_tilt_deg: float = 45.0,
) -> float:
    """Estimate the rotation needed to make repeated thread lines axis-aligned."""
    if image_bgr is None or image_bgr.size == 0 or max_tilt_deg <= 0:
        return 0.0
    gray = image_bgr
    if image_bgr.ndim == 3:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    # Hough is run on a reduced copy to keep auto-alignment inexpensive.
    height, width = gray.shape[:2]
    scale = min(1.0, 1200.0 / max(height, width))
    if scale < 1.0:
        small = cv2.resize(
            gray,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        small = gray
    small_h, small_w = small.shape[:2]
    blurred = cv2.GaussianBlur(small, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 120)

    # The full-height ROI can contain background seams. Restrict Hough to the
    # dominant textured band before choosing its line orientation.
    if count_axis == "y":
        row_energy = np.abs(cv2.Sobel(small, cv2.CV_32F, 0, 1, ksize=3)).mean(axis=1)
        band_start, band_end = ThreadCounter._find_active_band(row_energy)
        mask = np.zeros_like(edges)
        mask[band_start: band_end + 1, :] = 255
    else:
        col_energy = np.abs(cv2.Sobel(small, cv2.CV_32F, 1, 0, ksize=3)).mean(axis=0)
        band_start, band_end = ThreadCounter._find_active_band(col_energy)
        mask = np.zeros_like(edges)
        mask[:, band_start: band_end + 1] = 255
    edges = cv2.bitwise_and(edges, mask)

    min_line_length = max(
        24,
        int((small_w if count_axis == "y" else small_h) * 0.12),
    )
    line_gap = max(4, int(min(small_h, small_w) * 0.02))
    threshold = max(18, int(min(small_h, small_w) * 0.04))
    lines = cv2.HoughLinesP(
        edges,
        1.0,
        np.pi / 180.0,
        threshold=threshold,
        minLineLength=min_line_length,
        maxLineGap=line_gap,
    )
    if lines is None:
        periodic_angle, periodic_score = _search_periodic_alignment(
            small, count_axis, max_tilt_deg
        )
        return periodic_angle if periodic_score >= 0.50 else 0.0

    corrections: list[tuple[float, float]] = []
    for line in np.asarray(lines).reshape(-1, 4):
        x_a, y_a, x_b, y_b = [int(value) for value in line]
        dx = x_b - x_a
        dy = y_b - y_a
        length = float(math.hypot(dx, dy))
        if length < min_line_length:
            continue
        angle = math.degrees(math.atan2(dy, dx))
        while angle <= -90.0:
            angle += 180.0
        while angle > 90.0:
            angle -= 180.0

        if count_axis == "y":
            correction = angle
        else:
            target = 90.0 if angle >= 0.0 else -90.0
            correction = angle - target
        if abs(correction) <= max_tilt_deg:
            corrections.append((correction, length))

    if not corrections:
        periodic_angle, periodic_score = _search_periodic_alignment(
            small, count_axis, max_tilt_deg
        )
        return periodic_angle if periodic_score >= 0.50 else 0.0

    # Weighted histogram is less sensitive to one short diagonal background
    # edge than a simple average of Hough line angles.
    bin_size = 1.0
    bins = np.arange(-max_tilt_deg, max_tilt_deg + bin_size, bin_size)
    histogram = np.zeros(len(bins), dtype=np.float32)
    for correction, length in corrections:
        index = int(round((correction + max_tilt_deg) / bin_size))
        index = max(0, min(len(histogram) - 1, index))
        histogram[index] += float(length)
    hough_confidence = float(histogram.max()) / max(1e-6, float(histogram.sum()))
    histogram = np.convolve(histogram, np.ones(5, dtype=np.float32), mode="same")
    best_index = int(np.argmax(histogram))
    estimated = float(bins[best_index])
    # Do not rotate a nominally horizontal sample for a one-degree background
    # seam; the extra interpolation can hurt the repeated-thread profile.
    estimated = 0.0 if abs(estimated) <= 2.0 else estimated

    # Hough is usually the fastest and most accurate estimate for small tilts.
    # If the textured band is strongly diagonal, Hough can instead lock onto
    # a long band edge. A periodicity search provides a classical-CV fallback
    # by selecting the angle that makes the repeated profile most regular.
    if hough_confidence >= 0.45:
        return estimated
    hough_score = _alignment_periodicity_score(small, estimated, count_axis)
    periodic_angle, periodic_score = _search_periodic_alignment(
        small, count_axis, max_tilt_deg
    )
    if periodic_score >= max(0.50, hough_score + 0.10):
        return periodic_angle
    return estimated


def rotate_for_alignment(
    image_bgr: np.ndarray,
    rotation_deg: float,
) -> np.ndarray:
    """Rotate an ROI in-place dimensions; the inverse transform is used for overlay."""
    if abs(rotation_deg) < 0.25:
        return image_bgr
    height, width = image_bgr.shape[:2]
    matrix = cv2.getRotationMatrix2D(
        ((width - 1) / 2.0, (height - 1) / 2.0),
        rotation_deg,
        1.0,
    )
    return cv2.warpAffine(
        image_bgr,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _alignment_periodicity_score(
    gray: np.ndarray,
    rotation_deg: float,
    count_axis: str,
) -> float:
    """Score repeated edge regularity after a candidate rotation."""
    aligned = rotate_for_alignment(gray, rotation_deg)
    if aligned.ndim != 2:
        aligned = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(aligned, (3, 3), 0)
    height, width = blurred.shape[:2]
    if count_axis == "y":
        left = int(width * 0.08)
        right = max(left + 1, int(width * 0.92))
        profile = np.abs(
            cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
        )[:, left:right].mean(axis=1)
        shaped = profile.reshape(-1, 1)
        length = height
        kernel_shape = (1, min(51, max(3, (length // 2) * 2 - 1)))
    else:
        top = int(height * 0.08)
        bottom = max(top + 1, int(height * 0.92))
        profile = np.abs(
            cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
        )[top:bottom, :].mean(axis=0)
        shaped = profile.reshape(1, -1)
        length = width
        kernel_shape = (min(51, max(3, (length // 2) * 2 - 1)), 1)

    if length < 12:
        return -1.0
    detrended = profile - cv2.GaussianBlur(
        shaped, kernel_shape, 0
    ).reshape(-1)
    detrended = detrended - float(detrended.mean())
    variance = float(np.mean(detrended * detrended))
    if variance < 1e-6:
        return -1.0

    best = -1.0
    max_lag = min(80, length // 3)
    for lag in range(3, max_lag + 1):
        first = detrended[:-lag]
        second = detrended[lag:]
        denominator = math.sqrt(
            float(np.mean(first * first) * np.mean(second * second))
        ) + 1e-6
        correlation = float(np.mean(first * second)) / denominator
        best = max(best, correlation)
    return best


def _search_periodic_alignment(
    gray: np.ndarray,
    count_axis: str,
    max_tilt_deg: float,
) -> tuple[float, float]:
    """Search only when Hough's line orientation is not self-consistent."""
    if max_tilt_deg <= 0:
        return 0.0, -1.0
    coarse_angles = np.arange(
        -max_tilt_deg,
        max_tilt_deg + 0.01,
        2.0,
        dtype=np.float32,
    )
    coarse_angles = np.unique(np.concatenate((coarse_angles, [0.0])))
    scored = [
        (
            _alignment_periodicity_score(gray, float(angle), count_axis),
            float(angle),
        )
        for angle in coarse_angles
    ]
    best_score, best_angle = max(scored, key=lambda item: item[0])

    refine_angles = np.arange(
        max(-max_tilt_deg, best_angle - 2.0),
        min(max_tilt_deg, best_angle + 2.0) + 0.01,
        0.5,
        dtype=np.float32,
    )
    refined = [
        (
            _alignment_periodicity_score(gray, float(angle), count_axis),
            float(angle),
        )
        for angle in refine_angles
    ]
    best_score, best_angle = max(
        scored + refined,
        key=lambda item: item[0],
    )
    return best_angle, best_score


# ---------------------------------------------------------------------------
# Measurement, colour and product classification
# ---------------------------------------------------------------------------


def classify_colour(
    roi_bgr: np.ndarray,
    axis_start: int,
    axis_end: int,
    count_axis: str,
    settings: StationSettings,
) -> tuple[str, float]:
    """Classify white/black from median CIE-L lightness in the measured band."""
    height, width = roi_bgr.shape[:2]
    if count_axis == "y":
        y0 = max(0, min(height - 1, int(axis_start)))
        y1 = max(y0 + 1, min(height, int(axis_end) + 1))
        x0 = int(width * 0.15)
        x1 = max(x0 + 1, int(width * 0.85))
    else:
        x0 = max(0, min(width - 1, int(axis_start)))
        x1 = max(x0 + 1, min(width, int(axis_end) + 1))
        y0 = int(height * 0.15)
        y1 = max(y0 + 1, int(height * 0.85))
    sample = roi_bgr[y0:y1, x0:x1]
    lab = cv2.cvtColor(sample, cv2.COLOR_BGR2LAB)
    lightness = float(np.median(lab[:, :, 0]))
    if lightness >= settings.white_l_min:
        return "white", lightness
    if lightness <= settings.black_l_max:
        return "black", lightness
    return "unknown", lightness


def enrich_result(
    result: CountResult,
    roi_bgr: np.ndarray,
    scale_factor: float,
    settings: StationSettings,
    catalog: ProductCatalog,
    rotation_deg: float = 0.0,
) -> CountResult:
    result.scale_factor = scale_factor
    result.rotation_deg = float(rotation_deg)
    result.width_px = max(
        0.0, (float(result.x_right) - float(result.x_left)) / scale_factor
    )
    if settings.pixels_per_mm > 0:
        result.width_mm = result.width_px / settings.pixels_per_mm
    result.color, result.lightness = classify_colour(
        roi_bgr,
        int(round(result.x_left / scale_factor)),
        int(round(result.x_right / scale_factor)),
        result.count_axis,
        settings,
    )
    result.product_id, result.product_name = catalog.classify(
        result.color, result.count, result.width_mm
    )
    return result


def analyse_roi(
    roi_bgr: np.ndarray,
    counter: ThreadCounter,
    settings: StationSettings,
    catalog: ProductCatalog,
) -> Optional[CountResult]:
    if settings.alignment_mode == "none":
        rotation_deg = 0.0
    elif settings.alignment_mode == "manual":
        rotation_deg = float(settings.alignment_angle_deg or 0.0)
    else:
        rotation_deg = estimate_alignment_rotation(
            roi_bgr,
            settings.count_axis,
            settings.max_tilt_deg,
        )
    aligned_roi = rotate_for_alignment(roi_bgr, rotation_deg)
    gray, scale = prepare_gray(aligned_roi, settings.process_max_side)
    result = counter.run(
        gray,
        polarity=settings.polarity,
        pitch_override=settings.pitch_override_px,
        num_strips=settings.num_strips,
    )
    if result is None:
        return None
    return enrich_result(
        result,
        aligned_roi,
        scale,
        settings,
        catalog,
        rotation_deg=rotation_deg,
    )


# ---------------------------------------------------------------------------
# Overlay and UI
# ---------------------------------------------------------------------------


def _ascii_text(value: Any) -> str:
    """OpenCV's default Hershey font has no Thai glyphs; keep HUD readable."""
    text = str(value)
    return text.encode("ascii", "replace").decode("ascii")


def _quality_colour(result: Optional[CountResult]) -> tuple[int, int, int]:
    if result is None:
        return 180, 180, 180
    if result.agreement >= 0.70:
        return 0, 230, 100
    if result.agreement >= 0.50:
        return 0, 210, 255
    return 50, 50, 255


def _draw_panel(
    image: np.ndarray,
    lines: list[str],
    origin: tuple[int, int] = (20, 20),
    line_height: int = 29,
) -> None:
    x, y = origin
    width = max(
        cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.72, 2)[0][0]
        for line in lines
    ) + 32
    height = line_height * len(lines) + 18
    overlay = image.copy()
    cv2.rectangle(
        overlay,
        (x - 10, y - 10),
        (x + width, y + height),
        (0, 0, 0),
        -1,
    )
    cv2.addWeighted(overlay, 0.72, image, 0.28, 0, image)
    colour = (235, 235, 235)
    for index, line in enumerate(lines):
        cv2.putText(
            image,
            _ascii_text(line),
            (x, y + 23 + index * line_height),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            colour,
            2,
            cv2.LINE_AA,
        )


def _result_lines(
    result: Optional[CountResult],
    settings: StationSettings,
    status_message: str,
) -> list[str]:
    if result is None:
        return [
            "THREAD COUNTER STATION",
            f"STATUS: {status_message}",
        ]
    width = f"{result.width_px:.0f}px"
    if result.width_mm is not None:
        width += f" / {result.width_mm:.2f}mm"
    quality = "OK" if result.agreement >= settings.min_agreement else "CHECK"
    return [
        "THREAD COUNTER STATION",
        f"COUNT: {result.count}    QUALITY: {quality} {result.agreement * 100:.0f}%",
        f"PRODUCT: {_ascii_text(result.product_id)}",
        f"COLOR: {result.color.upper()}    WIDTH: {width}",
        f"LIGHTNESS: {result.lightness:.0f}    POLARITY: {result.polarity}  AXIS: {result.count_axis.upper()}",
        f"ALIGN: {result.rotation_deg:+.1f} deg",
    ]


def _aligned_line_endpoints(
    roi_rect: tuple[int, int, int, int],
    rotation_deg: float,
    count_axis: str,
    position: float,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Map one line from the aligned ROI back into the source frame."""
    x0, y0, x1, y1 = roi_rect
    roi_width = max(1, x1 - x0)
    roi_height = max(1, y1 - y0)
    if count_axis == "y":
        aligned_points = np.array(
            [[[0.0, float(position)], [float(roi_width - 1), float(position)]]],
            dtype=np.float32,
        )
    else:
        aligned_points = np.array(
            [[[float(position), 0.0], [float(position), float(roi_height - 1)]]],
            dtype=np.float32,
        )

    if abs(rotation_deg) >= 0.25:
        matrix = cv2.getRotationMatrix2D(
            ((roi_width - 1) / 2.0, (roi_height - 1) / 2.0),
            rotation_deg,
            1.0,
        )
        matrix = cv2.invertAffineTransform(matrix)
        source_points = cv2.transform(aligned_points, matrix)
    else:
        source_points = aligned_points

    source_points = source_points[0]
    source_points[:, 0] += float(x0)
    source_points[:, 1] += float(y0)
    return (
        (int(round(source_points[0, 0])), int(round(source_points[0, 1]))),
        (int(round(source_points[1, 0])), int(round(source_points[1, 1]))),
    )


def _draw_aligned_profile_line(
    image: np.ndarray,
    roi_rect: tuple[int, int, int, int],
    result: CountResult,
    position: float,
    colour: tuple[int, int, int],
    thickness: int,
) -> None:
    start, end = _aligned_line_endpoints(
        roi_rect,
        result.rotation_deg,
        result.count_axis,
        position,
    )
    cv2.line(image, start, end, colour, thickness, cv2.LINE_AA)


def draw_station_view(
    frame_bgr: np.ndarray,
    roi_rect: tuple[int, int, int, int],
    result: Optional[CountResult],
    sharpness: Optional[float],
    settings: StationSettings,
    status_message: str = "PRESS SPACE",
) -> np.ndarray:
    """Draw ROI, consensus lines and a full-screen-friendly dashboard."""
    view = frame_bgr.copy()
    height, width = view.shape[:2]
    x0, y0, x1, y1 = roi_rect
    quality_colour = _quality_colour(result)

    cv2.rectangle(view, (x0, y0), (x1, y1), quality_colour, 2)
    if result is not None:
        scale = max(1e-6, result.scale_factor)
        start = int(round(result.x_left / scale))
        end = int(round(result.x_right / scale))
        if result.count_axis == "y":
            _draw_aligned_profile_line(
                view, roi_rect, result, start, quality_colour, 2
            )
            _draw_aligned_profile_line(
                view, roi_rect, result, end, quality_colour, 2
            )
        else:
            _draw_aligned_profile_line(
                view, roi_rect, result, start, quality_colour, 2
            )
            _draw_aligned_profile_line(
                view, roi_rect, result, end, quality_colour, 2
            )

        for position in result.consensus_xs:
            _draw_aligned_profile_line(
                view,
                roi_rect,
                result,
                float(position) / scale,
                quality_colour,
                1,
            )

    if sharpness is not None:
        sharp_label = f"SHARPNESS: {sharpness:.0f}"
        cv2.putText(
            view,
            sharp_label,
            (x0, max(24, y0 - 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            quality_colour,
            2,
            cv2.LINE_AA,
        )

    _draw_panel(view, _result_lines(result, settings, status_message))
    controls = "SPACE capture | R reset | S save | Q/ESC quit"
    cv2.putText(
        view,
        controls,
        (20, height - 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (220, 220, 220),
        2,
        cv2.LINE_AA,
    )
    return view


def create_window(settings: StationSettings) -> None:
    cv2.namedWindow(settings.window_title, cv2.WINDOW_NORMAL)
    if settings.fullscreen:
        cv2.setWindowProperty(
            settings.window_title,
            cv2.WND_PROP_FULLSCREEN,
            cv2.WINDOW_FULLSCREEN,
        )


# ---------------------------------------------------------------------------
# Camera, saving and execution modes
# ---------------------------------------------------------------------------


def open_camera(settings: StationSettings) -> cv2.VideoCapture:
    # MJPG keeps a 2K-capable UVC camera usable over USB 2.0 when supported;
    # the shared helper prefers Media Foundation on Windows.
    capture, _ = open_camera_backend(
        settings.camera_index,
        settings.camera_width,
        settings.camera_height,
        settings.camera_fps,
        use_mjpg=True,
    )
    return capture


def capture_best_frame(
    capture: cv2.VideoCapture,
    settings: StationSettings,
) -> tuple[Optional[np.ndarray], Optional[float]]:
    frames: list[np.ndarray] = []
    for _ in range(settings.burst_frames):
        ok, frame = capture.read()
        if ok and frame is not None:
            frames.append(frame)
        if settings.burst_delay_ms:
            time.sleep(settings.burst_delay_ms / 1000.0)
    if not frames:
        return None, None

    best_frame = frames[0]
    best_score = -math.inf
    for frame in frames:
        roi, _ = crop_roi(frame, settings)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        score = sharpness_score(gray)
        if score > best_score:
            best_frame = frame
            best_score = score
    return best_frame, best_score


def result_as_json(result: CountResult) -> dict[str, Any]:
    data = asdict(result)
    data["consensus_xs"] = [float(value) for value in result.consensus_xs]
    data["votes"] = [int(value) for value in result.votes]
    return data


def save_result(
    frame_bgr: np.ndarray,
    roi_rect: tuple[int, int, int, int],
    result: CountResult,
    settings: StationSettings,
    prefix: str = "result",
) -> Path:
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = output_dir / f"{prefix}_{stamp}"
    annotated = draw_station_view(
        frame_bgr,
        roi_rect,
        result,
        None,
        settings,
        status_message="SAVED",
    )
    image_path = base.with_suffix(".jpg")
    json_path = base.with_suffix(".json")
    if not cv2.imwrite(str(image_path), annotated):
        raise OSError(f"Could not save image: {image_path}")
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result_as_json(result), handle, ensure_ascii=False, indent=2)
    return image_path


def print_result(result: Optional[CountResult]) -> None:
    if result is None:
        print("No reliable result. Check focus, lighting and ROI alignment.")
        return
    width = f"{result.width_px:.1f}px"
    if result.width_mm is not None:
        width += f" / {result.width_mm:.2f}mm"
    print(
        "Count={count}  Agreement={agreement:.0f}%  Product={product}  "
        "Color={color}  Width={width}  Pitch={pitch:.1f}px".format(
            count=result.count,
            agreement=result.agreement * 100.0,
            product=result.product_id,
            color=result.color,
            width=width,
            pitch=result.pitch_px,
        )
    )


def run_image(
    image_path: Path,
    settings: StationSettings,
    catalog: ProductCatalog,
    save: bool,
    no_display: bool,
) -> int:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        print(f"Could not load image: {image_path}")
        return 2
    roi, rect = crop_roi(image, settings)
    counter = ThreadCounter(settings.edge_weight, settings.count_axis)
    started = time.perf_counter()
    result = analyse_roi(roi, counter, settings, catalog)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    print_result(result)
    print(f"Processing time: {elapsed_ms:.0f} ms")

    if result is not None and save:
        saved = save_result(image, rect, result, settings, prefix=image_path.stem)
        print(f"Saved: {saved}")
    if no_display:
        return 0 if result is not None else 1

    create_window(settings)
    view = draw_station_view(
        image,
        rect,
        result,
        sharpness_score(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)),
        settings,
        status_message="IMAGE RESULT" if result is not None else "NO RESULT",
    )
    cv2.imshow(
        settings.window_title,
        resize_for_preview(view, settings.preview_width),
    )
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    return 0 if result is not None else 1


def run_live(
    settings: StationSettings,
    catalog: ProductCatalog,
    no_display: bool,
) -> int:
    capture = open_camera(settings)
    if not capture.isOpened():
        print(
            f"Cannot open camera index {settings.camera_index}. "
            "Check Windows camera permission and the USB connection."
        )
        return 2

    actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Camera opened at {actual_width}x{actual_height}")
    print("SPACE=capture  R=reset  S=save  Q/ESC=quit")

    if no_display:
        print("Live mode requires a display; use --image with --no-display.")
        capture.release()
        return 2

    create_window(settings)
    counter = ThreadCounter(settings.edge_weight, settings.count_axis)
    last_result: Optional[CountResult] = None
    last_frame: Optional[np.ndarray] = None
    sharpness: Optional[float] = None
    status_message = "PRESS SPACE"
    tick = 0

    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                status_message = "FRAME READ FAILED"
                break

            tick += 1
            if tick % 8 == 0:
                roi, _ = crop_roi(frame, settings)
                sharpness = sharpness_score(
                    cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                )
            view = draw_station_view(
                frame,
                crop_roi(frame, settings)[1],
                last_result,
                sharpness,
                settings,
                status_message=status_message,
            )
            cv2.imshow(
                settings.window_title,
                resize_for_preview(view, settings.preview_width),
            )
            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (ord("r"), ord("R")):
                counter.reset_calibration()
                last_result = None
                last_frame = None
                status_message = "CALIBRATION RESET"
                continue
            if key in (ord("s"), ord("S")) and last_result is not None and last_frame is not None:
                saved = save_result(
                    last_frame,
                    crop_roi(last_frame, settings)[1],
                    last_result,
                    settings,
                )
                status_message = f"SAVED {saved.name}"
                print(f"Saved: {saved}")
                continue
            if key != ord(" "):
                continue

            print(f"Capturing {settings.burst_frames} frames...", flush=True)
            started = time.perf_counter()
            best_frame, best_sharpness = capture_best_frame(capture, settings)
            if best_frame is None:
                status_message = "CAPTURE FAILED"
                continue
            best_roi, _ = crop_roi(best_frame, settings)
            counter.reset_calibration()
            last_result = analyse_roi(best_roi, counter, settings, catalog)
            last_frame = best_frame
            sharpness = best_sharpness
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            print_result(last_result)
            print(f"Capture + processing: {elapsed_ms:.0f} ms")
            status_message = "RESULT READY" if last_result is not None else "NO RELIABLE RESULT"
    finally:
        capture.release()
        cv2.destroyAllWindows()
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fixed-camera elastic thread counter; OpenCV + NumPy only."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("station_config.json"),
        help="station JSON configuration",
    )
    parser.add_argument(
        "--products",
        type=Path,
        default=Path(__file__).with_name("products.json"),
        help="user-defined product rule JSON",
    )
    parser.add_argument("--camera", type=int, default=None, help="camera index override")
    parser.add_argument("--image", type=Path, help="run once on an image instead of the camera")
    parser.add_argument(
        "--process-width",
        type=int,
        default=None,
        help="processing max side override in pixels",
    )
    parser.add_argument(
        "--pixels-per-mm",
        type=float,
        default=None,
        help="calibration scale; width_mm = width_px / pixels_per_mm",
    )
    parser.add_argument(
        "--polarity",
        choices=("auto", "black", "white"),
        default=None,
        help="expected thread polarity override",
    )
    parser.add_argument(
        "--pitch",
        type=float,
        default=None,
        help="known thread pitch in processing pixels; optional rescue for weak contrast",
    )
    parser.add_argument("--windowed", action="store_true", help="do not use fullscreen")
    parser.add_argument("--save", action="store_true", help="save image-mode result")
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="print image-mode result without opening an OpenCV window",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.config)
    if args.camera is not None:
        settings.camera_index = args.camera
    if args.process_width is not None:
        settings.process_max_side = args.process_width
    if args.pixels_per_mm is not None:
        settings.pixels_per_mm = args.pixels_per_mm
    if args.polarity is not None:
        settings.polarity = args.polarity
    if args.pitch is not None:
        settings.pitch_override_px = args.pitch
    if args.windowed:
        settings.fullscreen = False
    settings.validated()

    try:
        catalog = ProductCatalog.from_file(args.products)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Could not load product catalog: {error}")
        return 2

    if args.image:
        return run_image(
            args.image,
            settings,
            catalog,
            save=args.save,
            no_display=args.no_display,
        )
    return run_live(settings, catalog, no_display=args.no_display)


if __name__ == "__main__":
    raise SystemExit(main())
