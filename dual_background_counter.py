"""Grayscale counter for a vertical elastic raft on a dual background.

The module deliberately has no product-catalog or colour-classification logic.
It implements the phase-one decision path described by ADR-004 and uses only
OpenCV and NumPy so the same code can run on desktop Python and Raspberry Pi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class DualBackgroundConfig:
    min_count: int = 30
    max_count: int = 50
    max_tilt_deg: float = 15.0
    locator_max_side: int = 1024
    side_fraction: float = 0.05
    min_zone_height_fraction: float = 0.12
    min_raft_width_fraction: float = 0.12
    max_missing_boundaries: int = 2


@dataclass
class ZoneEvidence:
    name: str
    y0: int
    y1: int
    left: int
    right: int
    edge_score: float
    pitch_px: Optional[float] = None
    pitch_score: float = 0.0
    count: Optional[int] = None
    profile: Optional[np.ndarray] = field(default=None, repr=False)

    @property
    def width_px(self) -> int:
        return max(0, self.right - self.left)

    @property
    def quality(self) -> float:
        # Pitch may compensate for weak outer edges, as required by ADR-004.
        return float(np.clip(0.30 * self.edge_score + 0.70 * self.pitch_score, 0, 1))


@dataclass
class DualBackgroundResult:
    count: int
    pitch_px: float
    width_px: float
    left: int
    right: int
    top: int
    bottom: int
    seam_y: int
    seam_top: int
    seam_bottom: int
    boundaries_x: list[float]
    inferred_boundaries: list[bool]
    source_zone: str
    quality: float
    zones: list[ZoneEvidence]

    @property
    def centers_x(self) -> list[float]:
        return [
            (self.boundaries_x[index] + self.boundaries_x[index + 1]) / 2.0
            for index in range(self.count)
        ]


def _smooth(values: np.ndarray, sigma: float) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32).reshape(1, -1)
    return cv2.GaussianBlur(
        vector,
        (0, 0),
        sigmaX=max(0.5, float(sigma)),
        borderType=cv2.BORDER_REFLECT,
    ).ravel()


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    indices = np.flatnonzero(mask)
    if len(indices) == 0:
        return []
    output: list[tuple[int, int]] = []
    start = previous = int(indices[0])
    for raw in indices[1:]:
        value = int(raw)
        if value > previous + 1:
            output.append((start, previous))
            start = value
        previous = value
    output.append((start, previous))
    return output


def _robust_scale(values: np.ndarray) -> tuple[float, float]:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    return median, max(1e-6, 1.4826 * mad)


def detect_background_seam(
    gray: np.ndarray,
    config: DualBackgroundConfig,
) -> tuple[int, int, int]:
    """Return seam centre and adaptive exclusion-band top/bottom."""
    height, width = gray.shape
    side_width = max(12, int(round(width * config.side_fraction)))
    candidates: list[tuple[int, float, np.ndarray]] = []
    search_start = int(round(height * 0.20))
    search_end = int(round(height * 0.80))

    for side in (gray[:, :side_width], gray[:, width - side_width :]):
        row_profile = np.median(side.astype(np.float32), axis=1)
        row_profile = _smooth(row_profile, max(1.0, height / 500.0))
        gradient = np.abs(np.gradient(row_profile))
        local = gradient[search_start:search_end]
        if len(local) == 0:
            continue
        index = search_start + int(np.argmax(local))
        candidates.append((index, float(gradient[index]), gradient))

    if not candidates:
        raise ValueError("BACKGROUND SEAM NOT FOUND")

    seam_y = int(round(float(np.median([item[0] for item in candidates]))))
    gradient = np.mean(np.stack([item[2] for item in candidates]), axis=0)
    peak = float(gradient[seam_y])
    noise, noise_scale = _robust_scale(gradient[search_start:search_end])
    transition_threshold = max(noise + 3.0 * noise_scale, peak * 0.20)

    transition_top = seam_y
    while transition_top > 1 and gradient[transition_top - 1] >= transition_threshold:
        transition_top -= 1
    transition_bottom = seam_y
    while transition_bottom < height - 2 and gradient[transition_bottom + 1] >= transition_threshold:
        transition_bottom += 1

    thickness = max(1, transition_bottom - transition_top + 1)
    noise_ratio = float(np.clip(noise_scale / max(peak, 1e-6), 0.0, 1.0))
    safety = max(4, int(round(thickness * (1.0 + noise_ratio))))
    band_top = max(0, transition_top - safety)
    band_bottom = min(height - 1, transition_bottom + safety)
    return seam_y, band_top, band_bottom


def _locate_zone_bounds(
    gray: np.ndarray,
    name: str,
    y0: int,
    y1: int,
    config: DualBackgroundConfig,
) -> Optional[ZoneEvidence]:
    height, width = gray.shape
    if y1 - y0 < max(16, int(height * config.min_zone_height_fraction)):
        return None

    zone = gray[y0:y1].astype(np.float32)
    gradient_x = np.abs(np.diff(zone, axis=1))
    energy = gradient_x.mean(axis=0)
    sigma = max(2.0, width / 450.0)
    energy = _smooth(energy, sigma)
    low = float(np.percentile(energy, 20))
    high = float(np.percentile(energy, 95))
    dynamic = high - low
    if dynamic <= 1e-5:
        return None

    threshold = low + 0.23 * dynamic
    mask = (energy >= threshold).astype(np.uint8).reshape(1, -1)
    close_width = max(7, int(round(width / max(config.max_count, 1))))
    kernel = np.ones((1, close_width), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel).ravel() > 0

    min_width = int(round(width * config.min_raft_width_fraction))
    candidates = [run for run in _runs(mask) if run[1] - run[0] + 1 >= min_width]
    if not candidates:
        return None

    def run_score(run: tuple[int, int]) -> float:
        left, right = run
        local = np.maximum(0.0, energy[left : right + 1] - low)
        return float(local.mean() * np.sqrt(max(1, right - left + 1)))

    left, right = max(candidates, key=run_score)
    # Closing already bridges one strand pitch.  Keep locator padding small;
    # broad padding is an entire extra strand on fine-pitch products.
    padding = max(1, int(round(0.25 * sigma)))
    left = max(0, left - padding)
    right = min(width - 1, right + padding + 1)
    inside = float(np.mean(energy[left : max(left + 1, right)]))
    edge_score = float(np.clip((inside - low) / max(dynamic, 1e-6), 0.0, 1.0))
    return ZoneEvidence(name, y0, y1, left, right, edge_score)


def locate_dynamic_raft(
    gray: np.ndarray,
    seam_top: int,
    seam_bottom: int,
    config: DualBackgroundConfig,
) -> list[ZoneEvidence]:
    height = gray.shape[0]
    zones = []
    upper = _locate_zone_bounds(gray, "white", 0, seam_top, config)
    lower = _locate_zone_bounds(gray, "black", seam_bottom + 1, height, config)
    if upper is not None:
        zones.append(upper)
    if lower is not None:
        zones.append(lower)
    return zones


def _profile_for_zone(
    gray: np.ndarray,
    zone: ZoneEvidence,
    left: int,
    right: int,
) -> np.ndarray:
    pixels = gray[zone.y0 : zone.y1, left : right + 1].astype(np.float32)
    # A median profile rejects lint and isolated silicone/powder marks.
    return np.median(pixels, axis=0).astype(np.float32)


def _pitch_from_profile(
    profile: np.ndarray,
    config: DualBackgroundConfig,
) -> tuple[Optional[float], float, Optional[int]]:
    span = len(profile) - 1
    if span < config.min_count * 3:
        return None, 0.0, None

    trend = _smooth(profile, max(5.0, span / 28.0))
    signal = profile.astype(np.float32) - trend
    signal -= float(signal.mean())
    deviation = float(signal.std())
    if deviation <= 1e-5:
        return None, 0.0, None
    signal /= deviation

    min_lag = max(3, int(np.floor(span / config.max_count * 0.70)))
    max_lag = min(span // 3, int(np.ceil(span / config.min_count * 1.30)))
    candidates: list[tuple[float, int]] = []
    correlations: dict[int, float] = {}
    for lag in range(min_lag, max_lag + 1):
        value = float(np.mean(signal[:-lag] * signal[lag:]))
        correlations[lag] = value
    for lag in range(min_lag + 1, max_lag):
        value = correlations[lag]
        if value >= correlations[lag - 1] and value > correlations[lag + 1]:
            candidate_count = int(round(span / lag))
            if config.min_count <= candidate_count <= config.max_count:
                candidates.append((value, lag))
    if not candidates:
        return None, 0.0, None

    best_correlation = max(value for value, _ in candidates)
    strong = [
        (value, lag)
        for value, lag in candidates
        if value >= max(0.30, best_correlation * 0.82)
    ]
    # Autocorrelation is also strong at 2x/3x pitch.  The smallest strong
    # in-range local maximum is the fundamental strand pitch.
    correlation, lag = min(strong or candidates, key=lambda item: item[1])
    count = int(round(span / lag))
    pitch = span / float(count)

    gaps = []
    for multiple in (1, 2, 3):
        check_lag = int(round(pitch * multiple))
        if check_lag < len(signal):
            gaps.append(float(np.mean(signal[:-check_lag] * signal[check_lag:])))
    regularity = float(np.mean(gaps)) if gaps else correlation
    score = float(np.clip((0.65 * correlation + 0.35 * regularity + 0.10) / 1.10, 0, 1))
    return float(pitch), score, count


def _fused_bounds(zones: list[ZoneEvidence]) -> tuple[int, int, str]:
    strongest = max(zones, key=lambda zone: zone.edge_score)
    compatible = [strongest]
    tolerance = max(8, int(round(strongest.width_px * 0.08)))
    for zone in zones:
        if zone is strongest:
            continue
        if abs(zone.left - strongest.left) <= tolerance and abs(zone.right - strongest.right) <= tolerance:
            compatible.append(zone)
    weights = np.asarray([max(0.05, item.edge_score) for item in compatible], dtype=np.float32)
    left = int(round(float(np.average([item.left for item in compatible], weights=weights))))
    right = int(round(float(np.average([item.right for item in compatible], weights=weights))))
    return left, right, strongest.name


def _refine_boundaries(
    profile: np.ndarray,
    left: int,
    right: int,
    count: int,
    max_missing: int,
) -> tuple[list[float], list[bool]]:
    pitch = (right - left) / float(count)
    smoothed = _smooth(profile, max(0.7, pitch * 0.06))
    dynamic = float(np.percentile(smoothed, 98) - np.percentile(smoothed, 2))
    if dynamic <= 1e-5:
        return list(np.linspace(left, right, count + 1)), [True] * (count + 1)

    expected_local = np.linspace(0.0, len(profile) - 1.0, count + 1)
    search = max(2, int(round(pitch * 0.30)))

    def polarity_result(sign: float) -> tuple[float, list[float], list[bool]]:
        signal = sign * smoothed
        refined = [float(left)]
        inferred = [False]
        strengths = []
        for expected in expected_local[1:-1]:
            centre = int(round(expected))
            lo = max(1, centre - search)
            hi = min(len(signal) - 2, centre + search)
            if hi <= lo:
                refined.append(float(left + expected))
                inferred.append(True)
                strengths.append(0.0)
                continue
            index = lo + int(np.argmax(signal[lo : hi + 1]))
            shoulder = max(2, int(round(pitch * 0.35)))
            local_floor = max(
                float(np.min(signal[max(0, index - shoulder) : index + 1])),
                float(np.min(signal[index : min(len(signal), index + shoulder + 1)])),
            )
            strength = float(signal[index] - local_floor) / dynamic
            is_inferred = strength < 0.06
            refined.append(float(left + (expected if is_inferred else index)))
            inferred.append(is_inferred)
            strengths.append(max(0.0, strength))
        refined.append(float(right))
        inferred.append(False)
        return float(np.mean(strengths)) if strengths else 0.0, refined, inferred

    bright = polarity_result(1.0)
    dark = polarity_result(-1.0)
    _, boundaries, inferred = bright if bright[0] >= dark[0] else dark

    missing_run = 0
    for value in inferred[1:-1]:
        missing_run = missing_run + 1 if value else 0
        if missing_run > max_missing:
            # Keep the geometry for diagnostics; the caller lowers quality.
            break
    return boundaries, inferred


def analyse_dual_background(
    image_bgr: np.ndarray,
    config: Optional[DualBackgroundConfig] = None,
) -> Optional[DualBackgroundResult]:
    config = config or DualBackgroundConfig()
    if image_bgr is None or image_bgr.size == 0:
        return None
    gray = image_bgr if image_bgr.ndim == 2 else cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = gray.astype(np.uint8, copy=False)

    height, width = gray.shape
    locator_gray = gray
    locator_scale = 1.0
    longest_side = max(height, width)
    if config.locator_max_side > 0 and longest_side > config.locator_max_side:
        locator_scale = config.locator_max_side / float(longest_side)
        locator_gray = cv2.resize(
            gray,
            (
                max(1, int(round(width * locator_scale))),
                max(1, int(round(height * locator_scale))),
            ),
            interpolation=cv2.INTER_AREA,
        )

    locator_seam, locator_top, locator_bottom = detect_background_seam(
        locator_gray, config
    )
    locator_zones = locate_dynamic_raft(
        locator_gray, locator_top, locator_bottom, config
    )
    if locator_scale == 1.0:
        seam_y, seam_top, seam_bottom = locator_seam, locator_top, locator_bottom
        zones = locator_zones
    else:
        inverse = 1.0 / locator_scale
        seam_y = int(round(locator_seam * inverse))
        seam_top = int(round(locator_top * inverse))
        seam_bottom = int(round(locator_bottom * inverse))
        zones = [
            ZoneEvidence(
                name=zone.name,
                y0=max(0, int(round(zone.y0 * inverse))),
                y1=min(height, int(round(zone.y1 * inverse))),
                left=max(0, int(round(zone.left * inverse))),
                right=min(width - 1, int(round(zone.right * inverse))),
                edge_score=zone.edge_score,
            )
            for zone in locator_zones
        ]
    if not zones:
        return None
    left, right, bounds_source = _fused_bounds(zones)
    if right - left < config.min_count * 3:
        return None

    for zone in zones:
        profile = _profile_for_zone(gray, zone, left, right)
        pitch, score, count = _pitch_from_profile(profile, config)
        zone.profile = profile
        zone.pitch_px = pitch
        zone.pitch_score = score
        zone.count = count

    usable = [zone for zone in zones if zone.pitch_px is not None and zone.count is not None]
    if not usable:
        return None
    source = max(usable, key=lambda zone: zone.quality)
    compatible = [
        zone
        for zone in usable
        if abs(float(zone.pitch_px) - float(source.pitch_px)) / max(float(source.pitch_px), 1e-6) <= 0.15
    ]
    weights = np.asarray([max(0.05, zone.quality) for zone in compatible], dtype=np.float32)
    pitch = float(np.average([float(zone.pitch_px) for zone in compatible], weights=weights))
    count = int(round((right - left) / pitch))
    if not config.min_count <= count <= config.max_count:
        return None
    pitch = (right - left) / float(count)

    boundary_options = []
    for zone in compatible:
        zone_boundaries, zone_inferred = _refine_boundaries(
            zone.profile,
            left,
            right,
            count,
            config.max_missing_boundaries,
        )
        max_run = 0
        current = 0
        for missing in zone_inferred[1:-1]:
            current = current + 1 if missing else 0
            max_run = max(max_run, current)
        boundary_options.append(
            (
                max_run,
                sum(zone_inferred[1:-1]),
                -zone.quality,
                zone,
                zone_boundaries,
                zone_inferred,
            )
        )
    (
        max_missing_run,
        missing_total,
        _,
        boundary_source,
        boundaries,
        inferred,
    ) = min(boundary_options, key=lambda item: item[:3])
    if max_missing_run > config.max_missing_boundaries:
        return None
    completion_penalty = min(0.20, 0.02 * missing_total)
    quality = float(
        np.clip(
            np.average([zone.quality for zone in compatible], weights=weights)
            - completion_penalty,
            0,
            1,
        )
    )

    return DualBackgroundResult(
        count=count,
        pitch_px=pitch,
        width_px=float(right - left),
        left=left,
        right=right,
        top=0,
        bottom=gray.shape[0] - 1,
        seam_y=seam_y,
        seam_top=seam_top,
        seam_bottom=seam_bottom,
        boundaries_x=boundaries,
        inferred_boundaries=inferred,
        source_zone=(
            f"bounds:{bounds_source},pitch:fused,grooves:{boundary_source.name}"
        ),
        quality=quality,
        zones=zones,
    )


def classify_count_qc(visible_count: int, nominal_count: int) -> tuple[str, str]:
    """Return QC status and an operator-facing reason from count comparison."""
    if visible_count == nominal_count:
        return "PASS", ""
    if visible_count < nominal_count:
        return "FAIL", "MISSING/TORN EDGE"
    return "FAIL", "EXTRA STRANDS"


def draw_dual_background_result(
    image_bgr: np.ndarray,
    result: DualBackgroundResult,
    show_indices: bool = False,
    nominal_count: Optional[int] = None,
    product_name: Optional[str] = None,
) -> np.ndarray:
    output = image_bgr.copy()
    height, width = output.shape[:2]
    line_thickness = max(1, int(round(max(height, width) / 1200.0)))
    cv2.rectangle(
        output,
        (0, result.seam_top),
        (width - 1, result.seam_bottom),
        (0, 180, 255),
        line_thickness,
    )

    boundaries = [int(round(value)) for value in result.boundaries_x]
    for index in range(result.count):
        left = int(np.clip(boundaries[index], 0, width - 1))
        right = int(np.clip(boundaries[index + 1], 0, width - 1))
        centre = int(round((left + right) / 2.0))
        cv2.rectangle(
            output,
            (left, result.top),
            (right, result.bottom),
            (0, 210, 0),
            line_thickness,
        )
        cv2.line(
            output,
            (centre, result.top),
            (centre, result.bottom),
            (255, 80, 0),
            line_thickness,
        )
        if show_indices:
            index_text = str(index + 1)
            text_y = min(result.bottom - 4, result.top + 92 + (index % 3) * 22)
            text_x = max(0, centre - 7)
            cv2.putText(
                output,
                index_text,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                (0, 0, 0),
                3,
                cv2.LINE_AA,
            )
            cv2.putText(
                output,
                index_text,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )

    count_label = f"COUNT {result.count}"
    detail_label = (
        f"WIDTH {result.width_px:.0f}px   PITCH {result.pitch_px:.1f}px   "
        f"QUALITY {result.quality:.2f}"
    )
    panel_colour = (20, 20, 20)
    status_label = f"PRODUCT {product_name}" if product_name else "PRODUCT NO_MATCH"
    if nominal_count is not None:
        qc_status, qc_reason = classify_count_qc(result.count, nominal_count)
        status_label = f"EXPECTED {nominal_count}   QC {qc_status}"
        if qc_reason:
            status_label += f" - {qc_reason}"
        if product_name:
            status_label = f"PRODUCT {product_name}   {status_label}"
        panel_colour = (25, 125, 25) if qc_status == "PASS" else (20, 20, 180)
    panel_right = min(width - 12, max(780, int(len(status_label) * 18)))
    cv2.rectangle(
        output,
        (12, 12),
        (panel_right, 142),
        panel_colour,
        -1,
    )
    cv2.putText(
        output,
        count_label,
        (28, 68),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.45,
        (255, 255, 255),
        3,
        cv2.LINE_AA,
    )
    cv2.putText(
        output,
        detail_label,
        (30, 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        (230, 230, 230),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        output,
        status_label,
        (30, 130),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.68,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return output
