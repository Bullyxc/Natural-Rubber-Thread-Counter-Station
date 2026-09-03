# ADR-004: Dual-background grayscale counting phase

## Status

Accepted for phase-one implementation.

## Context

The station must count physical elastic strands in a vertically presented raft without a machine-learning model. Products can be black, white or have weak local contrast, and different products can use substantially different strand sizes. A white upper background and black lower background provide complementary evidence. The horizontal background seam must not become a false strand feature.

## Decision

- Detect the background seam from every frame and exclude its measured transition thickness plus an adaptive safety margin.
- Locate the raft from a reduced-resolution full frame, then process a dynamic horizontal ROI around the complete raft.
- Analyse trusted white- and black-background zones independently in grayscale.
- Permit compatible outer bounds from one zone and pitch/groove evidence from the other zone to form one complete frame result.
- Estimate pitch independently in every frame. Do not carry a product pitch from another sample.
- Treat outer bounds and completed internal grooves as a boundary sequence. `COUNT = boundary count - 1`.
- Fill no more than two consecutive missing internal grooves. Infer an outer boundary by no more than one pitch per side and only with weak supporting image evidence.
- Compensate tilt up to ±15 degrees from vertical. Reject larger angles with `ALIGN PRODUCT`.
- For phase one, accept only candidate counts from 30 through 50. This is a temporary experiment constraint.
- Phase-one output is count, continuous centerline and box overlays, and raft width in pixels. Colour, millimetre width and product lookup are deferred.
- Keep visible count separate from nominal product count. When a nominal count is supplied by test metadata or a future product rule, equality is `QC PASS`; a mismatch is `QC FAIL`. Never overwrite a measured visible count with the nominal value.
- Product matching is optional metadata and never gates counting. A complete visible `COUNT` must still be displayed when no product pitch rule matches; in that case product and expected/QC metadata are unavailable or `NO_MATCH`.

## Reference data

The initial labelled set is recorded in `image/ground_truth.json`. Samples 01 and 03 have visible and nominal count 40 with expected `QC PASS`. Sample 02 is a torn-edge QC reference with visible count 37, nominal count 40 and expected `QC FAIL`.

## Consequences

The existing fixed central ROI and direct peak counter cannot be the production decision path for this layout. The new path requires explicit failure reasons and evidence scores so weak images fail safely instead of being forced into the allowed count range.
