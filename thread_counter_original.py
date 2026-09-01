"""
thread_counter.py
=================
Rubber thread counter for fixed camera station.
Direct Python port of ConductorCounter.kt with a live camera UI.

Requirements:
    pip install opencv-python numpy scipy

Usage:
    python thread_counter.py                  # webcam (index 0)
    python thread_counter.py --camera 1        # second camera
    python thread_counter.py --image pic.jpg   # single image file
    python thread_counter.py --scale 1280      # processing resolution

Controls (live mode):
    SPACE           capture 5 frames, pick sharpest, count
    R               reset calibration
    S               save last result image
    Q / ESC         quit
"""
import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import cv2
import numpy as np
from scipy.signal import find_peaks as scipy_find_peaks


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class Params:
    tophat_kw: int
    distance: int
    border_margin: int
    smooth_win: int
    merge_max: int


@dataclass
class StripResult:
    y0: int
    y1: int
    cy: int
    count: int
    peaks: np.ndarray
    uniform: bool


@dataclass
class CountResult:
    count: int
    agreement: float
    pitch: float
    polarity: str
    x_left: int
    x_right: int
    consensus_xs: list[float]
    tier1_count: int
    tier2_count: int
    spread: int
    votes: list[int]


# ── Core counter ──────────────────────────────────────────────────────────────
class ConductorCounter:
    """
    Counts parallel rubber threads 
    from a grayscale image.
    Identical algorithm to 
    ConductorCounter.kt.
    """
    RECALIBRATE_EVERY = 60

    def __init__(self):
        self.reset_calibration()

    def reset_calibration(self):
        """Call when scene changes — new band, zoom, lighting."""
        self._locked_polarity: Optional[str] = None
        self._locked_pitch: Optional[float] = None
        self._locked_params: Optional[Params] = None
        self._frames_since_cal = 0

    def run(
        self,
        image: np.ndarray,          # BGR or grayscale uint8
        polarity: str = "auto",    # "auto" | "black" | "white"
        pitch_override: Optional[float] = None,
        center_fraction: float = 0.30,
        edge_threshold: float = 0.08,
        num_strips: int = 20,
    ) -> Optional[CountResult]:
        """
        Count threads in image.
        Returns CountResult or None if counting failed.
        """
        self._frames_since_cal += 1
        needs_cal = (
            self._locked_polarity is None
            or self._locked_pitch is None
            or self._frames_since_cal >= self.RECALIBRATE_EVERY
        )

        # Ensure grayscale
        if image.ndim == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # Blur: bilateral on calibration frames, Gaussian on fast frames
        smoothed = (
            self._bilateral(gray) if needs_cal
            else self._gaussian(gray)
        )
        enhanced = self._clahe(smoothed)

        # ── Calibration ───────────────────────────────────────────────────────
        if needs_cal:
            _, detected_pol = self._detect_polarity(enhanced, 15)
            chosen_pol = detected_pol if polarity == "auto" else polarity
            rough_feat = self._tophat(enhanced, 15, chosen_pol)
            rough_profile = self._mean_h_profile(rough_feat)
            est_pitch = (
                pitch_override
                or self._estimate_pitch(rough_profile, center_fraction)
            )
            if est_pitch is None:
                return None
            params = self._auto_params(est_pitch)
            feat2 = self._tophat(enhanced, params.tophat_kw, chosen_pol)
            profile2 = self._mean_h_profile(feat2)
            refined_pitch = (
                pitch_override
                or self._estimate_pitch(
                    profile2, center_fraction, min_pitch_scale=0.5
                )
                or est_pitch
            )
            self._locked_polarity = chosen_pol
            self._locked_pitch = refined_pitch
            self._locked_params = self._auto_params(refined_pitch)
            self._frames_since_cal = 0

        chosen_pol = self._locked_polarity
        final_pitch = self._locked_pitch
        final_params = self._locked_params

        # ── Counting ──────────────────────────────────────────────────────────
        feat = self._tophat(enhanced, final_params.tophat_kw, chosen_pol)
        full_profile = self._mean_h_profile(feat)
        smooth_full = self._smooth(full_profile)
        x_left, x_right = self._find_bounds(
            smooth_full, 
            final_params.border_margin, 
            edge_threshold
        )
        feat_f = feat.astype(np.float32)
        final_count, strips, votes = self._strip_vote(
            feat_f, final_params, x_left, x_right, num_strips
        )
        if final_count == 0 or not votes:
            return None

        # Pitch sanity check (after frame 10)
        band_width = float(x_right - x_left)
        if (final_pitch > 0 and band_width > 0 and self._frames_since_cal > 10):
            predicted = round(band_width / final_pitch)
            tolerance = max(3, int(predicted * 0.10))
            if abs(final_count - predicted) > tolerance:
                return None

        spread = max(votes) - min(votes)
        agreement = votes.count(final_count) / len(votes)
        tier1 = sum(
            1 for s in strips if s.count == final_count and s.uniform
        )
        tier2 = sum(
            1 for s in strips if s.count == final_count and not s.uniform
        )
        xs = self._consensus_positions(strips, final_count, x_left, x_right)

        return CountResult(
            count=final_count,
            agreement=agreement,
            pitch=final_pitch,
            polarity=chosen_pol,
            x_left=x_left,
            x_right=x_right,
            consensus_xs=xs,
            tier1_count=tier1,
            tier2_count=tier2,
            spread=spread,
            votes=votes,
        )

    # ── Image processing ──────────────────────────────────────────────────────
    @staticmethod
    def _bilateral(gray: np.ndarray) -> np.ndarray:
        return cv2.bilateralFilter(gray, 7, 40, 8)

    @staticmethod
    def _gaussian(gray: np.ndarray) -> np.ndarray:
        return cv2.GaussianBlur(gray, (7, 7), 2.0)

    @staticmethod
    def _clahe(gray: np.ndarray) -> np.ndarray:
        """CLAHE with contrast guard — skips if contrast < 6 (dark threads)."""
        std = gray.std()
        if std < 6.0:
            return gray.copy()
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(6, 6))
        return clahe.apply(gray)

    @staticmethod
    def _tophat(img: np.ndarray, kw: int, polarity: str) -> np.ndarray:
        kw = kw if kw % 2 == 1 else kw + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 1))
        op = (
            cv2.MORPH_TOPHAT if polarity == "white" else cv2.MORPH_BLACKHAT
        )
        return cv2.morphologyEx(img, op, kernel, borderType=cv2.BORDER_REFLECT)

    def _detect_polarity(
        self, enhanced: np.ndarray, kw: int
    ) -> tuple[np.ndarray, str]:
        white = self._tophat(enhanced, kw, "white")
        black = self._tophat(enhanced, kw, "black")
        if black.std() > white.std():
            return black, "black"
        return white, "white"

    @staticmethod
    def _mean_h_profile(feat: np.ndarray) -> np.ndarray:
        """Column-wise mean — shape (W,)."""
        return feat.astype(np.float32).mean(axis=0)

    @staticmethod
    def _smooth(profile: np.ndarray, window: int = 5) -> np.ndarray:
        kernel = np.ones(window) / window
        return np.convolve(profile, kernel, mode="same")

    # ── Peak finding ──────────────────────────────────────────────────────────
    @staticmethod
    def _find_peaks(
        signal: np.ndarray,
        min_distance: int,
        min_prominence: float,
    ) -> np.ndarray:
        peaks, _ = scipy_find_peaks(
            signal,
            distance=max(1, min_distance),
            prominence=min_prominence,
        )
        return peaks

    # ── Pitch estimation ──────────────────────────────────────────────────────
    def _estimate_pitch(
        self,
        profile: np.ndarray,
        center_fraction: float,
        min_pitch_scale: float = 1.0,
    ) -> Optional[float]:
        W = len(profile)
        margin = int(W * (1 - center_fraction) / 2)
        center = profile[margin: max(margin + 1, W - margin)]
        smoothed = self._smooth(center)
        rng = smoothed.max() - smoothed.min()
        min_prom = max(0.03 * rng, 1.0)
        peaks = self._find_peaks(
            smoothed, min_distance=2, min_prominence=min_prom
        )
        if len(peaks) < 2:
            return None
        gaps = np.diff(peaks).astype(float)
        valid = gaps[
            (gaps >= 3 * min_pitch_scale) & (gaps <= len(center) / 3)
        ]
        if len(valid) >= 2:
            return float(self._kde_pitch(valid))
        if len(gaps) > 0:
            return float(gaps.mean())
        return None

    @staticmethod
    def _kde_pitch(gaps: np.ndarray) -> float:
        if len(gaps) == 0:
            return 0.0
        n = len(gaps)
        mean = gaps.mean()
        std = gaps.std()
        iqr = np.percentile(gaps, 75) - np.percentile(gaps, 25)
        bw = 0.9 * min(std, iqr / 1.34) * (n ** -0.2)
        if bw <= 0:
            return float(gaps.mean())
        lo, hi = gaps.min(), gaps.max()
        xs = np.linspace(lo, hi, 500)
        density = np.array([
            np.exp(-0.5 * ((x - gaps) / bw) ** 2).sum()
            for x in xs
        ])
        best_x = float(xs[np.argmax(density)])
        close = gaps[np.abs(gaps - best_x) < best_x * 0.30]
        return float(np.median(close)) if len(close) >= 2 else best_x

    @staticmethod
    def _auto_params(pitch: float) -> Params:
        kw = max(5, int(pitch * 1.5))
        if kw % 2 == 0:
            kw += 1
        sw = max(3, int(pitch * 0.3))
        if sw % 2 == 0:
            sw += 1
        return Params(
            tophat_kw=kw,
            distance=max(2, int(pitch * 0.5)),
            border_margin=max(3, kw // 2),
            smooth_win=sw,
            merge_max=max(2, int(pitch * 0.25)),
        )

    # ── Band bounds ───────────────────────────────────────────────────────────
    @staticmethod
    def _find_bounds(
        profile: np.ndarray,
        border_margin: int,
        edge_threshold: float,
    ) -> tuple[int, int]:
        W = len(profile)
        thr = edge_threshold * profile.max()
        x_left = border_margin
        for x in range(border_margin, W // 2):
            if profile[x] >= thr:
                x_left = x
                break
        x_right = W - 1 - border_margin
        for x in range(W - 1 - border_margin, W // 2, -1):
            if profile[x] >= thr:
                x_right = x
                break
        return x_left, x_right

    # ── Strip voting ──────────────────────────────────────────────────────────
    def _count_peaks_in_strip(
        self,
        profile: np.ndarray,
        params: Params,
        x_left: int,
        x_right: int,
    ) -> tuple[int, np.ndarray, np.ndarray]:
        smoothed = self._smooth(profile, params.smooth_win)
        cable = (
            smoothed[x_left: x_right + 1]
            if x_left < x_right
            else smoothed
        )
        if len(cable) == 0:
            return 0, np.array([]), smoothed

        rng = float(cable.max() - cable.min())
        # Prominence threshold: 3% of range
        prom = max(0.03 * rng, 0.5)
        pitch = self._locked_pitch or float(params.distance)
        min_dist = max(params.distance, int(pitch * 0.55))
        pks = list(self._find_peaks(cable, min_dist, prom))

        # Edge rescue: 15% zones at both sides with 1.5% threshold
        edge_zone = int(len(cable) * 0.15)
        edge_prom = max(0.015 * rng, 0.3)
        left_pks = self._find_peaks(cable[:edge_zone], min_dist, edge_prom)
        for rp in left_pks:
            if all(abs(rp - p) >= min_dist for p in pks):
                pks.append(int(rp))
        right_start = len(cable) - edge_zone
        right_pks = self._find_peaks(
            cable[right_start:], min_dist, edge_prom
        ) + right_start
        for rp in right_pks:
            if all(abs(rp - p) >= min_dist for p in pks):
                pks.append(int(rp))
        pks.sort()

        # Merge very close peaks
        merged = []
        i = 0
        while i < len(pks):
            if (i + 1 < len(pks) and (pks[i + 1] - pks[i]) < params.merge_max):
                merged.append((pks[i] + pks[i + 1]) // 2)
                i += 2
            else:
                merged.append(pks[i])
                i += 1

        # Valley depth validation
        min_valley_drop = rng * 0.10
        validated = []
        for idx, curr in enumerate(merged):
            if idx == 0:
                validated.append(curr)
                continue
            prev = merged[idx - 1]
            seg = cable[prev: curr + 1]
            valley_min = seg.min() if len(seg) > 0 else 0.0
            left_val = cable[prev] if prev < len(cable) else 0.0
            right_val = cable[curr] if curr < len(cable) else 0.0
            drop = min(left_val, right_val) - valley_min
            if drop >= min_valley_drop:
                validated.append(curr)
            elif right_val > left_val:
                if validated:
                    validated.pop()
                validated.append(curr)

        # Uniform pitch check via coefficient of variation
        if len(validated) > 3:
            gaps = np.diff(validated).astype(float)
            mean_gap = gaps.mean()
            std_gap = gaps.std()
            cv = std_gap / mean_gap if mean_gap > 0 else 1.0
            max_cv = (
                0.28 if rng < 20 else
                0.22 if rng < 40 else 0.18
            )
            if cv > max_cv:
                return 0, np.array([]), smoothed

        global_peaks = np.array(validated) + x_left
        return len(validated), global_peaks, smoothed

    def _strip_vote(
        self,
        feat: np.ndarray,
        params: Params,
        x_left: int,
        x_right: int,
        num_strips: int,
    ) -> tuple[int, list[StripResult], list[int]]:
        H = feat.shape[0]
        strip_h = max(1, H // num_strips)
        strips: list[StripResult] = []
        votes: list[int] = []

        for i in range(num_strips):
            y0 = i * strip_h
            y1 = min(H, y0 + strip_h)
            if y0 >= y1:
                continue
            strip = feat[y0:y1, :]
            profile = strip.mean(axis=0)
            count, peaks, _ = self._count_peaks_in_strip(
                profile, params, x_left, x_right
            )
            uniform = False
            if len(peaks) > 1:
                gaps = np.diff(peaks.astype(float))
                med = np.median(gaps)
                uniform = bool(
                    med > 0
                    and np.all(np.abs(gaps - med) / med <= 0.25)
                )

            strips.append(
                StripResult(y0, y1, (y0 + y1) // 2, count, peaks, uniform)
            )
            if count > 0:
                votes.append(count)

        final = int(np.median(votes)) if votes else 0
        return final, strips, votes

    def _consensus_positions(
        self,
        strips: list[StripResult],
        final_count: int,
        x_left: int,
        x_right: int,
    ) -> list[float]:
        honest = [
            s for s in strips
            if s.count == final_count and len(s.peaks) == final_count and s.uniform
        ]
        if not honest:
            honest = [
                s for s in strips
                if s.count == final_count and len(s.peaks) == final_count
            ]
        if not honest:
            return []

        median_xs = np.array([
            float(np.median([s.peaks[slot] for s in honest]))
            for slot in range(final_count)
        ])
        diffs = np.diff(median_xs)
        pitch = float(np.median(diffs)) if len(diffs) > 0 else 0.0
        if pitch <= 0:
            return median_xs.tolist()

        x0_start = median_xs[0] - pitch
        x0_end = median_xs[0] + pitch
        x0_vals = np.linspace(x0_start, x0_end, 300)
        best_x0, best_err = median_xs[0], float("inf")
        for x0 in x0_vals:
            expected = x0 + np.arange(final_count) * pitch
            err = sum(
                float(np.min((median_xs - e) ** 2)) for e in expected
            )
            if err < best_err:
                best_err, best_x0 = err, x0

        xs = [best_x0 + k * pitch for k in range(final_count)]
        return [x for x in xs if x_left <= x <= x_right]


# ── Sharpness ─────────────────────────────────────────────────────────────────
def sharpness_score(gray: np.ndarray) -> float:
    """Laplacian variance — higher = sharper."""
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap.std() ** 2)


# ── Image preparation ─────────────────────────────────────────────────────────
def crop_roi(
    image: np.ndarray,
    width_frac: float = 0.8,
    height_frac: float = 0.2
) -> np.ndarray:
    """Crop center ROI — same logic as Android cropCenterROI()."""
    h, w = image.shape[:2]
    rw = int(w * width_frac)
    rh = int(h * height_frac) 
    x0 = (w - rw) // 2
    y0 = (h - rh) // 2
    return image[y0: y0 + rh, x0: x0 + rw]


def prepare_image(
    image: np.ndarray,
    target_size: int = 1920
) -> np.ndarray:
    """Resize to target_size on longest side, convert to gray."""
    h, w = image.shape[:2]
    scale = target_size / max(h, w)
    if scale < 1.0:
        image = cv2.resize(
            image,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_AREA,
        )
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


# ── Result overlay ────────────────────────────────────────────────────────────
def draw_result(
    image: np.ndarray,
    result: CountResult,
    scale_factor: float = 1.0,
) -> np.ndarray:
    """
    Draw thread lines and count badge onto a BGR copy of image.
    scale_factor maps consensus_xs (at processing scale) back to display scale.
    """
    vis = (
        image.copy() if image.ndim == 3
        else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    )
    h, w = vis.shape[:2]

    # Colour by agreement
    if result.agreement >= 0.70:
        colour = (0, 255, 220)   # cyan
    elif result.agreement >= 0.50:
        colour = (0, 220, 255)   # yellow
    else:
        colour = (0, 80, 255)    # red

    # Thread lines
    for x in result.consensus_xs:
        sx = int(x / scale_factor)
        cv2.line(vis, (sx, 0), (sx, h), colour, 1, cv2.LINE_AA)

    # Count badge — top left
    label = (
        f"Count: {result.count}  "
        f"Agree: {result.agreement*100:.0f}%  "
        f"Pitch: {result.pitch/scale_factor:.1f}px  "
        f"Pol: {result.polarity}"
    )
    (tw, th), bl = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(vis, (8, 8), (12 + tw, 20 + th + bl), (0, 0, 0), -1)
    cv2.putText(
        vis, label, (10, 18 + th),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2, cv2.LINE_AA
    )
    return vis


def draw_roi_guide(
    frame: np.ndarray,
    sharpness: Optional[float] = None
) -> np.ndarray:
    """Draw ROI rectangle and sharpness indicator on live preview."""
    vis = frame.copy()
    h, w = vis.shape[:2]
    rw = int(w * 0.8)
    rh = int(h * 0.2)
    x0 = (w - rw) // 2
    y0 = (h - rh) // 2

    # Sharpness colour
    if sharpness is None:
        colour = (180, 180, 180)
    elif sharpness >= 300:
        colour = (0, 230, 100)   # green
    elif sharpness >= 80:
        colour = (0, 210, 255)   # yellow
    else:
        colour = (50, 50, 255)   # red

    # ROI rectangle
    cv2.rectangle(vis, (x0, y0), (x0 + rw, y0 + rh), colour, 2)

    # Corner accents
    clen = 20
    for cx, cy in [
        (x0, y0), (x0 + rw, y0),
        (x0, y0 + rh), (x0 + rw, y0 + rh)
    ]:
        dx = 1 if cx == x0 else -1
        dy = 1 if cy == y0 else -1
        cv2.line(vis, (cx, cy), (cx + dx * clen, cy), (255, 255, 255), 3)
        cv2.line(vis, (cx, cy), (cx, cy + dy * clen), (255, 255, 255), 3)

    # Sharpness label
    if sharpness is not None:
        if sharpness >= 300:
            msg = "Sharp - ready"
        elif sharpness >= 80:
            msg = "Hold steadier"
        else:
            msg = "Too blurry - hold still"
        cv2.putText(
            vis, msg, (x0, y0 - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2, cv2.LINE_AA
        )

    # Controls hint
    cv2.putText(
        vis, "SPACE=capture  R=reset  S=save  Q=quit",
        (10, h - 12),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA
    )
    return vis


# ── Burst capture ─────────────────────────────────────────────────────────────
def capture_best_frame(
    cap: cv2.VideoCapture,
    n_frames: int = 5,
    process_size: int = 1280,
) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Grab n_frames rapidly, return (best_raw_bgr, best_roi_gray).
    Picks frame with highest sharpness on the ROI region.
    """
    frames = []
    for _ in range(n_frames):
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
        # Small delay lets the camera pipeline settle between frames
        time.sleep(0.05)

    if not frames:
        return None, None

    best_frame = None
    best_score = -1.0
    for frame in frames:
        roi = crop_roi(frame)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        score = sharpness_score(gray)
        if score > best_score:
            best_score = score
            best_frame = frame

    roi_gray = prepare_image(crop_roi(best_frame), process_size)
    return best_frame, roi_gray


# ── Single image mode ─────────────────────────────────────────────────────────
def run_on_image(
    path: str,
    process_size: int = 1280,
    save: bool = False,
) -> None:
    img = cv2.imread(path)
    if img is None:
        print(f"Could not load image: {path}")
        return

    counter = ConductorCounter()
    roi = crop_roi(img)
    gray = prepare_image(roi, process_size)
    scale = (
        process_size / max(roi.shape[:2])
        if max(roi.shape[:2]) > process_size
        else 1.0
    )

    print("Processing…")
    t0 = time.time()
    result = counter.run(gray, num_strips=20)
    elapsed = time.time() - t0

    if result is None:
        print("Could not count threads — check image quality and ROI alignment.")
        return

    print(f"\n{'─'*40}")
    print(f"  Count:      {result.count}")
    print(f"  Agreement:  {result.agreement*100:.0f}%")
    print(f"  Polarity:   {result.polarity}")
    print(f"  Pitch:      {result.pitch/scale:.1f} px (at original res)")
    print(f"  Time:       {elapsed*1000:.0f} ms")
    print(f"{'─'*40}\n")

    vis = draw_result(roi, result, scale_factor=scale)
    cv2.imshow("Thread Count", vis)

    if save:
        out = Path(path).with_suffix(".result.jpg")
        cv2.imwrite(str(out), vis)
        print(f"Saved → {out}")

    print("Press any key to close.")
    cv2.waitKey(0)
    cv2.destroyAllWindows()


# ── Live camera mode ──────────────────────────────────────────────────────────
def run_live(
    camera_index: int = 1,
    process_size: int = 1280,
    n_burst: int = 5,
) -> None:
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"Cannot open camera {camera_index}")
        return

    # Request high resolution from camera
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 4032)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 3024)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Camera {camera_index} opened at {actual_w}×{actual_h}")
    print("SPACE = capture  |  R = reset  |  S = save  |  Q/ESC = quit")

    counter = ConductorCounter()
    last_result: Optional[CountResult] = None
    last_vis: Optional[np.ndarray] = None
    sharpness: Optional[float] = None
    sharp_tick = 0
    save_counter = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Frame read failed.")
            break

        # Update sharpness every 8 frames (cheap)
        sharp_tick += 1
        if sharp_tick % 8 == 0:
            roi_small = crop_roi(frame)
            gray_small = cv2.cvtColor(roi_small, cv2.COLOR_BGR2GRAY)
            sharpness = sharpness_score(gray_small)

        preview = draw_roi_guide(frame, sharpness)

        # Overlay last result on preview
        if last_result is not None:
            h, w = frame.shape[:2]
            rw = int(w * 0.8)
            rh = int(h * 0.2)
            x0 = (w - rw) // 2
            y0 = (h - rh) // 2
            scale = (
                process_size / max(rh, rw)
                if max(rh, rw) > process_size
                else 1.0
            )

            # Draw thread lines on ROI region in preview
            colour = (
                (0, 255, 220) if last_result.agreement >= 0.70
                else (0, 210, 255) if last_result.agreement >= 0.50
                else (0, 80, 255)
            )
            for x in last_result.consensus_xs:
                sx = x0 + int(x / scale)
                cv2.line(
                    preview, (sx, y0), (sx, y0 + rh), colour, 1, cv2.LINE_AA
                )

            # Count badge
            badge = f"Count: {last_result.count}  ({last_result.agreement*100:.0f}%)"
            cv2.putText(
                preview, badge, (10, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 2, cv2.LINE_AA
            )

        cv2.imshow("Thread Counter — Camera Station", preview)
        key = cv2.waitKey(1) & 0xFF

        if key in (ord('q'), 27):    # Q or ESC
            break
        elif key == ord('r'):        # Reset calibration
            counter.reset_calibration()
            last_result = None
            print("Calibration reset.")
        elif key == ord('s') and last_vis is not None:
            save_counter += 1
            fname = f"result_{save_counter:03d}.jpg"
            cv2.imwrite(fname, last_vis)
            print(f"Saved → {fname}")
        elif key == ord(' '):        # Capture burst
            print(f"Capturing {n_burst} frames…", end=" ", flush=True)
            t0 = time.time()
            best_raw, roi_gray = capture_best_frame(cap, n_burst, process_size)
            if roi_gray is None:
                print("Capture failed.")
                continue
            counter.reset_calibration()
            result = counter.run(roi_gray, num_strips=20)
            elapsed = time.time() - t0
            if result is None:
                print("No result — reposition or improve lighting.")
                continue

            print(f"Done ({elapsed*1000:.0f} ms)")
            print(
                f"  Count: {result.count}  "
                f"Agreement: {result.agreement*100:.0f}%  "
                f"Polarity: {result.polarity}  "
                f"Pitch: {result.pitch:.1f}px"
            )

            # Build result display
            roi_display = crop_roi(best_raw)
            scale = (
                process_size / max(roi_display.shape[:2])
                if max(roi_display.shape[:2]) > process_size
                else 1.0
            )
            last_result = result
            last_vis = draw_result(roi_display, result, scale_factor=scale)
            cv2.imshow("Last Result", last_vis)

    cap.release()
    cv2.destroyAllWindows()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Rubber thread counter for camera station"
    )
    parser.add_argument(
        "--camera", type=int, default=1, help="Camera index (default: 1; USB camera)"
    )
    parser.add_argument(
        "--image", type=str, default=None, help="Path to image file (skips live mode)"
    )
    parser.add_argument(
        "--scale", type=int, default=1280, help="Processing resolution in pixels (default: 1280)"
    )
    parser.add_argument(
        "--burst", type=int, default=5, help="Number of frames in burst capture (default: 5)"
    )
    parser.add_argument(
        "--save", action="store_true", help="Auto-save result image (image mode only)"
    )
    args = parser.parse_args()

    if args.image:
        run_on_image(
            args.image, process_size=args.scale, save=args.save
        )
    else:
        run_live(
            camera_index=args.camera,
            process_size=args.scale,
            n_burst=args.burst,
        )


if __name__ == "__main__":
    main()
