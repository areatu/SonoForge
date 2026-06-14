# LV Lamé Open-Arc Template (D1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace sinusoidal MA-chord warp with piecewise asymmetric Lamé open-arc for LV Manual and Model Simpson (A4C/A2C ED/ES), improving R-refine stability and visual closeness to manual contours.

**Architecture:** Pure-domain math in `lv_shape_template.py` (`LameWarpProfile`, `lame_lift_height`, `warp_lame_open_arc`); `mbs_lite_service.fit_contour_from_landmarks` calls Lamé warp for `chamber=="LV"`; `ViewerWidget._finish_manual_contour` uses the same warp for LV; refine passes regenerated Lamé template to `active_contour_refine`.

**Tech Stack:** Python 3.11+, NumPy, SciPy (`ndimage` unchanged), pytest, pytest-qt.

**Spec:** [2026-06-14-lv-lame-template-design.md](../specs/2026-06-14-lv-lame-template-design.md)

---

## File map

| File | Responsibility |
|------|----------------|
| `src/echo_personal_tool/domain/services/lv_shape_template.py` | `LameWarpProfile`, four presets, `lame_profile_for_view_phase`, `lame_lift_height`, `warp_lame_open_arc`; remove `ArcWarpProfile` / sinusoidal helpers |
| `src/echo_personal_tool/domain/services/mbs_lite_service.py` | LV fit via Lamé; `infer_apex_from_open_arc`, `build_lame_template_for_contour`; refine uses Lamé template |
| `src/echo_personal_tool/presentation/viewer_widget.py` | LV manual finish → Lamé warp + `source="manual"` |
| `tests/unit/test_lv_lame_template.py` | Domain math unit tests (new) |
| `tests/unit/test_mbs_lite_service.py` | Update imports/tests for Lamé; remove sinusoidal-specific tests |
| `tests/unit/test_viewer_manual_lame.py` | Viewer LV manual finish uses Lamé (new, small) |
| `CHANGELOG_SESSION.md` | One entry after implementation |

---

### Task 1: `lame_lift_height` — failing tests + implementation

**Files:**
- Create: `tests/unit/test_lv_lame_template.py`
- Modify: `src/echo_personal_tool/domain/services/lv_shape_template.py`

- [x] **Step 1: Write the failing tests**

Create `tests/unit/test_lv_lame_template.py`:

```python
"""Unit tests for LV Lamé open-arc template."""

from __future__ import annotations

import math

import pytest

from echo_personal_tool.domain.services.lv_shape_template import (
    LAME_A4C_ED,
    LAME_A4C_ES,
    LAME_A2C_ED,
    LAME_A2C_ES,
    LameWarpProfile,
    lame_lift_height,
    lame_profile_for_view_phase,
)


def test_lame_lift_height_zero_at_ma_endpoints() -> None:
    profile = LAME_A4C_ED
    u_apex = 0.5
    ma_length = 100.0
    assert lame_lift_height(0.0, u_apex, ma_length, profile) == pytest.approx(0.0, abs=1e-9)
    assert lame_lift_height(1.0, u_apex, ma_length, profile) == pytest.approx(0.0, abs=1e-9)


def test_lame_lift_height_peak_at_apex_projection() -> None:
    profile = LAME_A4C_ED
    u_apex = 0.5
    ma_length = 100.0
    peak = lame_lift_height(u_apex, u_apex, ma_length, profile)
    assert peak == pytest.approx(profile.lift_scale, abs=1e-6)
    assert peak > lame_lift_height(0.25, u_apex, ma_length, profile)
    assert peak > lame_lift_height(0.75, u_apex, ma_length, profile)


def test_lame_lift_height_monotonic_each_side() -> None:
    profile = LAME_A4C_ED
    u_apex = 0.5
    ma_length = 100.0
    septal_side = [
        lame_lift_height(u, u_apex, ma_length, profile)
        for u in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    ]
    lateral_side = [
        lame_lift_height(u, u_apex, ma_length, profile)
        for u in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    ]
    assert all(septal_side[i] <= septal_side[i + 1] for i in range(len(septal_side) - 1))
    assert all(lateral_side[i] >= lateral_side[i + 1] for i in range(len(lateral_side) - 1))


def test_lame_profile_for_view_phase_presets() -> None:
    assert lame_profile_for_view_phase("A4C", "ED") == LAME_A4C_ED
    assert lame_profile_for_view_phase("A4C", "ES") == LAME_A4C_ES
    assert lame_profile_for_view_phase("A2C", "ED") == LAME_A2C_ED
    assert lame_profile_for_view_phase("2C", "ES") == LAME_A2C_ES
    assert lame_profile_for_view_phase("UNKNOWN", "UNKNOWN") == LAME_A4C_ED


def test_es_preset_squatter_than_ed_on_same_landmarks_ratio() -> None:
    """Higher n in ES → lower mid-arc lift multiplier (squatter body)."""
    u_apex = 0.5
    ma_length = 100.0
    mid_ed = lame_lift_height(0.25, u_apex, ma_length, LAME_A4C_ED)
    mid_es = lame_lift_height(0.25, u_apex, ma_length, LAME_A4C_ES)
    assert mid_es < mid_ed
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_lv_lame_template.py -v`

Expected: FAIL — `ImportError` or `cannot import name 'lame_lift_height'`

- [x] **Step 3: Replace `lv_shape_template.py` with Lamé API**

Replace entire `src/echo_personal_tool/domain/services/lv_shape_template.py` with:

```python
"""Canonical LV endocardial Lamé open-arc warp profiles."""

from __future__ import annotations

from dataclasses import dataclass

_MIN_SEMI_AXIS_PX = 1e-6


@dataclass(frozen=True)
class LameWarpProfile:
    """Piecewise asymmetric Lamé height multipliers along MA chord."""

    n_sept: float
    n_lat: float
    alpha_sept: float = 1.0
    alpha_lat: float = 1.0
    lift_scale: float = 1.0


LAME_A4C_ED = LameWarpProfile(n_sept=3.0, n_lat=2.8, alpha_sept=1.0, alpha_lat=1.0, lift_scale=1.0)
LAME_A4C_ES = LameWarpProfile(n_sept=4.5, n_lat=4.0, alpha_sept=1.0, alpha_lat=0.95, lift_scale=0.98)
LAME_A2C_ED = LameWarpProfile(n_sept=2.9, n_lat=3.1, alpha_sept=1.0, alpha_lat=1.0, lift_scale=0.98)
LAME_A2C_ES = LameWarpProfile(n_sept=4.2, n_lat=4.5, alpha_sept=0.98, alpha_lat=1.0, lift_scale=0.96)


def lame_profile_for_view_phase(view: str, phase: str) -> LameWarpProfile:
    """Return Lamé preset for view × phase; unknown → A4C ED."""
    view_key = view.upper()
    phase_key = phase.upper()
    is_a2c = view_key in {"A2C", "2C"}
    is_es = phase_key == "ES"
    if is_a2c and is_es:
        return LAME_A2C_ES
    if is_a2c:
        return LAME_A2C_ED
    if is_es:
        return LAME_A4C_ES
    return LAME_A4C_ED


def lame_lift_height(
    u: float,
    u_apex: float,
    ma_length: float,
    profile: LameWarpProfile,
) -> float:
    """Return h(u)/H multiplier ∈ [0, lift_scale] along MA parameter u."""
    if ma_length <= 0.0:
        return 0.0
    x = (u - u_apex) * ma_length
    if x <= 0.0:
        semi_axis = max(u_apex * ma_length / profile.alpha_sept, _MIN_SEMI_AXIS_PX)
        exponent = profile.n_sept
    else:
        semi_axis = max((1.0 - u_apex) * ma_length / profile.alpha_lat, _MIN_SEMI_AXIS_PX)
        exponent = profile.n_lat
    ratio = min(1.0, abs(x / semi_axis) ** exponent)
    lift = (1.0 - ratio) ** (1.0 / exponent)
    return profile.lift_scale * max(0.0, lift)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_lv_lame_template.py -v`

Expected: PASS (5 tests)

- [x] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/lv_shape_template.py tests/unit/test_lv_lame_template.py
git commit -m "feat(lv): add Lamé lift height and view/phase presets"
```

---

### Task 2: `warp_lame_open_arc` — arc geometry tests + implementation

**Files:**
- Modify: `tests/unit/test_lv_lame_template.py`
- Modify: `src/echo_personal_tool/domain/services/lv_shape_template.py`

- [x] **Step 1: Add failing warp tests**

Append to `tests/unit/test_lv_lame_template.py`:

```python
from echo_personal_tool.domain.services.contour_geometry import point_line_distance
from echo_personal_tool.domain.services.lv_shape_template import warp_lame_open_arc


def test_warp_lame_open_arc_pins_ma_endpoints() -> None:
    septal = (10.0, 40.0)
    lateral = (50.0, 40.0)
    apex = (30.0, 10.0)
    warped = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    assert warped[0] == pytest.approx(septal, abs=1e-6)
    assert warped[-1] == pytest.approx(lateral, abs=1e-6)


def test_warp_lame_open_arc_apex_near_max_lift() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    warped = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    apex_height = point_line_distance(apex, septal, lateral)
    max_point = max(warped, key=lambda p: point_line_distance(p, septal, lateral))
    max_height = point_line_distance(max_point, septal, lateral)
    assert max_height == pytest.approx(apex_height * LAME_A4C_ED.lift_scale, rel=0.05, abs=2.0)


def test_warp_lame_a2c_differs_from_a4c() -> None:
    septal = (10.0, 40.0)
    lateral = (50.0, 40.0)
    apex = (30.0, 10.0)
    a4c = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    a2c = warp_lame_open_arc(septal, lateral, apex, view="A2C", phase="ED", num_points=81)
    mid_a4c = a4c[len(a4c) // 2]
    mid_a2c = a2c[len(a2c) // 2]
    assert mid_a4c != pytest.approx(mid_a2c, abs=0.5)


def test_warp_lame_arc_not_triangle() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    warped = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    quarter = warped[len(warped) // 4]
    triangle_x = 0.25 * apex[0]
    triangle_y = 0.25 * apex[1]
    assert quarter[0] > triangle_x + 10.0
    assert quarter[1] > triangle_y + 5.0
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_lv_lame_template.py::test_warp_lame_open_arc_pins_ma_endpoints -v`

Expected: FAIL — `cannot import name 'warp_lame_open_arc'`

- [x] **Step 3: Implement `warp_lame_open_arc`**

Append to `lv_shape_template.py`:

```python
import math


def _project_apex_param(
    apex: tuple[float, float],
    septal: tuple[float, float],
    lateral: tuple[float, float],
    ma_length: float,
) -> float:
    dx = lateral[0] - septal[0]
    dy = lateral[1] - septal[1]
    if ma_length <= 0.0:
        return 0.5
    t = ((apex[0] - septal[0]) * dx + (apex[1] - septal[1]) * dy) / (ma_length * ma_length)
    return max(0.0, min(1.0, t))


def warp_lame_open_arc(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    view: str = "A4C",
    phase: str = "ED",
    num_points: int = 81,
    profile: LameWarpProfile | None = None,
) -> list[tuple[float, float]]:
    """Sample open arc from septal to lateral via asymmetric Lamé lift along apex direction."""
    if num_points < 3:
        msg = "num_points must be at least 3"
        raise ValueError(msg)

    ma_dx = lateral[0] - septal[0]
    ma_dy = lateral[1] - septal[1]
    ma_length = math.hypot(ma_dx, ma_dy)
    if ma_length <= 0.0:
        msg = "mitral annulus length must be positive"
        raise ValueError(msg)

    warp_profile = profile or lame_profile_for_view_phase(view, phase)
    u_apex = _project_apex_param(apex, septal, lateral, ma_length)
    mid_x = 0.5 * (septal[0] + lateral[0])
    mid_y = 0.5 * (septal[1] + lateral[1])
    offset_x = apex[0] - mid_x
    offset_y = apex[1] - mid_y
    apex_height = math.hypot(offset_x, offset_y)
    if apex_height <= 0.0:
        msg = "apex must be off the mitral annulus line"
        raise ValueError(msg)

    dir_x = offset_x / apex_height
    dir_y = offset_y / apex_height
    warped: list[tuple[float, float]] = []
    for index in range(num_points):
        u = index / (num_points - 1)
        base_x = (1.0 - u) * septal[0] + u * lateral[0]
        base_y = (1.0 - u) * septal[1] + u * lateral[1]
        lift_mult = lame_lift_height(u, u_apex, ma_length, warp_profile)
        lift = lift_mult * apex_height
        warped.append((base_x + lift * dir_x, base_y + lift * dir_y))
    return warped
```

Move `import math` to top of file (merge with existing imports).

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_lv_lame_template.py -v`

Expected: PASS (9 tests)

- [x] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/lv_shape_template.py tests/unit/test_lv_lame_template.py
git commit -m "feat(lv): add warp_lame_open_arc geometry"
```

---

### Task 3: Wire Lamé into `mbs_lite_service`

**Files:**
- Modify: `src/echo_personal_tool/domain/services/mbs_lite_service.py`
- Modify: `tests/unit/test_mbs_lite_service.py`

- [x] **Step 1: Update failing imports in `test_mbs_lite_service.py`**

Replace imports at top of `tests/unit/test_mbs_lite_service.py`:

```python
from echo_personal_tool.domain.services.lv_shape_template import (
    LAME_A2C_ED,
    LAME_A4C_ED,
    lame_profile_for_view_phase,
    warp_lame_open_arc,
)
from echo_personal_tool.domain.services.mbs_lite_service import (
    build_lame_template_for_contour,
    fit_contour_from_landmarks,
    infer_apex_from_open_arc,
    refine_model_contour,
    refine_open_arc_contour,
)
```

Replace `test_dome_arc_is_not_septal_apex_lateral_triangle` body — use `warp_lame_open_arc` instead of `_warp_truncated_oval_arc`.

Replace `test_fit_contour_dome_includes_lateral_blend_before_apex` similarly.

Replace `test_a2c_warp_profile_differs_from_a4c`:

```python
def test_a2c_lame_profile_differs_from_a4c() -> None:
    a4c = lame_profile_for_view_phase("A4C", "ED")
    a2c = lame_profile_for_view_phase("A2C", "ED")
    assert a2c.n_lat != pytest.approx(a4c.n_lat)
```

Add new test:

```python
def test_infer_apex_from_open_arc_uses_max_ma_distance() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=(50.0, 60.0),
        phase="ED",
    )
    inferred = infer_apex_from_open_arc(contour.points, septal, lateral)
    assert inferred[1] > 30.0


def test_build_lame_template_matches_node_count() -> None:
    contour = fit_contour_from_landmarks(
        septal=(10.0, 40.0),
        lateral=(50.0, 40.0),
        apex=(30.0, 10.0),
        phase="ED",
        view="A4C",
    )
    template = build_lame_template_for_contour(contour)
    assert len(template) == len(contour.points)
```

- [x] **Step 2: Run tests — expect failures on new symbols**

Run: `uv run pytest tests/unit/test_mbs_lite_service.py -v`

Expected: FAIL — `cannot import name 'infer_apex_from_open_arc'`

- [x] **Step 3: Rewrite `mbs_lite_service.py` warp path**

In `mbs_lite_service.py`:

1. Replace imports:

```python
from echo_personal_tool.domain.services.lv_shape_template import (
    lame_profile_for_view_phase,
    warp_lame_open_arc,
)
```

Remove `ArcWarpProfile`, `warp_profile_for_view`.

2. In `fit_contour_from_landmarks`, pass `phase` and use Lamé for LV:

```python
    if chamber.upper() != "LV":
        msg = "fit_contour_from_landmarks supports LV only"
        raise ValueError(msg)

    warped = warp_lame_open_arc(
        septal,
        lateral,
        apex,
        view=view,
        phase=phase,
        num_points=_TEMPLATE_POINT_COUNT,
    )
```

3. Add helpers (after `fit_contour_from_landmarks`):

```python
def infer_apex_from_open_arc(
    points: Sequence[tuple[float, float]],
    septal: tuple[float, float],
    lateral: tuple[float, float],
) -> tuple[float, float]:
    """Infer apex landmark as interior point farthest from MA chord."""
    if len(points) < 3:
        return points[len(points) // 2]
    interior = points[1:-1]
    return max(interior, key=lambda point: point_line_distance(point, septal, lateral))


def build_lame_template_for_contour(contour: Contour) -> list[tuple[float, float]]:
    """Regenerate Lamé template resampled to contour node count."""
    if contour.mitral_annulus is None:
        return list(contour.points)
    septal, lateral = contour.mitral_annulus
    apex = infer_apex_from_open_arc(contour.points, septal, lateral)
    warped = warp_lame_open_arc(
        septal,
        lateral,
        apex,
        view=contour.view,
        phase=contour.phase,
        num_points=_TEMPLATE_POINT_COUNT,
    )
    return resample_open_arc(warped, num_nodes=len(contour.points))
```

Add `from collections.abc import Sequence` if missing.

4. Update `_refine_contour_points`:

```python
    template = template_points
    if template is None and contour.chamber.upper() == "LV":
        template = build_lame_template_for_contour(contour)
    if template is None:
        template = list(contour.points)
```

5. **Delete** `_warp_truncated_oval_arc`, `_lift_height`, and all `ArcWarpProfile` references.

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_mbs_lite_service.py tests/unit/test_lv_lame_template.py -v`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/mbs_lite_service.py tests/unit/test_mbs_lite_service.py
git commit -m "feat(lv): fit and refine LV contours via Lamé warp"
```

---

### Task 4: LV manual finish in `ViewerWidget`

**Files:**
- Create: `tests/unit/test_viewer_manual_lame.py`
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

- [x] **Step 1: Write failing viewer test**

Create `tests/unit/test_viewer_manual_lame.py`:

```python
"""Viewer tests for LV manual contour Lamé init."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.contour_geometry import DEFAULT_NODE_COUNT, point_line_distance
from echo_personal_tool.domain.services.mbs_lite_service import infer_apex_from_open_arc
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def test_finish_manual_lv_uses_lame_warp_not_triangle(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((120, 120), dtype=np.uint8))

    septal = (20.0, 90.0)
    lateral = (90.0, 90.0)
    apex = (55.0, 25.0)

    viewer._contour_mode_active = True
    viewer._contour_stage = "apex"
    viewer._active_contour_chamber = "LV"
    viewer._active_contour_phase = "ED"
    viewer._active_contour_view = "A4C"
    viewer._active_contour_source = "manual"
    viewer._active_mitral_annulus = (septal, lateral)

    finished = viewer._finish_manual_contour(apex=apex)
    assert finished is True

    contours = viewer.contours()
    assert len(contours) == 1
    contour = contours[0]
    assert contour.source == "manual"
    assert contour.chamber == "LV"
    assert len(contour.points) == DEFAULT_NODE_COUNT
    assert contour.points[0] == pytest.approx(septal, abs=1e-3)
    assert contour.points[-1] == pytest.approx(lateral, abs=1e-3)

    triangle_mid = (
        0.5 * (septal[0] + apex[0]),
        0.5 * (septal[1] + apex[1]),
    )
    interior = contour.points[DEFAULT_NODE_COUNT // 4]
    assert interior[1] > triangle_mid[1] + 5.0

    inferred = infer_apex_from_open_arc(contour.points, septal, lateral)
    apex_height = point_line_distance(apex, septal, lateral)
    assert point_line_distance(inferred, septal, lateral) == pytest.approx(
        apex_height, rel=0.1, abs=5.0
    )
```

- [x] **Step 2: Run test — expect fail (triangle geometry)**

Run: `uv run pytest tests/unit/test_viewer_manual_lame.py -v`

Expected: FAIL — interior point too low (old polyline resample)

- [x] **Step 3: Update `_finish_manual_contour`**

In `viewer_widget.py`, add import:

```python
from echo_personal_tool.domain.services.mbs_lite_service import fit_contour_from_landmarks
```

Replace `_finish_manual_contour` body (keep early return if no annulus):

```python
    def _finish_manual_contour(self, *, apex: tuple[float, float]) -> bool:
        if self._active_mitral_annulus is None:
            return False

        septal, lateral = self._active_mitral_annulus
        if self._active_contour_chamber.upper() == "LV":
            try:
                contour = fit_contour_from_landmarks(
                    septal=septal,
                    lateral=lateral,
                    apex=apex,
                    phase=self._active_contour_phase or "ED",
                    view=self._active_contour_view,
                    chamber="LV",
                )
            except ValueError:
                return False
            contour.source = "manual"
            contour.frame_index = self._contour_frame_index()
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

- [x] **Step 4: Run test**

Run: `uv run pytest tests/unit/test_viewer_manual_lame.py -v`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py tests/unit/test_viewer_manual_lame.py
git commit -m "feat(viewer): LV manual Simpson uses Lamé warp"
```

---

### Task 5: Full verification + changelog

**Files:**
- Modify: `CHANGELOG_SESSION.md`

- [x] **Step 1: Run full unit suite**

```bash
uv run pytest tests/unit -q
uv run ruff check src tests
```

Expected: all tests pass; no ruff errors

- [x] **Step 2: Add changelog entry**

Append to `CHANGELOG_SESSION.md`:

```markdown
## [2026-06-14] LV Lamé open-arc template D1
- **Тип:** feature
- **Файлы:** `lv_shape_template.py`, `mbs_lite_service.py`, `viewer_widget.py`, `test_lv_lame_template.py`, `test_mbs_lite_service.py`, `test_viewer_manual_lame.py`
- **Суть:** Синусоидальный warp заменён на piecewise Lamé по хорде МК с пресетами A4C/A2C ED/ES; manual и model LV Simpson используют одну формулу; R-refine получает Lamé template.
```

- [x] **Step 3: Commit**

```bash
git add CHANGELOG_SESSION.md
git commit -m "docs: changelog LV Lamé template D1"
```

---

## Manual smoke test (post-implementation)

1. Load A4C cine → Manual Simpson ED → 3 clicks (septal, lateral, apex).
2. Contour should be smooth Lamé arc (not sharp triangle); orange nodes.
3. Press **R** → refine should not collapse contour.
4. Repeat Model (MBS) path → green contour, same shape family.
5. A2C ED/ES → visibly different mid-arc vs A4C on same landmark geometry.

---

## Spec coverage (self-review)

| Spec requirement | Task |
|------------------|------|
| Option 1 Lamé over MA `u` | Task 1–2 |
| Four presets A4C/A2C ED/ES | Task 1 |
| LV manual + model only | Task 3–4 |
| `fit_contour_from_landmarks` API unchanged | Task 3 |
| Manual same warp | Task 4 |
| R-refine Lamé template | Task 3 `build_lame_template_for_contour` |
| Remove sinusoidal `ArcWarpProfile` | Task 1–3 |
| Endpoint h=0 at S/L | Task 1–2 tests |
| Non-LV unchanged | Task 4 (non-LV branch keeps polyline) |
| Deferred Option 2 / PDM | not in plan |

---

## Execution handoff

**Plan saved to `docs/superpowers/plans/2026-06-14-lv-lame-template.md`.**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks.

**2. Inline Execution** — implement all tasks in this session with checkpoints.

Which approach?
