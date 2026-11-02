# MBS-lite Design Spec

**Date:** 2026-06-12  
**Status:** Implemented (v1)

## Goal

Model-Based Segmentation lite: fit an LV endocardial open arc from three landmarks (septal MA, lateral MA, apex), output a standard `Contour` with `source="model"`, and reuse existing Simpson volume pipeline and node editing.

## Prerequisites (Phase 0 — Open Arc)

Completed as foundation:

- `contour_geometry.py`: B-spline sampling, equal arc-length resample, node drag resample
- `Contour`: `mitral_annulus`, `num_nodes`, `closed_polygon_points()` (arc + MA chord)
- `lvef_simpson.py`: MA→apex long axis, per-disk diameters (bug fix), closed polygon for width
- Viewer **C**: staged workflow MA septal → MA lateral → arc clicks → Enter

## MBS-lite v1

### Domain

| Module | Role |
|--------|------|
| `lv_shape_template.py` | Canonical A4C arc as barycentric weights over truncated oval (elliptic dome over MA) |
| `mbs_lite_service.py` | `fit_contour_from_landmarks()` → `Contour(source="model")` |

**Warp:** sinusoidal dome over MA chord — `base(t) + sin(πt)·(apex − MA_mid)`, 81 samples → `resample_open_arc()` to 32 nodes.

**Validation:**

- MA length ≥ 10 px
- Apex distance from MA line ≥ 3 px

### Viewer UX

| Control | Action |
|---------|--------|
| **Simpson → 4C/2C → Diastole/Systole** | Jump to ED/ES frame, start MBS-lite (3-click model contour) |
| **LV-2D → All Diastole** | IVSd → LVEDD → LVPWd caliper sequence |
| **LV-2D → ESD Systole** | LVESD caliper |
| **Left atrium → LA AP / LAV** | LA AP: linear caliper; LAV: closed LA contour (area) + LAL length → ASE area-length |
| **Right ventricle → RV basal / TAPSE** | Linear calipers |

Keyboard **M** still works when main window has focus; primary workflow is via buttons.

**Frame overlay:** top-left on viewer shows measurements for the current frame only; clears on frame change.

**Visual:** `source="model"` contours render green (`#4caf50`). Manual = orange, AI = cyan.

**Editing:** Node drag uses `move_node_and_resample`; `source` stays `"model"`.

### Out of scope (v1.1)

- Gradient snap to image edges
- Separate A2C template
- Temporal propagation ED→ES

### Limitations

- v1 uses `CANONICAL_LV_ARC_A4C` for all views
- No gradient refinement; shape is purely landmark-driven

## Verification

```bash
uv run pytest tests/unit -q
uv run ruff check src tests
```

Manual: load cine → **M** × 3 on ED → green contour + EDV; drag node → volume updates; **C** for manual comparison.
