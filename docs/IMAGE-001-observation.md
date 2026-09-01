# IMAGE-001: first real sample observation

- Source: `image/WIN_20260730_04_26_07_Pro.jpg`
- Image size: 1920 x 1080 pixels
- Product appearance: dark/black elastic band spanning almost the full image
  width, with repeated horizontal thread ridges.
- Background: corrugated metal with strong vertical structures, dirt marks, and
  non-uniform illumination.
- Useful counting direction: Y. The repeated thread positions are horizontal
  lines, so the profile must run over rows and the voting strips must be
  vertical slices.

## Initial station settings for this sample

The settings were changed from the first generic prototype to:

```json
{
  "count_axis": "y",
  "num_strips": 12,
  "edge_weight": 0.20,
  "roi": {
    "x": 0.30,
    "y": 0.0,
    "width": 0.40,
    "height": 1.0
  }
}
```

The requested full-height ROI now runs from the centre 40% of the image width
and covers 100% of the image height. The band locator finds the product around
Y=429--715 in this sample. With that full-height ROI, the current smoke test
returns a preliminary count of 37, agreement 38%, and a detected span of about
278 original pixels. The earlier 40/100% result came from a Y-limited ROI and
must not be treated as production ground truth. The full-height version needs
further tuning against a manually verified sample and repeated images under
controlled lighting.

The background's vertical ribs explain why averaging across the width and
counting along Y is preferable for this sample. Keep the ROI away from large
background seams when the fixture is redesigned.

## Tilt correction smoke test

The station now supports `alignment.mode = "auto"`. It estimates the correction
angle from Hough line segments and, when those segments are ambiguous, searches
for the angle that produces the most regular repeated edge profile. The ROI is
rotated only for processing; the consensus lines are transformed back to the
original frame for the overlay.

Using synthetic rotations of this sample, the current implementation detected
corrections of approximately -15, +12, -21.5, -29.5, and +30.5 degrees for
source rotations of +15, -12, +22, +30, and -30 degrees. The corresponding
counts were 36--39 with agreement between 55% and 75%. These are algorithm
smoke tests, not production acceptance values; a manually verified image set
is still required before setting a quality gate for the station.
