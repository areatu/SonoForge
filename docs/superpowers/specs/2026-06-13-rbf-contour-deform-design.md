# RBF Contour Deformation Design Spec

**Date:** 2026-06-13  
**Status:** Approved  
**Reference:** `B-plane-IDW-⁄RBF.md` (QLAB Philips–style editing)  
**Predecessor:** [2026-06-13-mbs-advanced-design.md](./2026-06-13-mbs-advanced-design.md)

## Goal

Replace index-based local node drag (`drag_node_local`) with **Gaussian RBF weighted displacement** from cursor position. Nodes remain visible and are the only drag handles (variant C). Behavior targets QLAB Philips soft-brush contour editing.

## Decisions (approved)

| Topic | Choice |
|-------|--------|
| Interaction | **C** — visible nodes; drag starts on node; weights from cursor only |
| Open-arc MA endpoints | **A** — pinned (`w = 0`); interior nodes only |
| Weight kernel | **Gaussian RBF** (QLAB-like soft brush; not IDW in v1) |
| σ (influence radius) | **C** — zoom-adaptive: constant screen brush, σ in image px |
| Contour scope | **C** — all contours (open-arc LV/MBS + closed LA/AI/manual) |
| Visual feedback | **A** — highlight nodes with `w_i > 0.1` during drag |
| Architecture | **Approach 1** — thin domain functions + Viewer changes |

## Architecture

```
_ContourNodeItem.mouseDragEvent
  └─ ViewerWidget._drag_contour_point / _finalize_contour_point_drag
       ├─ sigma_from_view_range(view)           # presentation helper
       ├─ gaussian_weights(points, cursor, σ, pinned)
       ├─ apply_gaussian_displacement(...)      # domain, vectorized numpy
       ├─ update node positions + RBF highlight
       ├─ _refresh_rendered_contour_geometry    # spline line
       └─ on release: resample, sync MA, contours_changed
```

**Domain layer:** pure functions in `contour_geometry.py` — no Qt dependencies.  
**Presentation layer:** drag session state, σ from viewBox, node highlighting.

## Mathematical model

### Gaussian weights

For control points `P_i = (x_i, y_i)` and cursor `C`:

```
d_i = ||P_i - C||_2
w_i = exp(-d_i² / 2σ²)     if i not pinned
w_i = 0                    if i ∈ pinned
```

### Displacement (incremental per mouse-move)

```
Δ = C_current - C_previous
P_i' = P_i + Δ * w_i * K
```

| Constant | Default | Meaning |
|----------|---------|---------|
| `SIGMA_SCREEN_PX` | `40.0` | Visual brush radius on screen (px) |
| `SENSITIVITY_K` | `1.5` | Displacement gain |
| `WEIGHT_ACTIVE_THRESHOLD` | `0.1` | Node highlight cutoff |
| `MIN_DELTA_NORM` | `1e-3` | Ignore micro-jitter |

### σ from zoom

```python
x0, x1 = view.viewRange()[0]
viewport_w = max(view.width(), 1)
scale = (x1 - x0) / viewport_w          # image px per screen px
sigma_image = SIGMA_SCREEN_PX * scale
```

ViewBox pan/zoom is currently disabled; viewRange ≈ frame size. Formula is forward-compatible when zoom is enabled.

## Open-arc vs closed

| Type | `pinned` | Post-step | On release |
|------|----------|-----------|------------|
| Open-arc (`mitral_annulus` set) | `{0, N-1}` | Snap `points[0]`, `points[-1]` to MA | `resample_open_arc`, sync annulus |
| Closed | `∅` | — | Existing closed resample / spline path |

MA chord line item is not updated during drag (endpoints fixed).

## Presentation: drag lifecycle

### Session state on `ViewerWidget`

```python
_drag_session: tuple[int, float, float] | None = None
# (contour_index, last_cursor_x, last_cursor_y)
```

| Event | Action |
|-------|--------|
| First `mouseMove` in drag | Init session; no displacement |
| Subsequent `mouseMove` | Compute Δ; if `‖Δ‖ < MIN_DELTA_NORM` skip; else RBF step |
| `mouseRelease` | Final RBF step; resample; reset session + node styles; emit `contours_changed` |

During drag: update points, nodes, spline line. **Do not** emit `contours_changed` until release (unchanged from current behavior).

### Node highlighting

`_ContourNodeItem.set_rbf_highlight(*, active: bool, base_pen)`:

- `w_i > 0.1` → green `#4caf50`, size 12
- otherwise → contour source color (`manual` / `model` / `ai`), size 10
- On release: restore all nodes to inactive style

## Domain API (new)

```python
def gaussian_weights(
    points: Sequence[tuple[float, float]],
    cursor: tuple[float, float],
    sigma: float,
    pinned_indices: frozenset[int] = frozenset(),
) -> np.ndarray: ...

def apply_gaussian_displacement(
    points: Sequence[tuple[float, float]],
    delta: tuple[float, float],
    weights: np.ndarray,
    *,
    sensitivity_k: float = SENSITIVITY_K,
) -> list[tuple[float, float]]: ...

def sigma_from_view_range(
    view_range_width: float,
    viewport_width_px: float,
    *,
    sigma_screen_px: float = SIGMA_SCREEN_PX,
) -> float: ...
```

**Requirements:** vectorized numpy for distances and weights; no Python loops over points for weight computation.

## Removed

- `drag_node_local()` and its tests
- Closed-contour branch that moves a single node without RBF

## Out of scope (v1)

- Drag on curve without grabbing a node
- IDW kernel or runtime σ/K UI
- Enabling ViewBox pan/zoom
- Changes to active contour refine (**R** hotkey)

## Testing

### Domain (`tests/unit/test_rbf_contour_deform.py`)

- Peak weight at cursor
- Monotonic decay with distance
- Pinned indices → zero weight
- Open-arc: endpoints unchanged after displacement
- Closed: all interior/exterior points move when near cursor
- Min-delta guard
- `sigma_from_view_range` scaling

### Viewer (`test_spline_editor.py` / `test_contour.py`)

- Open-arc mid-node drag: neighbors move, MA fixed
- Closed contour: multiple points shift
- Finalize: resample count, `contours_changed` emitted

Direct calls to `_drag_contour_point` / `_finalize_contour_point_drag` (no synthetic mouse events required).

## Edge cases

| Case | Behavior |
|------|----------|
| `N < 3` points | RBF applies; spline/resample as today |
| Drag MA node (index 0 or N−1) | All weights zero on pinned → no motion |
| Invalid cursor / None coords | Ignore event |
| Float drift on MA | Snap after each RBF step |
| Contour deleted mid-drag | Clear session on reindex/delete |

## Acceptance criteria

1. Drag on any contour produces smooth local deformation (no angular artifacts on rendered spline).
2. Open-arc MA endpoints never drift.
3. Typical full-frame view: brush affects ~3–5 nodes; tighter viewRange → narrower influence.
4. Active nodes highlighted green when `w > 0.1` during drag.
5. All unit tests pass; `ruff check src tests` clean.

## Verification

```bash
uv run pytest tests/unit/test_rbf_contour_deform.py tests/unit/test_spline_editor.py tests/unit/test_contour_geometry.py -v
uv run pytest tests/unit -q
uv run ruff check src tests
```

## Files to change

| File | Change |
|------|--------|
| `domain/services/contour_geometry.py` | Add RBF functions; remove `drag_node_local` |
| `presentation/viewer_widget.py` | Session state, RBF drag, node highlight |
| `tests/unit/test_rbf_contour_deform.py` | New domain tests |
| `tests/unit/test_contour_geometry.py` | Remove `drag_node_local` tests |
| `tests/unit/test_spline_editor.py` | RBF integration tests |
