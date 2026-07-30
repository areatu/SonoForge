# Plan: AI-Assisted Manual LA Contour (A+B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace the pure-geometric elliptical template in manual LA contouring with an AI-segmented contour (from the existing LA ONNX model), refined by edge-snap. User clicks 3 landmarks → system runs LA inference → presents AI-derived contour snapped to actual image boundaries → user drags nodes to fine-tune.

**Architecture:** The existing LA inference pipeline (`OnnxInferenceEngine` → `la_mask_to_contour()`) produces a contour from the segmentation mask. The existing magnetic edge-snap system (`contour_edge_snap.py`) pulls nodes toward myocardial boundaries. The missing piece is connecting these two: when the user clicks 3 landmarks for LA, also trigger LA inference and use the AI contour as the initial shape instead of the pure elliptical template.

**Tech Stack:** PySide6, PyQtGraph, ONNX Runtime, NumPy, SciPy (existing stack)

---

## Current State Analysis

### Manual LA flow (current):
```
User clicks 3 landmarks (septal, lateral, apex)
  → fit_contour_from_landmarks(chamber="LA")
    → _warp_elliptical_open_arc() [pure geometry, NO image awareness]
    → resample_open_arc_landmarks() → 32-node contour
  → source="manual"
  → User drags nodes manually
  → On release: _apply_magnetic_snap_to_contour() [Sobel edge snap]
```

### AI LA flow (current):
```
"LAV 4C AI" button clicked
  → OnnxWorker(la_inference) → async inference
  → la_mask_to_contour(mask) → elliptical template from mask landmarks
  → quality gate → source="ai", review_pending=True
  → User reviews/accepts
```

### Problem:
The manual contour starts as a **pure half-ellipse** (short_axis_ratio=0.85) with zero image awareness. The magnetic edge-snap only activates on drag release, so the initial shape is far from actual LA walls. User must drag many nodes to get a reasonable contour.

### Solution (A+B combined):
After 3 clicks, run LA inference **in parallel** with the geometric fit. Use the AI mask to derive better landmarks and contour shape. Apply edge-snap to the initial contour. Present to user for fine-tuning.

---

## Global Constraints

- Python `>=3.10,<3.12`
- PySide6 `>=6.6`
- LA model only works on **A4C ES** frames (hardcoded in `request_la_auto_segment`)
- Existing quality gate must be respected
- Magnetic edge-snap system must be reused, not duplicated
- Contour data model: `Contour` frozen dataclass in `domain/models/contour.py`

---

## Task 1: Extract LA landmarks from mask as fallback for manual clicks

**Problem:** When user clicks 3 landmarks manually, the AI mask may produce better landmark positions. We need a function that extracts septal/lateral/apex from the AI mask and can optionally replace or blend with user-provided landmarks.

**Files:**
- Modify: `src/echo_personal_tool/domain/services/la_segmentation_service.py`

- [x] **Step 1: Create `la_landmarks_from_mask_or_user()` function**

Add a new function in `la_segmentation_service.py` that takes both the AI mask and user-provided landmarks, and returns the best landmarks:

```python
def la_landmarks_from_mask_or_user(
    mask: np.ndarray,
    *,
    user_septal: tuple[float, float] | None = None,
    user_lateral: tuple[float, float] | None = None,
    user_apex: tuple[float, float] | None = None,
    blend_factor: float = 0.7,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Extract LA landmarks from AI mask, optionally blending with user clicks.

    Returns (septal, lateral, apex). If user landmarks are None,
    uses pure AI landmarks. Otherwise blends: result = AI * blend_factor + user * (1 - blend_factor).
    """
    ai_septal, ai_lateral, ai_apex = _la_landmarks_from_mask(_largest_component(np.asarray(mask) > 0))

    if user_septal is None or user_lateral is None or user_apex is None:
        return ai_septal, ai_lateral, ai_apex

    def _blend(
        ai: tuple[float, float],
        user: tuple[float, float],
        w: float,
    ) -> tuple[float, float]:
        return (
            ai[0] * w + user[0] * (1 - w),
            ai[1] * w + user[1] * (1 - w),
        )

    return (
        _blend(ai_septal, user_septal, blend_factor),
        _blend(ai_lateral, user_lateral, blend_factor),
        _blend(ai_apex, user_apex, blend_factor),
    )
```

- [x] **Step 2: Write unit test**

Create `tests/unit/test_la_landmarks_blend.py`:

```python
import numpy as np
import pytest

from echo_personal_tool.domain.services.la_segmentation_service import (
    la_landmarks_from_mask_or_user,
)


@pytest.fixture()
def dummy_mask():
    """Synthetic LA mask: ellipse in center of 224x224 image."""
    mask = np.zeros((224, 224), dtype=bool)
    # Draw filled ellipse
    cy, cx = 112, 112
    for y in range(224):
        for x in range(224):
            if ((x - cx) / 50) ** 2 + ((y - cy) / 80) ** 2 <= 1:
                mask[y, x] = True
    return mask.astype(np.uint8) * 255


def test_pure_ai_landmarks(dummy_mask):
    septal, lateral, apex = la_landmarks_from_mask_or_user(dummy_mask)
    assert septal is not None
    assert lateral is not None
    assert apex is not None
    # Apex should be above MA (smaller y = superior in image coords)
    assert apex[1] < septal[1]


def test_blended_landmarks(dummy_mask):
    user_septal = (80.0, 180.0)
    user_lateral = (140.0, 180.0)
    user_apex = (112.0, 40.0)
    septal, lateral, apex = la_landmarks_from_mask_or_user(
        dummy_mask,
        user_septal=user_septal,
        user_lateral=user_lateral,
        user_apex=user_apex,
        blend_factor=0.5,
    )
    # Blended result should be between AI and user
    assert septal[0] != user_septal[0]  # Not pure user
    assert septal[0] != 112.0  # Not pure center
```

- [x] **Step 3: Run test**

```bash
python -m pytest tests/unit/test_la_landmarks_blend.py -v
```

- [x] **Step 4: Commit**

```bash
git add src/echo_personal_tool/domain/services/la_segmentation_service.py tests/unit/test_la_landmarks_blend.py
git commit -m "feat(la): add landmark blending function for AI-assisted manual contour"
```

---

## Task 2: Add `_request_la_assist_for_manual()` to AppController

**Problem:** The manual contour flow needs to trigger LA inference asynchronously and apply the result when ready.

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py`

- [x] **Step 1: Add LA assist method**

Add a new method to `AppController` that triggers LA inference for manual contour assist. This is a simplified version of `request_la_auto_segment()` that blends AI landmarks with user landmarks:

```python
def request_la_assist_for_manual(
    self,
    *,
    frame_index: int,
    user_septal: tuple[float, float],
    user_lateral: tuple[float, float],
    user_apex: tuple[float, float],
) -> None:
    """Run LA inference to assist manual contour placement.

    Blends AI-derived landmarks with user-provided ones, then
    creates a contour with the blended shape.
    """
    from echo_personal_tool.domain.services.la_segmentation_service import (
        la_landmarks_from_mask_or_user,
        la_mask_to_contour,
    )

    # Find the frame data
    frame_data = self._get_frame_for_segmentation(frame_index)
    if frame_data is None:
        return

    # Run inference (reuse existing OnnxWorker pattern)
    worker = OnnxWorker(
        frame=frame_data,
        manifest_section="la_inference",
    )
    worker.signals.finished.connect(
        lambda result: self._on_la_assist_finished(
            result=result,
            user_septal=user_septal,
            user_lateral=user_lateral,
            user_apex=user_apex,
            frame_index=frame_index,
        )
    )
    worker.signals.error.connect(lambda err: None)  # Silent fallback
    self._threadpool.start(worker)
```

- [x] **Step 2: Add completion handler**

```python
def _on_la_assist_finished(
    self,
    *,
    result,
    user_septal: tuple[float, float],
    user_lateral: tuple[float, float],
    user_apex: tuple[float, float],
    frame_index: int,
) -> None:
    """Handle LA inference result for manual contour assist."""
    from echo_personal_tool.domain.services.la_segmentation_service import (
        la_landmarks_from_mask_or_user,
        la_mask_to_contour,
    )
    from echo_personal_tool.domain.services.mbs_lite_service import (
        fit_contour_from_landmarks,
    )
    from echo_personal_tool.domain.models.contour import Contour
    from dataclasses import replace

    mask = result.get("mask")
    if mask is None or mask.sum() < 80:
        return  # Fallback: keep geometric ellipse

    try:
        # Blend AI landmarks with user landmarks
        blended_septal, blended_lateral, blended_apex = la_landmarks_from_mask_or_user(
            mask,
            user_septal=user_septal,
            user_lateral=user_lateral,
            user_apex=user_apex,
            blend_factor=0.7,
        )

        # Build contour from blended landmarks
        contour = fit_contour_from_landmarks(
            septal=blended_septal,
            lateral=blended_lateral,
            apex=blended_apex,
            phase="ES",
            view="A4C",
            chamber="LA",
        )
        contour = replace(
            contour,
            source="manual",
            frame_index=frame_index,
            review_pending=False,
        )

        # Emit for viewer to pick up
        self.la_assist_contour_ready.emit(contour)

    except (ValueError, Exception):
        pass  # Silently fall back to geometric ellipse
```

- [x] **Step 3: Add signal**

Add signal to `AppController`:

```python
la_assist_contour_ready = Signal(object)
```

- [x] **Step 4: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py
git commit -m "feat(la): add async LA assist for manual contour in AppController"
```

---

## Task 3: Integrate LA assist into manual contour flow in ViewerWidget

**Problem:** When the user completes 3 clicks for LA, the viewer should trigger LA assist and replace the geometric ellipse with the AI-derived contour.

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

- [x] **Step 1: Modify `_finish_manual_contour()` to trigger LA assist**

After the geometric contour is created, if chamber is "LA" and view is "A4C" and phase is "ES", trigger LA assist:

```python
def _finish_manual_contour(self, *, apex: tuple[float, float]) -> bool:
    if self._active_mitral_annulus is None:
        return False

    septal, lateral = self._active_mitral_annulus
    chamber = self._active_contour_chamber.upper()
    if chamber in {"LV", "LA", "RA", "RV"}:
        try:
            contour = fit_contour_from_landmarks(
                septal=septal,
                lateral=lateral,
                apex=apex,
                phase=self._active_contour_phase or "ED",
                view=self._active_contour_view,
                chamber=chamber,
            )
        except ValueError as exc:
            self.contour_landmark_rejected.emit(str(exc))
            return False
        contour = replace(
            contour,
            source="manual",
            frame_index=self._contour_frame_index(),
            apex_landmark=apex,
        )

        # --- NEW: Trigger LA assist for A4C ES ---
        if (
            chamber == "LA"
            and self._active_contour_view == "A4C"
            and (self._active_contour_phase or "ED") == "ES"
            and self._app_controller is not None
        ):
            self._request_la_assist_for_manual(
                septal=septal,
                lateral=lateral,
                apex=apex,
                frame_index=self._contour_frame_index(),
            )
        # --- END NEW ---

    else:
        raw_arc = [septal, apex, lateral]
        resampled = resample_open_arc(raw_arc, num_nodes=DEFAULT_NODE_COUNT)
        contour = Contour(
            phase=self._active_contour_phase or "ED",
            view=self._active_contour_view,
            chamber=self._active_contour_chamber,
            mitral_annulus=self._active_mitral_annulus,
            points=resampled,
            num_nodes=DEFAULT_NODE_COUNT,
            frame_index=self._contour_frame_index(),
        )
    self._clear_active_contour_drawing()
    self.set_contour_from_domain(contour)
    self.contour_completed.emit(contour)
    return True
```

- [x] **Step 2: Add `_request_la_assist_for_manual()` to ViewerWidget**

```python
def _request_la_assist_for_manual(
    self,
    *,
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    frame_index: int,
) -> None:
    """Request LA AI assist for the current manual contour."""
    if self._app_controller is None:
        return
    # Connect signal (once)
    if not hasattr(self, "_la_assist_connected"):
        self._app_controller.la_assist_contour_ready.connect(self._on_la_assist_contour_ready)
        self._la_assist_connected = True

    self._app_controller.request_la_assist_for_manual(
        frame_index=frame_index,
        user_septal=septal,
        user_lateral=lateral,
        user_apex=apex,
    )


def _on_la_assist_contour_ready(self, contour) -> None:
    """Replace current LA contour with AI-assisted version."""
    if contour.chamber != "LA":
        return
    # Find and replace the existing LA contour
    for i, c in enumerate(self._contours):
        if c.chamber == "LA" and c.view == contour.view and c.phase == contour.phase:
            self._contours[i] = contour
            self._refresh_contour_display(i)
            # Apply magnetic snap to refine edges
            self._apply_magnetic_snap_to_contour(
                i,
                np.ones(len(contour.points)),
                grab_index=None,
            )
            self.contours_changed.emit(self.contours())
            break
```

- [x] **Step 3: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat(la): integrate AI assist into manual LA contour flow"
```

---

## Task 4: Add edge-snap to initial contour placement

**Problem:** The initial AI-assisted contour should be edge-snapped before presenting to the user, not just on drag release.

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

- [x] **Step 1: Apply edge-snap in `_on_la_assist_contour_ready()`**

Update the handler to apply edge-snap immediately after replacing the contour:

```python
def _on_la_assist_contour_ready(self, contour) -> None:
    """Replace current LA contour with AI-assisted version."""
    if contour.chamber != "LA":
        return
    for i, c in enumerate(self._contours):
        if c.chamber == "LA" and c.view == contour.view and c.phase == contour.phase:
            self._contours[i] = contour
            self._refresh_contour_display(i)
            # Apply magnetic snap immediately
            edge_map = self._get_edge_map()
            if edge_map is not None:
                from echo_personal_tool.domain.services.contour_edge_snap import (
                    apply_soft_magnetic_snap,
                    magnetic_edge_snap_config_for_source,
                )

                weights = np.ones(len(contour.points))
                pinned = self._pinned_indices_for_contour(contour)
                config = magnetic_edge_snap_config_for_source(contour.source)
                snapped = apply_soft_magnetic_snap(
                    list(contour.points),
                    weights,
                    edge_map,
                    strength=0.8,
                    max_radial_px=15.0,
                    weight_threshold=0.0,
                    config=config,
                    pinned_indices=pinned,
                    grab_index=None,
                )
                contour.points[:] = snapped
                self._snap_open_arc_endpoints(contour)
                self._refresh_contour_display(i)
            self.contours_changed.emit(self.contours())
            break
```

- [x] **Step 2: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat(la): apply edge-snap to initial AI-assisted manual contour"
```

---

## Task 5: Add "LAV 4C AI+" button with AI-assisted manual mode

**Problem:** Add a new UI button that triggers the AI-assisted manual flow (3 clicks → AI refinement).

**Files:**
- Modify: `src/echo_personal_tool/presentation/measurement_tools_panel.py`

- [x] **Step 1: Add button**

In the measurement tools panel, add a new button next to existing "LAV 4C" and "LAV 4C AI" buttons:

```python
# In the LA measurement section
self._btn_lav4c_ai_plus = QPushButton("LAV 4C AI+")
self._btn_lav4c_ai_plus.setToolTip("AI-assisted LA contour: click 3 landmarks, AI refines shape")
self._btn_lav4c_ai_plus.clicked.connect(lambda: self.tool_selected.emit("lav4c_ai_plus"))
```

- [x] **Step 2: Handle in main_window.py**

In `main_window.py`, handle the new tool:

```python
elif tool == "lav4c_ai_plus":
    self._viewer.set_contour_mode(
        chamber="LA",
        view="A4C",
        phase="ES",
        source="manual_ai_assist",
    )
```

- [x] **Step 3: Commit**

```bash
git add src/echo_personal_tool/presentation/measurement_tools_panel.py src/echo_personal_tool/presentation/main_window.py
git commit -m "feat(ui): add LAV 4C AI+ button for AI-assisted manual contour"
```

---

## Task 6: Write integration tests

**Files:**
- Create: `tests/unit/test_la_assist_integration.py`

- [x] **Step 1: Write tests**

```python
"""Tests for AI-assisted manual LA contour integration."""

import numpy as np
import pytest
from dataclasses import replace

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.la_segmentation_service import (
    la_landmarks_from_mask_or_user,
    la_mask_to_contour,
)
from echo_personal_tool.domain.services.mbs_lite_service import (
    fit_contour_from_landmarks,
)


@pytest.fixture()
def synthetic_la_mask():
    """Binary mask simulating LA cavity in 224x224 frame."""
    mask = np.zeros((224, 224), dtype=np.uint8)
    cy, cx = 112, 100
    for y in range(224):
        for x in range(224):
            if ((x - cx) / 55) ** 2 + ((y - cy) / 75) ** 2 <= 1:
                mask[y, x] = 255
    return mask


def test_manual_contour_starts_as_ellipse():
    """Verify manual contour is initially a pure ellipse (no AI)."""
    contour = fit_contour_from_landmarks(
        septal=(80.0, 180.0),
        lateral=(140.0, 180.0),
        apex=(112.0, 40.0),
        phase="ES",
        view="A4C",
        chamber="LA",
    )
    assert contour.chamber == "LA"
    assert contour.source == "model"
    assert len(contour.points) == 32
    # Endpoints should be at MA
    assert contour.points[0] == (80.0, 180.0)
    assert contour.points[-1] == (140.0, 180.0)


def test_ai_landmarks_differ_from_geometric(synthetic_la_mask):
    """AI-derived landmarks should differ from pure geometric ellipse."""
    ai_septal, ai_lateral, ai_apex = la_landmarks_from_mask_or_user(synthetic_la_mask)
    # AI landmarks come from mask, not from user clicks
    assert ai_septal is not None
    assert ai_lateral is not None
    assert ai_apex is not None


def test_blend_shifts_toward_ai(synthetic_la_mask):
    """Blended landmarks should be closer to AI than pure user clicks."""
    user_septal = (60.0, 190.0)
    user_lateral = (160.0, 190.0)
    user_apex = (112.0, 30.0)

    blended = la_landmarks_from_mask_or_user(
        synthetic_la_mask,
        user_septal=user_septal,
        user_lateral=user_lateral,
        user_apex=user_apex,
        blend_factor=0.7,
    )
    ai = la_landmarks_from_mask_or_user(synthetic_la_mask)

    # Blended should be 70% AI + 30% user
    for b, a, u in zip(blended, ai, [user_septal, user_lateral, user_apex]):
        assert abs(b[0] - a[0]) < abs(u[0] - a[0])  # Closer to AI
```

- [x] **Step 2: Run tests**

```bash
python -m pytest tests/unit/test_la_assist_integration.py -v
```

- [x] **Step 3: Commit**

```bash
git add tests/unit/test_la_assist_integration.py
git commit -m "test(la): add integration tests for AI-assisted manual contour"
```

---

## Verification

After all tasks:

1. **Unit tests pass:**
```bash
python -m pytest tests/unit/test_la_landmarks_blend.py tests/unit/test_la_assist_integration.py -v
```

2. **Lint passes:**
```bash
ruff check src/echo_personal_tool/domain/services/la_segmentation_service.py
ruff check src/echo_personal_tool/application/app_controller.py
ruff check src/echo_personal_tool/presentation/viewer_widget.py
```

3. **Manual verification:**
- Open SonoForge with an A4C ES DICOM file
- Click "LAV 4C AI+" button
- Click 3 landmarks (septal, lateral, apex)
- Verify: contour appears AI-derived (not pure ellipse)
- Verify: contour nodes are close to LA wall boundaries
- Drag a node → verify magnetic snap still works on release

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Blend AI + user landmarks (70/30)** | User landmarks provide anatomical context (where they think the walls are), AI provides accuracy. 70% AI weight ensures the contour is mostly accurate while respecting user intent. |
| **Async inference** | LA inference takes ~200ms. Running async keeps UI responsive. If inference fails, fall back to geometric ellipse. |
| **Edge-snap on initial placement** | Apply `apply_soft_magnetic_snap()` immediately after AI contour is placed, not just on drag release. This gives the user a good starting point. |
| **New "LAV 4C AI+" button** | Don't modify existing "LAV 4C" or "LAV 4C AI" buttons. Additive change, no breaking existing workflow. |
| **LA A4C ES only** | The LA model is trained on A4C ES frames. Restrict assist to this view/phase combination. Other views fall back to geometric ellipse. |

---

## Open Questions for User

1. **Blend factor:** Should it be 70% AI / 30% user, or should the user control this via a slider?

2. **Fallback behavior:** If LA inference fails or mask is too small, should the system:
   - A) Fall back silently to geometric ellipse (current plan)?
   - B) Show a notification "AI assist unavailable, using geometric template"?

3. **Edge-snap strength:** The initial snap uses `strength=0.8, max_radial_px=15.0`. Should these be configurable?

4. **Existing "LAV 4C AI" button:** Should it also benefit from edge-snap on initial placement, or keep its current behavior?
