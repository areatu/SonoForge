"""QH-3 target boundary — what stays in ViewerWidget and what leaves.

Spec §7.1 / QH-3.1 §10.2–§10.3.  This file is the *agreed* decomposition contract
reviewed against the viewer characterization harness (QH-0).  It never ships
runtime logic; it documents the ownership that every subsequent slice must honour
so parallel slices do not recreate the «entire MainWindow as a dependency»
anti-pattern rejected in §7.1.

```
Qt events / signals / rendering
            │
      ViewerWidget (facade)
            │
  ViewerContext + explicit commands
            │
  tool / contour / calibration / overlay / magnifier controllers
            │
  application services / ports
       ├──→ domain calculations (pure)
       └──→ injected worker / I/O adapters
```

ViewerWidget stays a thin Qt facade:
  - owns QGraphicsView / QGraphicsLayoutWidget / sliders / timeline
  - translates Qt events (mouse/key/wheel/resize) into explicit commands
  - renders pixels supplied by the application (never decodes DICOM itself)
  - forwards signals that existed before QH-3 (contour_completed, calibration_completed, …)

Everything else moves into explicit controllers that receive narrow dependencies
(not the entire MainWindow/ViewerWidget).  ``ViewerContext`` is the only
per-frame identity they are allowed to read.

Gate criteria (QH-3):
  - behavior parity via the QH-0 characterization harness (no shortcut/tool/
    overlay regression)
  - S-02 isolation: switching pane/tab/source never leaks calibration, contour
    or worker result into the next context (generation check)
  - lifecycle 50/500 cycles without RSS/signal/timer growth (see
    tests/unit/test_qh3_lifecycle.py)
"""

from __future__ import annotations

# --- Ownership contract (immutable documentation) -------------------------

# Each row: (component, owns, must_not_own)
# Used by code review; the ratchet test in test_qh3_boundary.py asserts that
# no controller imports the viewer facade for I/O and that domain stays pure.
BOUNDARY: tuple[tuple[str, str, str], ...] = (
    (
        "ToolInteractionController",
        "active tool, draft gesture, commit/cancel, routing",
        "disk/network I/O, global identity via current MainWindow",
    ),
    (
        "ContourEditingController",
        "handles/selection/draft edit; commands accepted change/delete",
        "separate inconsistent copy of study measurements",
    ),
    (
        "CalibrationController",
        "validation/commit per-source calibration and invalidation notify",
        'calibration "for the last viewer"',
    ),
    (
        "ResultsOverlayController",
        "layout/visibility/position and render projection (pure formatting via domain)",
        "recalculation of clinical results from UI text",
    ),
    (
        "MagnifierController",
        "zoom/pan/crop and transient lens state",
        "source identity/persistence/calculator inputs",
    ),
    (
        "WorkerAdapters",
        "lifecycle of one task, result delivery token/generation",
        "mutating Qt/UI from background thread",
    ),
)

# Facade invariant: ViewerWidget must not become a service locator.
# Controllers receive narrow callables (e.g. geometry_provider, display_provider)
# rather than `viewer: ViewerWidget` when possible.  When a Qt parent is
# required (labels, lens), it is passed as QWidget, not ViewerWidget.

# Removal criterion for temporary bridges:
#   A bridge (e.g. `viewer._overlay_controller` forwarding method) may exist
#   only while at least one external caller still uses the old ViewerWidget API.
#   Once all callers/tests are migrated to the controller, the forwarding method
#   is deleted in the same PR that migrates the last caller — no parallel
#   authoritative copies may persist (§7.2 slice 5).

__all__ = ["BOUNDARY"]
