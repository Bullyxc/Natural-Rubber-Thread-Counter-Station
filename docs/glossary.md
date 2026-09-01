# Thread Counter Station glossary

| Term | Meaning in this project |
| --- | --- |
| Station | The fixed camera, fixture, controlled lighting, computer, and display used for inspection. |
| ROI | Region of interest; the configured rectangle containing the elastic product. |
| Thread pitch | Approximate pixel distance between repeated thread peaks. |
| Polarity | Whether the useful thread response is brighter (`white`) or darker (`black`) than its local surroundings. |
| Top-hat | Morphological operation that extracts bright local structure from a line-shaped neighbourhood. |
| Black-hat | Morphological operation that extracts dark local structure from a line-shaped neighbourhood. |
| Gradient axis | Intensity-gradient response along the configured counting axis; it emphasizes repeated thread boundaries. |
| Strip vote | A count made independently in several horizontal slices of the ROI; the median is the station count. |
| Agreement | Fraction of non-empty strips that produced the final median count. |
| Consensus position | A thread x-position shared by strips whose count agrees with the final result. |
| Width (px) | Detected product span between the left and right profile bounds in original ROI pixels. |
| `pixels_per_mm` | Calibration scale; pixels per millimetre in the product plane. |
| Width (mm) | `width_px / pixels_per_mm`; shown only after a positive scale is configured. |
| Lightness | Median CIE-L value from the LAB colour space in the measured span. Used for black/white classification. |
| Product rule | One ordered JSON entry matching colour, count, and optionally calibrated width to a product ID. |
| NO_MATCH | Safe result when no configured product rule matches the measurement. |
