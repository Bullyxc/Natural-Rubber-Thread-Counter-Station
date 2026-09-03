"""
Camera Capture Test
===================

Small standalone camera utility for the Thread Counter Station. It does not
run the thread-counting algorithm; it only previews a UVC camera and saves raw
frames for later testing.

Controls:
    SPACE/S  save the current raw frame (and optional ROI crop)
    F       toggle fullscreen/windowed preview
    Q/ESC   quit

Examples:
    python camera_capture_test.py
    python camera_capture_test.py --camera 1 --windowed
    python camera_capture_test.py --save-dir image --save-roi
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from runtime_control import bootstrap_environment

bootstrap_environment()

import cv2

from camera_stream import (
    FpsMeter,
    LatestFrameReader,
    open_camera_backend,
    resize_for_preview,
)
from runtime_control import SystemMonitor, build_runtime_profile, configure_opencv


WINDOW_TITLE = "Thread Counter - Camera Capture Test"


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Camera config must be a JSON object: {path}")
    return data


def crop_roi_from_config(
    frame: Any,
    config: dict[str, Any],
) -> Any:
    processing = config.get("processing", {}) or {}
    roi = processing.get("roi", config.get("roi", {})) or {}
    height, width = frame.shape[:2]
    x = float(roi.get("x", 0.30))
    y = float(roi.get("y", 0.0))
    roi_width = float(roi.get("width", 0.40))
    roi_height = float(roi.get("height", 1.0))
    x0 = max(0, min(width - 1, int(round(width * x))))
    y0 = max(0, min(height - 1, int(round(height * y))))
    x1 = max(x0 + 1, min(width, int(round(width * (x + roi_width)))))
    y1 = max(y0 + 1, min(height, int(round(height * (y + roi_height)))))
    return frame[y0:y1, x0:x1]


def open_camera(
    camera_index: int,
    width: int,
    height: int,
    fps: int,
    use_mjpg: bool = True,
) -> cv2.VideoCapture:
    capture, _ = open_camera_backend(
        camera_index,
        width,
        height,
        fps,
        use_mjpg=use_mjpg,
    )
    return capture


def list_cameras(max_index: int = 8) -> None:
    """Probe camera indexes so the external USB camera index can be confirmed."""
    print(f"Probing camera indexes 0..{max_index - 1}...")
    for index in range(max_index):
        capture = open_camera(index, 640, 480, 15, use_mjpg=True)
        if not capture.isOpened():
            continue
        actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        ok, _ = capture.read()
        capture.release()
        state = "read OK" if ok else "opened, read failed"
        print(f"  index {index}: {actual_width}x{actual_height} ({state})")


def draw_status(
    frame: Any,
    camera_index: int,
    actual_width: int,
    actual_height: int,
    save_dir: Path,
    message: str,
) -> Any:
    view = frame.copy()
    height, width = view.shape[:2]
    lines = [
        "CAMERA CAPTURE TEST",
        f"CAMERA: {camera_index}   RESOLUTION: {actual_width}x{actual_height}",
        f"SAVE DIR: {save_dir}",
        f"STATUS: {message}",
    ]
    panel_width = max(
        cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.68, 2)[0][0]
        for line in lines
    ) + 32
    panel_height = 30 * len(lines) + 18
    panel_x1 = min(width, 14 + panel_width)
    panel_y1 = min(height, 14 + panel_height)
    panel = view[14:panel_y1, 14:panel_x1]
    if panel.size:
        panel[:] = (panel.astype("float32") * 0.28).astype("uint8")
    for index, line in enumerate(lines):
        cv2.putText(
            view,
            line.encode("ascii", "replace").decode("ascii"),
            (24, 44 + index * 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            (240, 240, 240),
            2,
            cv2.LINE_AA,
        )
    cv2.putText(
        view,
        "SPACE/S save raw frame | F fullscreen | Q/ESC quit",
        (20, height - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (230, 230, 230),
        2,
        cv2.LINE_AA,
    )
    return view


def next_capture_path(save_dir: Path, prefix: str = "capture") -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    candidate = save_dir / f"{prefix}_{stamp}.jpg"
    suffix = 1
    while candidate.exists():
        candidate = save_dir / f"{prefix}_{stamp}_{suffix:02d}.jpg"
        suffix += 1
    return candidate


def save_frame(
    frame: Any,
    save_dir: Path,
    config: dict[str, Any],
    save_roi: bool,
) -> tuple[Path, Optional[Path]]:
    save_dir.mkdir(parents=True, exist_ok=True)
    image_path = next_capture_path(save_dir)
    if not cv2.imwrite(str(image_path), frame):
        raise OSError(f"Could not save image: {image_path}")

    roi_path: Optional[Path] = None
    if save_roi:
        roi = crop_roi_from_config(frame, config)
        roi_path = image_path.with_name(image_path.stem + "_roi.jpg")
        if not cv2.imwrite(str(roi_path), roi):
            raise OSError(f"Could not save ROI image: {roi_path}")
    return image_path, roi_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview a USB camera and save raw frames for inspection."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("station_config.json"),
        help="station JSON configuration",
    )
    parser.add_argument("--camera", type=int, default=None, help="camera index override")
    parser.add_argument(
        "--runtime-profile",
        choices=("auto", "desktop", "rpi5-passive"),
        default=None,
        help="runtime tuning; auto detects Raspberry Pi 5",
    )
    parser.add_argument("--width", type=int, default=None, help="requested camera width")
    parser.add_argument("--height", type=int, default=None, help="requested camera height")
    parser.add_argument("--fps", type=int, default=None, help="requested camera FPS")
    parser.add_argument(
        "--preview-width",
        type=int,
        default=None,
        help="display-copy width; saved frames remain full camera resolution",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=None,
        help="directory for captured JPG files (default: image)",
    )
    parser.add_argument(
        "--save-roi",
        action="store_true",
        help="save the configured ROI as an additional *_roi.jpg file",
    )
    parser.add_argument("--windowed", action="store_true", help="start in a normal window")
    parser.add_argument(
        "--no-mjpg",
        action="store_true",
        help="do not request MJPG from the UVC camera",
    )
    parser.add_argument(
        "--list-cameras",
        action="store_true",
        help="probe camera indexes 0..7 and exit",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Could not load config: {error}")
        return 2

    camera_config = config.get("camera", {}) or {}
    camera_index = int(
        args.camera if args.camera is not None else camera_config.get("index", 1)
    )
    requested_width = int(args.width or camera_config.get("width", 2560))
    requested_height = int(args.height or camera_config.get("height", 1440))
    requested_fps = int(args.fps or camera_config.get("fps", 30))
    capture_config = config.get("capture", {}) or {}
    save_dir = args.save_dir or Path(capture_config.get("directory", "image"))
    save_roi = bool(args.save_roi or capture_config.get("save_roi", False))
    preview_width = int(
        args.preview_width or capture_config.get("preview_width", 1600)
    )
    runtime = build_runtime_profile(config, args.runtime_profile)
    configure_opencv(runtime)
    if runtime.max_preview_width is not None:
        preview_width = min(preview_width, runtime.max_preview_width)
    print(
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}; "
        f"runtime profile: {runtime.name}; OpenCV threads={cv2.getNumThreads()}, "
        f"preview limit={runtime.preview_fps:.0f} FPS"
    )

    if args.list_cameras:
        list_cameras()
        return 0

    capture, camera_info = open_camera_backend(
        camera_index,
        requested_width,
        requested_height,
        requested_fps,
        use_mjpg=not args.no_mjpg,
    )
    if not capture.isOpened():
        print(
            f"Cannot open camera {camera_index}. Check the USB connection, "
            "camera permission, and camera or /dev/video* index."
        )
        return 2

    actual_width = camera_info.actual_width
    actual_height = camera_info.actual_height
    print(
        f"Camera {camera_index}: requested {requested_width}x{requested_height}, "
        f"actual {actual_width}x{actual_height}, "
        f"backend {camera_info.backend}, driver FPS {camera_info.driver_fps:.1f}"
    )
    print(f"Saving raw frames to: {save_dir.resolve()}")
    print(
        f"Preview width: {preview_width}px; raw saved frames stay "
        f"{actual_width}x{actual_height}"
    )

    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
    fullscreen = not args.windowed
    if fullscreen:
        cv2.setWindowProperty(
            WINDOW_TITLE,
            cv2.WND_PROP_FULLSCREEN,
            cv2.WINDOW_FULLSCREEN,
        )

    reader = LatestFrameReader(capture).start()
    monitor = SystemMonitor(runtime)
    display_meter = FpsMeter()
    status = "READY"
    display_fps = 0.0
    last_sequence = -1
    next_preview_at = 0.0
    try:
        while True:
            packet = reader.wait_latest(
                after_sequence=last_sequence,
                timeout=0.02,
                copy=False,
            )
            if packet is None:
                cv2.waitKey(1)
                continue
            frame, sequence, timestamp = packet
            if frame is None:
                status = "FRAME READ FAILED"
                print(status)
                break

            now = time.monotonic()
            system_status = monitor.sample()
            preview_fps = monitor.preview_fps(system_status)
            is_new_frame = sequence != last_sequence
            if is_new_frame:
                last_sequence = sequence
            if is_new_frame and now >= next_preview_at:
                display_fps = display_meter.tick()
                live_status = (
                    f"{status} | CAP {reader.read_fps:.1f} FPS | "
                    f"DISPLAY {display_fps:.1f} FPS"
                )
                runtime_text = system_status.summary()
                if runtime_text:
                    live_status += f" | {runtime_text}"
                if now - timestamp > 2.0:
                    live_status += " | STALE FRAME"

                preview = resize_for_preview(frame, preview_width)
                view = draw_status(
                    preview,
                    camera_index,
                    actual_width,
                    actual_height,
                    save_dir,
                    live_status,
                )
                cv2.imshow(WINDOW_TITLE, view)
                next_preview_at = now + 1.0 / max(1.0, preview_fps)
            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (ord("f"), ord("F")):
                fullscreen = not fullscreen
                cv2.setWindowProperty(
                    WINDOW_TITLE,
                    cv2.WND_PROP_FULLSCREEN,
                    cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL,
                )
                status = "FULLSCREEN" if fullscreen else "WINDOWED"
                continue
            if key not in (ord("s"), ord("S"), ord(" ")):
                continue

            try:
                image_path, roi_path = save_frame(
                    frame,
                    save_dir,
                    config,
                    save_roi,
                )
                status = f"SAVED {image_path.name}"
                print(f"Saved: {image_path.resolve()}")
                if roi_path is not None:
                    print(f"Saved ROI: {roi_path.resolve()}")
            except OSError as error:
                status = "SAVE FAILED"
                print(error)
    finally:
        reader.stop()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
