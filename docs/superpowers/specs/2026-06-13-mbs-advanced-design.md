# MBS Advanced (v1.1) Design Spec

**Date:** 2026-06-13  
**Status:** Revised after clinical feedback  
**Predecessor:** [2026-06-12-mbs-lite-design.md](./2026-06-12-mbs-lite-design.md)

## Goal

Upgrade MBS-lite with optional border refinement. **ED→ES propagation removed** (ES always 3-click). **Auto-refine on 3rd click disabled** (opt-in via **R**).

## Template geometry

Primary warp: **sinusoidal dome over MA chord** (not barycentric triangle):

```
base = (1-t)*septal + t*lateral
lift = sin(π·phase(t)) * apex_lift_scale
point = base + lift * (apex - MA_mid)
```

A2C uses `ArcWarpProfile` with shifted peak (`peak_bias`) vs A4C.

## Active contour (opt-in)

- **R** hotkey on current frame **manual or model** LV open-arc contour → `refine_open_arc_contour()`
- Not run automatically after landmarks (US speckle unreliable in v1.1)

## ED→ES

**Out of scope:** ESV Auto always starts fresh 3-click workflow on ES frame.

## Verification

```bash
uv run pytest tests/unit/test_mbs_lite_service.py tests/unit/test_contour_geometry.py -v
uv run pytest tests/unit -q
```
