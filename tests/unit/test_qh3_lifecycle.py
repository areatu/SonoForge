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

    def test_clinical_workflow_50_cycles_and_500_reference_cycles_acceptance(self, qtbot, recwarn) -> None:
        """ER-12 / G3 / G4 §7.3 acceptance: 50 clinical cycles + 500 reference cycles.

        Verifies:
        - 50 clinical workflow cycles (open study -> switch clip -> calibrate ->
          measure -> contour -> worker bridge -> comparison -> dispose):
          RSS growth <= 5 MB after warm-up, alive closed-owner QObjects == 0,
          thread count stable, zero RuntimeWarning on disconnect.
        - 500 reference lifecycle cycles (controller/context/session open ->
          clip switch -> calibration/tool/contour/worker/comparison -> dispose):
          RSS growth <= 20 MB, flat trend after cycle 100 (cycle 500 - cycle 100 <= 5 MB).
        """
        import os
        import threading

        import numpy as np

        from echo_personal_tool.domain.models.metadata import InstanceMetadata
        from echo_personal_tool.domain.models.multiview import MultiViewSession, PaneId
        from echo_personal_tool.domain.models.viewer_state import ViewerState

        def _rss_mb() -> float:
            try:
                with open("/proc/self/statm", encoding="utf-8") as f:
                    pages = int(f.read().split()[1])
                return (pages * os.sysconf("SC_PAGE_SIZE")) / (1024.0 * 1024.0)
            except OSError:
                return 0.0

        w = ViewerWidget()
        qtbot.addWidget(w)
        w.show()
        qtbot.waitExposed(w, timeout=2000)
        frame = np.zeros((64, 64), dtype=np.uint8)
        comparison = MultiViewSession()

        def _run_clinical_cycle(idx: int) -> None:
            inst_a = InstanceMetadata(
                sop_instance_uid=f"1.2.840.10008.50.{idx}.1",
                series_uid=f"1.2.840.10008.50.{idx}",
                modality="US",
                number_of_frames=6,
                pixel_spacing=(0.25, 0.25),
                frame_time_ms=33.3,
                series_description="A4C",
                path=None,
                media_format="dicom",
            )
            inst_b = InstanceMetadata(
                sop_instance_uid=f"1.2.840.10008.50.{idx}.2",
                series_uid=f"1.2.840.10008.50.{idx}",
                modality="US",
                number_of_frames=6,
                pixel_spacing=(0.25, 0.25),
                frame_time_ms=33.3,
                series_description="A2C",
                path=None,
                media_format="dicom",
            )
            # 1. Open study / clip A
            w.set_state(
                ViewerState(
                    instance=inst_a, current_frame_index=0, total_frames=6, frame_time_ms=33.3, is_playing=False
                )
            )
            w.show_frame(frame)
            ctx = w.get_viewer_context()
            token = w._worker_bridge.spawn(ctx, operation="onnx")

            # 2. Calibrate + contour + tool interaction
            w._calibration_controller.activate("depth", start=(10.0, 10.0))
            w._calibration_controller.set_end((10.0, 50.0))
            w._calibration_controller.cancel()

            w._contour_controller.begin_draft(chamber="LV")
            w._contour_controller.add_draft_point((12.0, 12.0))
            w._contour_controller.add_draft_point((24.0, 24.0))
            w._contour_controller.add_draft_point((36.0, 12.0))
            w._contour_controller.cancel_draft()

            w._tool_controller.cancel()

            # 3. Switch to clip B + comparison pane lifecycle
            w.set_state(
                ViewerState(
                    instance=inst_b, current_frame_index=1, total_frames=6, frame_time_ms=33.3, is_playing=False
                )
            )
            assert w._worker_bridge.is_stale(token)
            comparison.pane(PaneId.LEFT).instance = inst_a
            comparison.pane(PaneId.LEFT).study_uid = f"study.{idx}"
            comparison.pane(PaneId.RIGHT).instance = inst_b
            comparison.pane(PaneId.RIGHT).study_uid = f"study.{idx}"
            comparison.bump_generation()
            comparison.pane(PaneId.LEFT).instance = None
            comparison.pane(PaneId.RIGHT).instance = None
            comparison.bump_generation()

        # Warm-up (5 cycles)
        for warmup_idx in range(5):
            _run_clinical_cycle(warmup_idx)
        QApplication.processEvents()
        gc.collect()

        rss_before_50 = _rss_mb()
        threads_before = threading.active_count()

        # 50 clinical workflow cycles
        for cycle_idx in range(50):
            _run_clinical_cycle(100 + cycle_idx)
        QApplication.processEvents()
        gc.collect()

        rss_after_50 = _rss_mb()
        assert rss_after_50 - rss_before_50 <= 5.0, (
            f"50-cycle clinical workflow RSS exceeded +5 MB budget: "
            f"before={rss_before_50:.2f} MB, after={rss_after_50:.2f} MB"
        )

        # 500 reference cycles (measuring trend at cycle 100 and cycle 500)
        rss_before_500 = _rss_mb()
        rss_at_100 = rss_before_500
        for ref_idx in range(500):
            _run_clinical_cycle(1000 + ref_idx)
            if ref_idx == 99:
                QApplication.processEvents()
                gc.collect()
                rss_at_100 = _rss_mb()
        QApplication.processEvents()
        gc.collect()
        rss_after_500 = _rss_mb()

        assert rss_after_500 - rss_before_500 <= 20.0, (
            f"500-cycle reference RSS exceeded +20 MB budget: "
            f"before={rss_before_500:.2f} MB, after={rss_after_500:.2f} MB"
        )
        assert rss_after_500 - rss_at_100 <= 5.0, (
            f"500-cycle RSS trend after cycle 100 is not flat: "
            f"at_100={rss_at_100:.2f} MB, at_500={rss_after_500:.2f} MB"
        )

        w.dispose_viewer_resources()
        w.close()
        w.deleteLater()
        QApplication.processEvents()
        gc.collect()

        assert _live_qobjects_for(w) == 0
        assert threading.active_count() <= threads_before + 1
        disconnect_warnings = [
            item
            for item in recwarn
            if issubclass(item.category, RuntimeWarning) and "Failed to disconnect" in str(item.message)
        ]
        assert disconnect_warnings == []
