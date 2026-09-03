"""Evaluate the phase-one dual-background counter on labelled images."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2

from dual_background_counter import (
    DualBackgroundConfig,
    analyse_dual_background,
    classify_count_qc,
    draw_dual_background_result,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path(__file__).with_name("image") / "ground_truth.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("results") / "reference",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    with args.labels.open("r", encoding="utf-8") as handle:
        labels = json.load(handle)
    count_range = labels["phase_one_count_range"]
    config = DualBackgroundConfig(
        min_count=int(count_range["minimum"]),
        max_count=int(count_range["maximum"]),
    )
    args.output.mkdir(parents=True, exist_ok=True)

    failures = 0
    print(
        "file\tvisible_expected\tnominal\tdetected\tqc_expected\tqc_detected\t"
        "pitch_px\twidth_px\tquality\tms\tsource"
    )
    for sample in labels["samples"]:
        path = args.labels.parent / sample["file"]
        visible_expected = int(sample["visible_strand_count"])
        nominal = int(sample["nominal_strand_count"])
        qc_expected = str(sample["expected_qc"]).upper()
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        started = time.perf_counter()
        result = analyse_dual_background(image, config) if image is not None else None
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if result is None:
            failures += 1
            print(
                f"{path.name}\t{visible_expected}\t{nominal}\tNO RESULT\t"
                f"{qc_expected}\t-\t-\t-\t-\t{elapsed_ms:.1f}\t-"
            )
            continue
        qc_detected, _ = classify_count_qc(result.count, nominal)
        passed = result.count == visible_expected and qc_detected == qc_expected
        failures += 0 if passed else 1
        print(
            f"{path.name}\t{visible_expected}\t{nominal}\t{result.count}\t"
            f"{qc_expected}\t{qc_detected}\t{result.pitch_px:.2f}\t"
            f"{result.width_px:.0f}\t{result.quality:.3f}\t{elapsed_ms:.1f}\t"
            f"{result.source_zone}"
        )
        annotated = draw_dual_background_result(
            image,
            result,
            show_indices=True,
            nominal_count=nominal,
        )
        output_path = args.output / f"{path.stem}_annotated.jpg"
        cv2.imwrite(str(output_path), annotated, [cv2.IMWRITE_JPEG_QUALITY, 92])

    print(f"summary\t{len(labels['samples']) - failures}/{len(labels['samples'])} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
