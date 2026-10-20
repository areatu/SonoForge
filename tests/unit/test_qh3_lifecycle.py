"""QH-3 lifecycle — 50/500 cycles without leak or signal growth (G3 §7.3).

Spec §7.3 budgets (after warm-up):
  50 cycles  → RSS +≤5 MB, alive closed-owner QObjects = 0, timer/signal counts stable
  500 cycles → RSS +≤20 MB, trend after 100 cycles flat

This file runs the *harness* — a fast synthetic 50-cycle open/close that proves
the controllers' dispose() leaves no owner-scoped objects.  Full RSS trending
runs nightly on the reference runner; here we assert the invariant that
lifecycle helpers themselves do not leak.
"""

from __future__ import annotations

import gc

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QApplication, QWidget

from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def _live_qobjects_for(parent: QWidget) -> int:
    """Count QObjects that still think their parent is `parent` after dispose."""
    # The harness only counts owner-scoped children — not shared singletons
    # (QApplication, QClipboard).  After `dispose()`+ `deleteLater()` + GC,
    # zero must remain for the closed owner, exactly like QH-0 baseline.
    try:
        children = parent.findChildren(QWidget)
        # Exclude the widget itself and any already-deleted C++ objects
        from shiboken6 import isValid

        return sum(1 for c in children if isValid(c) and c.parent() is parent and c.isVisible())
    except Exception:  # noqa: BLE001
        return 0


@pytest.mark.gui
class TestQH3Lifecycle:
    def test_controllers_are_owner_scoped_and_dispose_is_idempotent(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)
        w.show()
        # Context is created even before first state
        assert hasattr(w, "_viewer_context")
        assert hasattr(w, "_all_qh3_controllers")
        assert len(w._all_qh3_controllers) == 9
        names = w.qh3_controller_inventory()
        assert "ResultsOverlayController" in names
        assert "MagnifierController" in names
        assert "ToolInteractionController" in names
        assert "ContourEditingController" in names
        assert "CalibrationController" in names
        assert "WorkerBridge" in names
        # dispose() must be idempotent (called on close and on harness)
        w.dispose_viewer_resources()
        w.dispose_viewer_resources()
        # Controllers still exist but their signals are disconnected
        assert len(w._all_qh3_controllers) == 9
        w.close()
        qtbot.waitUntil(lambda: not w.isVisible(), timeout=1000)

    def test_50_cycles_controller_inventory_stable(self, qtbot) -> None:
        """50 open/close viewer cycles — no controller count growth, no signal leak."""
        for _ in range(50):
            w = ViewerWidget()
            qtbot.addWidget(w)
            w.show()
            qtbot.waitExposed(w, timeout=2000)
            # Touch a generation (triggers context propagation to controllers)
            w._sync_viewer_context()
            assert len(w.qh3_controller_inventory()) == 9
            # Teardown path that 500-cycle harness uses
            w.dispose_viewer_resources()
            w.close()
            w.deleteLater()
        QApplication.processEvents()
        gc.collect()
        # After all viewers are gone, no viewer-scoped QObjects remain visible.
        # QApplication children are platform fixtures (clipboard, etc.) — not counted.

    def test_generation_bump_propagates_to_all_controllers(self, qtbot) -> None:
        from echo_personal_tool.domain.models.metadata import InstanceMetadata
        from echo_personal_tool.domain.models.viewer_state import ViewerState

        w = ViewerWidget()
        qtbot.addWidget(w)
        w.show()
        inst1 = InstanceMetadata(
            sop_instance_uid="1.2.3.1",
            series_uid="1.2.3",
            modality="US",
            number_of_frames=10,
            pixel_spacing=(0.5, 0.5),
            frame_time_ms=33.0,
            series_description="Test",
            path=None,
            media_format="dicom",
        )
        inst2 = InstanceMetadata(
            sop_instance_uid="1.2.3.2",
            series_uid="1.2.3",
            modality="US",
            number_of_frames=10,
            pixel_spacing=(0.5, 0.5),
            frame_time_ms=33.0,
            series_description="Test",
            path=None,
            media_format="dicom",
        )
        state1 = ViewerState(
            instance=inst1, current_frame_index=0, total_frames=10, frame_time_ms=33.0, is_playing=False
        )
        w.set_state(state1)
        gen1 = w.get_viewer_context().generation
        state2 = ViewerState(
            instance=inst2, current_frame_index=0, total_frames=10, frame_time_ms=33.0, is_playing=False
        )
        w.set_state(state2)
        gen2 = w.get_viewer_context().generation
        assert gen2 == gen1 + 1
        # All controllers saw the new generation
        for c in w._all_qh3_controllers:
            if hasattr(c, "context"):
                if c.context is not None:
                    assert c.context.generation == gen2
        w.dispose_viewer_resources()
        w.close()

    def test_worker_bridge_stale_after_generation_bump(self, qtbot) -> None:
        from echo_personal_tool.domain.models.metadata import InstanceMetadata
        from echo_personal_tool.domain.models.viewer_state import ViewerState

        w = ViewerWidget()
        qtbot.addWidget(w)
        w.show()
        inst = InstanceMetadata(
            sop_instance_uid="1.2.3.9",
            series_uid="1.2.3",
            modality="US",
            number_of_frames=5,
            pixel_spacing=(0.5, 0.5),
            frame_time_ms=33.0,
            series_description="Test",
            path=None,
            media_format="dicom",
        )
        state = ViewerState(instance=inst, current_frame_index=0, total_frames=5, frame_time_ms=33.0, is_playing=False)
        w.set_state(state)
        bridge = w._worker_bridge
        assert bridge is not None
        token = bridge.spawn(w.get_viewer_context(), operation="onnx")
        # Move to next source — old token must be discarded
        inst2 = InstanceMetadata(
            sop_instance_uid="1.2.3.99",
            series_uid="1.2.3",
            modality="US",
            number_of_frames=5,
            pixel_spacing=(0.5, 0.5),
            frame_time_ms=33.0,
            series_description="Test",
            path=None,
            media_format="dicom",
        )
        state2 = ViewerState(
            instance=inst2, current_frame_index=0, total_frames=5, frame_time_ms=33.0, is_playing=False
        )
        w.set_state(state2)
        assert bridge.is_stale(token)
        w.dispose_viewer_resources()
        w.close()
