# ADR-001: Use an inspectable classical-vision pipeline

- Status: Accepted for the first station prototype
- Date: 2026-08-10

## Context

The station uses a fixed NEOCoolcam NE-82534053 UVC webcam with a manual
2.8--12 mm lens to inspect elastic products. The output must be explainable at
the station: operators need to see the ROI, measured product span, detected
thread positions, count agreement, colour decision, and the configured product
rule that matched. The first release must run on a computer with Python 3.10
and must not require a machine-learning model.

The main image risks are uneven illumination, silicone/flour residue joining
neighbouring threads, motion blur, and USB 2.0 bandwidth limits.

## Decision

Use the following pipeline in `thread_counter_station.py`:

1. Capture a short burst and select the sharpest ROI using variance of
   Laplacian.
2. Crop a fixed, user-configured rectangular ROI and downscale only when the
   requested processing side is exceeded.
3. Apply bilateral/Gaussian smoothing and CLAHE, then generate a white- or
   black-top-hat feature along the thread axis.
4. Fuse that morphology response with the absolute gradient along the
   counting axis. The polarity and `count_axis` can be forced in
   `station_config.json`.
5. Estimate thread pitch from repeated local maxima using a small NumPy-only
   peak finder. Count peaks independently in multiple horizontal strips.
6. Use the median strip count, strip agreement, valley checks, and uniform-gap
   checks as the quality gate. Draw the consensus positions back on the live
   frame.
7. Measure the detected span in pixels. Convert to millimetres only when the
   station has a measured `pixels_per_mm` calibration.
8. Classify black/white from calibrated LAB lightness thresholds, then apply
   ordered rules in `products.json` to identify the configured product type.

## Why this decision

- Every decision is visible in the image overlay and can be tuned from JSON.
- OpenCV and NumPy are widely deployable on Python 3.10 and avoid a model
  download, GPU, and training dataset.
- Multi-strip voting is more tolerant of local residue and partial occlusion
  than relying on one profile across the entire ROI.
- Separating measurement from product rules lets the image algorithm stay
  generic while the factory defines its own products.

## Rejected alternatives for this release

- **Object-detection/segmentation model:** would require labeled images,
  model lifecycle, and a confidence policy that is not yet defined.
- **One global threshold:** too sensitive to backlight falloff and dark/white
  product changes.
- **Edge-only counting:** silicone/ flour residue can produce extra edges;
  the morphology response plus valley and strip checks is a safer first pass.
- **Hard-coded product names in Python:** makes recipe changes require a code
  deployment and risks stale production rules.

## Consequences

The station works best when the product is flat, parallel to the image axes,
and illuminated consistently. Strong perspective, crossing threads, or
specular glare can produce `NO RESULT` or low agreement. The operator should
fix focus/lighting/ROI before relaxing thresholds. Each saved result includes
an annotated JPG and a JSON record so failed decisions can be audited.

## Calibration and acceptance plan

1. Lock the manual lens focus/zoom and camera exposure/white balance.
2. Capture at least 20--30 images for every real product and both requested
   colours.
3. Measure a known reference length in the same plane to set
   `pixels_per_mm`.
4. Tune ROI, `edge_weight`, lightness thresholds, and product ranges using a
   held-out image set.
5. Accept a production recipe only after count, colour, width, and product
   match are reviewed together with the overlay and agreement value.
