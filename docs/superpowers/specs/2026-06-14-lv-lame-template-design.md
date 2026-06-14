# LV Lamé Open-Arc Template Design Spec (D1)

**Date:** 2026-06-14  
**Status:** Approved (D1 implementation)  
**Reference:** `LVContour.md` (superellipse / Lamé recipe №1)  
**Predecessors:** [2026-06-12-mbs-lite-design.md](./2026-06-12-mbs-lite-design.md), [2026-06-13-mbs-advanced-design.md](./2026-06-13-mbs-advanced-design.md)

## Goal

Replace the sinusoidal dome warp (`sin(π·phase)`) with an **asymmetric Lamé (superellipse) open-arc** so that the initial LV contour from three landmarks is physiologically closer to the endocardium. That makes **R-refine** (active contour) stable and yields contours visually closer to manual Simpson on real cines.

**Success criteria (primary gate = D):**

| ID | Criterion | How we judge |
|----|-----------|--------------|
| A | R-refine stable | No collapse, no runaway into speckle; MA endpoints pinned |
| B | Visual closeness | Manual A4C ED/ES on user cines — contour hugs endocardium before/after R |
| C | Volume sanity | Simpson EDV/ESV plausible; not a release gate |
| D | **Combined** | A + B required; C informational |

## Scope (locked)

| In scope | Out of scope |
|----------|--------------|
| **LV** open-arc Simpson: **Manual** and **Model (MBS)** | LA, RA, RV chamber contours |
| Views: **A4C**, **A2C** | Closed polygons, linear calipers |
| Phases: **ED**, **ES** | PDM / ASM (D1.2+), EFD init |
| One formula family, **four presets** (view × phase) | ED→ES propagation |
| Tunable constants in code (`lv_shape_template.py`) | Auto-refine on 3rd click (stays opt-in **R**) |

**Skeleton approved:** asymmetric Lamé open-arc over MA chord with apex from 3rd landmark; presets differ by `n_sept`, `n_lat`, width asymmetry, optional lift scale — not separate formulas per view.

## Current baseline

```text
base(t) = (1-t)·septal + t·lateral          # t ∈ [0,1] along MA
lift(t) = apex_lift_scale · sin(π·phase(t)) # phase shifts peak via peak_bias
point(t) = base(t) + lift(t) · (apex − MA_mid)
```

Problems: symmetric dome, peak forced near MA mid regardless of apex projection, poor ES “squashed” shape, weak lateral vs septal asymmetry → R-refine fights a bad template.

## Target architecture

```text
viewer_widget._finish_model_contour
  └─ mbs_lite_service.fit_contour_from_landmarks(chamber="LV")
       └─ lv_shape_template.warp_lame_open_arc(septal, lateral, apex, view, phase)
            └─ resample_open_arc → Contour(source="model")

viewer_widget._finish_manual_contour   # D1 change
  └─ same warp_lame_open_arc + resample → Contour(source="manual")

refine_open_arc_contour (R key)
  └─ active_contour_refine with template_points = Lamé warp at refine time
```

| Module | Change |
|--------|--------|
| `lv_shape_template.py` | `LameWarpProfile`, presets, `warp_lame_open_arc()`, `lame_lift_height()` |
| `mbs_lite_service.py` | Call Lamé warp instead of `_warp_truncated_oval_arc`; gate on `chamber == "LV"` |
| `viewer_widget.py` | Manual finish uses same warp (not 3-point polyline resample) |
| `active_contour_refine.py` | No formula change; benefits from better `template_points` |

`fit_contour_from_landmarks()` signature unchanged. Non-LV chambers keep existing behavior (no Lamé).

---

## Coordinate frame

Landmarks: **S** (septal MA), **L** (lateral MA), **A** (apex).

1. **MA chord:** `B(u) = (1−u)·S + u·L`, `u ∈ [0,1]`, `u=0` at septal, `u=1` at lateral.
2. **MA length:** `W = ‖L − S‖`.
3. **MA midpoint:** `M = ½(S + L)`.
4. **Apex offset vector:** `d = A − M` (same role as current `apex − MA_mid`).
5. **Apex height:** `H = ‖d‖` (apex distance from MA line in image plane; from landmarks, not a free parameter).
6. **Apex projection on chord:** scalar `uₐ ∈ [0,1]` — parameter of the closest point on the chord to A:

```text
uₐ = clamp( dot(A − S, L − S) / W² , 0, 1 )
```

7. **Signed MA coordinate** relative to apex projection (for asymmetry):

```text
x(u) = (u − uₐ) · W        # negative on septal side, positive on lateral side
```

All contour points lie on rays from the MA chord toward the apex:

```text
P(u) = B(u) + h(u) · d̂
```

where `d̂ = d / ‖d‖` and **`h(u)`** is the Lamé-derived lift along the apex direction (0 at MA, `H` at apex).

This preserves the existing “lift along apex vector” structure but replaces `sin` with Lamé height.

---

## Height function h(u) — two candidate constructions

Both use the Lamé / superellipse identity for the upper half of a superellipse in local coordinates (origin at apex projection on MA, x along chord, y along apex):

```text
|x/a|^n + |y/b|^n = 1   →   y(x) = b · (1 − min(1, |x/a|^n))^(1/n)
```

Here `b` maps to apex height `H` at `x = 0`; `a` maps to effective half-width of the arc on each side.

### Option 1 — Piecewise asymmetric Lamé over MA parameter (recommended)

**Idea:** One continuous open arc sampled uniformly in `u`. Asymmetry via **different** `(a, n)` on septal vs lateral side of `uₐ`.

```text
h(u) = H · f( x(u); a(u), n(u) )

where for x ≤ 0 (septal → apex):
  a(u) = a_sept · (W/2)     # or a_sept · W · (uₐ)  — see width modes below
  n(u) = n_sept
for x > 0 (apex → lateral):
  a(u) = a_lat · (W/2)
  n(u) = n_lat

f(x; a, n) = (1 − min(1, |x/a|^n))^(1/n)
```

At `u = uₐ`, `x = 0` → `f = 1` → `h = H` (apex).  
At `u = 0` and `u = 1`, `x = −uₐ·W` and `(1−uₐ)·W` → `h` small but **not necessarily 0** unless `|x/a| ≥ 1`. Clamp or scale `a` so endpoints stay on MA (`h(0)=h(1)=0`).

**Endpoint constraint (required):** choose effective half-widths so the superellipse meets the annulus:

```text
a_sept_eff = uₐ · W / α_sept
a_lat_eff  = (1 − uₐ) · W / α_lat
```

with `α_sept`, `α_lat` preset scale factors (default `1.0`). Then at septal, `|x| = uₐ·W = a_sept_eff` → `h = 0` if `α_sept = 1`. Same at lateral.

**Pros:** Same loop as current warp; uniform `u` sampling; smooth join at apex; ED/ES = change `n` and `α`; apex off-center handled naturally via `uₐ`.  
**Cons:** Not a literal “two quarter-ellipse” construction; width tied to chord geometry.

### Option 2 — Dual-half explicit arcs (septal segment + lateral segment)

**Idea:** Build two **separate** Lamé quarters in local 2D frames, then concatenate in image space.

1. **Septal half** (parameter `τ ∈ [0,1]`): arc from S to A.  
   Local frame: origin at S, x̂ toward A, ŷ along chord toward L (or toward `uₐ` point on MA).  
   Superellipse quarter with semi-axes tied to `‖S−A‖` and septal preset `(a_sept, n_sept)`.

2. **Lateral half** (parameter `τ ∈ [0,1]`): arc from A to L.  
   Local frame: origin at A, x̂ toward L, ŷ from A back toward MA.  
   Preset `(a_lat, n_lat)`.

3. Sample `N_sept` points on half 1 + `N_lat` points on half 2; concatenate (drop duplicate A).

**Pros:** Intuitive “different wall curvature” per side; matches verbal “dual-half” description.  
**Cons:** Two frames + join at A → risk of tangent kink if axes misaligned; non-uniform arc-length unless resampled; more code than Option 1; harder to keep MA endpoints exactly on S/L without extra projection step.

### Decision

**Implement Option 1 (piecewise asymmetric Lamé over MA parameter)** as `warp_lame_open_arc`.  

Option 2 remains documented for D1.1 tuning if Option 1 fails visual gate B on lateral wall in A2C ES. No dual-half code in D1 unless review rejects Option 1.

---

## Presets (one formula, four tuples)

Stored in `lv_shape_template.py` as `LameWarpProfile` + lookup `lame_profile_for(view, phase)`.

| Preset | view | phase | n_sept | n_lat | α_sept | α_lat | lift_scale | Notes |
|--------|------|-------|--------|-------|--------|-------|------------|-------|
| A4C_ED | A4C | ED | 3.0 | 2.8 | 1.0 | 1.0 | 1.0 | Rounded body, typical diastole |
| A4C_ES | A4C | ES | 4.5 | 4.0 | 1.0 | 0.95 | 0.98 | Higher n → squatter; slight lateral shrink |
| A2C_ED | A2C | ED | 2.9 | 3.1 | 1.0 | 1.0 | 0.98 | Slight lateral emphasis (vs old peak_bias) |
| A2C_ES | A2C | ES | 4.2 | 4.5 | 0.98 | 1.0 | 0.96 | ES squat + septal bias |

**Tuning policy:** constants are code literals in v1 (no UI). D1.1 may export session contours + overlay debug for fitting `n`, `α`. Values above are **starting points**, not clinically validated.

**Phase/view fallback:** unknown phase → ED preset; unknown view → A4C.

---

## Sampling pipeline

1. `warp_lame_open_arc(..., num_points=81)` — uniform `u` (same as v1 template density).
2. `resample_open_arc(..., num_nodes=DEFAULT_NODE_COUNT)` — equal arc-length 32 nodes for Simpson + editing.
3. MA endpoints forced: first point = S, last point = L (resample already pins endpoints on open arc).

Optional v1 guard: if any `h(u)` numerically &lt; 0, clamp to 0.

---

## Manual vs model

| source | 3-click workflow | Template |
|--------|------------------|----------|
| `model` | MA septal → MA lateral → apex (MBS) | Lamé warp |
| `manual` | Same MA → apex (Simpson panel) | **Same Lamé warp** (replaces polyline through 3 points) |

Rationale: one geometric prior for manual and model; R-refine and visual comparison share the same init; user apex click still sets `H` and `uₐ`.

**Editing after init:** node drag + RBF (existing) unchanged; `source` preserved.

---

## Interaction with R-refine

From [mbs-advanced-design](./2026-06-13-mbs-advanced-design.md):

- Refine is **opt-in** (**R**), not on 3rd click.
- `refine_open_arc` uses `template_points` to pull snake toward template (`k_int`).
- D1: regenerate template from stored `mitral_annulus` + apex inferred from contour (max projection along apex direction) **or** store apex landmark on contour in future; v1 infer apex = point with max distance from MA line among interior nodes.

Better template → lower `k_int` fighting → stable A.

---

## API (domain)

```python
@dataclass(frozen=True)
class LameWarpProfile:
    n_sept: float
    n_lat: float
    alpha_sept: float = 1.0
    alpha_lat: float = 1.0
    lift_scale: float = 1.0

def lame_profile_for_view_phase(view: str, phase: str) -> LameWarpProfile

def lame_lift_height(
    u: float,
    u_apex: float,
    ma_length: float,
    profile: LameWarpProfile,
) -> float  # ∈ [0, 1] multiplier for H

def warp_lame_open_arc(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    view: str = "A4C",
    phase: str = "ED",
    num_points: int = 81,
    profile: LameWarpProfile | None = None,
) -> list[tuple[float, float]]
```

`ArcWarpProfile` / sinusoidal helpers: remove after Lamé lands (or keep private for one release behind flag — prefer delete + update tests).

---

## Testing

| Test | File | Assert |
|------|------|--------|
| Endpoints on MA | `test_mbs_lite_service.py` | first/last = septal/lateral |
| Apex near max lift | same | interior max distance from MA ≈ apex distance |
| Monotonic lift septal→apex, apex→lateral | same | h(u) unimodal |
| ES vs ED shape | same | ES mean curvature / n higher → smaller mean h mid-arc |
| A2C vs A4C differ | same | profiles produce non-identical arcs for same landmarks |
| Manual path | `test_simpson_live_feedback.py` or viewer unit | manual finish uses warp (mock fit) |
| Regression distance | new `test_lv_lame_template.py` | fixed landmarks → golden polyline hash or max deviation bound |
| R-refine smoke | `test_mbs_lite_service.py` | refine does not collapse nodes |

```bash
uv run pytest tests/unit/test_mbs_lite_service.py tests/unit/test_lv_lame_template.py -v
uv run pytest tests/unit -q
```

---

## Deferred (not D1)

| Item | Target |
|------|--------|
| PDM / ASM from session store | D1.2 |
| EFD contour init | — |
| Contour export + preset tuning UI | D1.1 |
| Dual-half Option 2 | D1.1 fallback only |
| LA / RA / RV templates | separate specs |

---

## Self-review checklist

| Check | Status |
|-------|--------|
| Scope: LV manual + model only | ✓ |
| One formula, four presets | ✓ |
| h(u) fully specified (Option 1 + Option 2 compared) | ✓ |
| Endpoint h=0 at S/L via α scaling | ✓ |
| No placeholder “TBD” for core math | ✓ |
| API names and file map | ✓ |
| Success criteria aligned with user (D) | ✓ |
| Conflicts with mbs-advanced (R opt-in) | none |
| Manual workflow change explicit | ✓ |

---

## Approved decisions (2026-06-14)

| Topic | Decision |
|-------|----------|
| D1 formula | **Option 1** — piecewise asymmetric Lamé over MA `u` |
| Manual init | **Same Lamé warp** as model (not 3-point polyline) |
| Presets | Starting table in spec; tune in code after cine pass |
| Option 2 (dual-half) | D1.1 **only if** gate B fails on named cases (e.g. A2C ES lateral); not default migration |

## Option 1 → Option 2: parameter transfer

| Parameter | Transfers to Option 2? | Notes |
|-----------|------------------------|-------|
| `n_sept`, `n_lat` | **Yes (qualitative)** | Wall “sharpness” semantics align; numeric values often reusable as starting points |
| ED vs ES delta (higher `n` in ES) | **Yes** | Clinical tuning insight, not wasted |
| A4C vs A2C asymmetry direction | **Yes** | e.g. “lateral tighter in ES” maps to both schemes |
| `alpha_sept`, `alpha_lat` | **Partial** | Option 1 scales chord half-width; Option 2 ties to segment axes — re-map, don’t copy blindly |
| `lift_scale` | **No direct** | Option 2 expresses similar effect via per-half axis ratios |
| Golden polyline hashes / regression fixtures | **No** | Recompute if formula switches |

**Strategy:** D1 tuning time is **not wasted** — you learn preset table and failure modes. Only exact `α` / lift numbers may need re-fit for Option 2.

**End-state recommendation:** Option 1 is the **target default** for 3-landmark LV init. Option 2 is an optional escape hatch for localized tangent/asymmetry gaps; PDM (D1.2) is the long-term ceiling if data allows.

---

## Next step

Implementation plan via `writing-plans` skill → `docs/superpowers/plans/2026-06-14-lv-lame-template.md`.
