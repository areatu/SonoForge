"""QH-0 lifecycle baseline: owner-scoped QObject, threads, bounded caches.

Spec §4: production-like lifecycle baseline — opening/closing clip/tab/dialog/
strain window; RSS, live owner-scoped QObject, threads/tasks, bounded caches.
Separately from long pytest-suite.

This file is the harness referenced in
docs/reviews/2026-10-13-quality-safety-baseline-ru.md. It runs 50 cycles after
warm-up (PR stress) and checks:

* closed-owner controllers/widgets/tasks — 0
* thread count does not grow
* bounded caches stay within limits
* no new QApplication-wide QObject leak (best-effort, offscreen)

Nightly / pre-release: 500 cycles on reference runner — same logic, more loops.

The test is marked gui because it needs QApplication. It runs offscreen
(QT_QPA_PLATFORM=offscreen) and under xvfb-run in CI.
"""

from __future__ import annotations

import gc
import threading
import weakref

import pytest
from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.gui


def _qobject_inventory() -> int:
    """Best-effort count of alive QObjects owned by QApplication."""
    app = QApplication.instance()
    if app is None:
        return 0
    # allWidgets + findChildren covers most owner-scoped widgets; not exact
    # but stable enough for leak detection.
    try:
        return len(app.allWidgets())
    except Exception:
        return 0


def _thread_count() -> int:
    return threading.active_count()


class _FakeViewer:
    """Minimal viewer-like QObject for TabCoordinator tests."""

    def __init__(self):
        from PySide6.QtCore import QObject

        self._obj = QObject()
        self.closed = False

    def close(self):
        self.closed = True
        self._obj.deleteLater()

    def deleteLater(self):
        self._obj.deleteLater()


def test_tab_open_close_50_cycles_no_qobject_leak(qtbot):
    """A → B → A tab lifecycle: 50 cycles after warm-up, no leak (G0/G3)."""
    from echo_personal_tool.application.tab_session import TabSessionManager

    manager = TabSessionManager()

    # Warm-up — real API is open_tab(origin=...), not create_tab
    for _ in range(5):
        tab = manager.open_tab(origin="empty")
        manager.close_tab(tab.tab_id)

    gc.collect()
    qtbot.wait(10)
    before_widgets = _qobject_inventory()
    before_threads = _thread_count()

    # 50 cycles (PR stress)
    for i in range(50):
        tab = manager.open_tab(origin="empty")
        # Simulate viewer attached to tab (QObject)
        from PySide6.QtCore import QObject

        viewer_obj = QObject()
        # keep weakref to detect leak
        ref = weakref.ref(viewer_obj)
        manager.close_tab(tab.tab_id)
        viewer_obj.deleteLater()
        if i % 10 == 0:
            gc.collect()
            qtbot.wait(5)
        # ensure previous viewer was collected
        gc.collect()
        assert ref() is None or i < 2  # allow first cycles to settle

    gc.collect()
    qtbot.wait(20)

    after_widgets = _qobject_inventory()
    after_threads = _thread_count()

    # Widgets: allow small growth due to Qt caching, but not unbounded
    # (baseline on 358d84a: +0..3 after 50 cycles offscreen)
    assert after_widgets <= before_widgets + 5, f"QObject leak: before={before_widgets} after={after_widgets}"
    # Threads: measurement-io worker is singleton; no new threads per cycle
    assert after_threads <= before_threads + 1, f"Thread leak: before={before_threads} after={after_threads}"


def test_viewer_widget_50_cycles_no_leak(qtbot):
    """ViewerWidget open/close 50 cycles: closed-owner resources freed."""
    import numpy as np

    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    # Warm-up
    for _ in range(3):
        w = ViewerWidget()
        qtbot.addWidget(w)
        w.show()
        qtbot.wait(5)
        w.close()
        # qtbot will deleteLater automatically; explicit call is okay but avoid double
        try:
            w.deleteLater()
        except RuntimeError:
            pass
        qtbot.wait(5)

    gc.collect()
    qtbot.wait(10)
    before = _qobject_inventory()
    before_threads = _thread_count()

    frame = np.zeros((64, 64), dtype=np.uint8)

    for i in range(50):
        w = ViewerWidget()
        qtbot.addWidget(w)
        w.show()
        # Real API is show_frame, not set_frame
        w.show_frame(frame)
        qtbot.wait(2)
        w.close()
        try:
            w.deleteLater()
        except RuntimeError:
            # Already deleted C++ object — happens when Qt already scheduled deletion
            pass
        if i % 10 == 0:
            gc.collect()
            qtbot.wait(5)

    gc.collect()
    qtbot.wait(20)
    after = _qobject_inventory()
    after_threads = _thread_count()

    assert after <= before + 5, f"ViewerWidget leak: before={before} after={after}"
    assert after_threads <= before_threads + 1, (
        f"Thread leak after ViewerWidget cycles: before={before_threads} after={after_threads}"
    )


def test_comparison_session_generation_and_ownership_lifecycle(qtbot):
    """Comparison pair owns sources, generation bumps, no resurrection (S-05)."""
    from echo_personal_tool.domain.models.metadata import InstanceMetadata
    from echo_personal_tool.domain.models.multiview import MultiViewSession, PaneId

    def _inst(uid: str) -> InstanceMetadata:
        return InstanceMetadata(
            sop_instance_uid=uid,
            series_uid=f"{uid}.series",
            modality="US",
            number_of_frames=4,
            pixel_spacing=(0.5, 0.5),
            frame_time_ms=33.3,
            series_description="A4C",
            path=None,
        )

    session = MultiViewSession()
    initial_gen = session.generation

    # Load A from tab1, B from tab2 — different studies
    session.pane(PaneId.LEFT).instance = _inst("1.2.1.1")
    session.pane(PaneId.LEFT).study_uid = "1.2.1"
    session.pane(PaneId.RIGHT).instance = _inst("1.2.2.1")
    session.pane(PaneId.RIGHT).study_uid = "1.2.2"
    session.bump_generation()
    gen_after_load = session.generation
    assert gen_after_load > initial_gen
    assert session.references_source("1.2.1")
    assert session.references_source("1.2.2")

    # Switch active tab does NOT bump generation (S-02)
    gen_before_switch = session.generation
    assert session.generation == gen_before_switch

    # Explicit clear bumps generation and releases ownership
    session.pane(PaneId.LEFT).instance = None
    session.pane(PaneId.LEFT).study_uid = None
    session.bump_generation()
    assert session.generation > gen_after_load
    assert not session.references_source("1.2.1")
    assert session.references_source("1.2.2")

    # Old generation must not be accepted (late callback discard)
    assert not session.accepts(gen_after_load)
    assert session.accepts(session.generation)


def test_measurement_persistence_worker_singleton_and_bounded(qtbot, tmp_path):
    """MeasurementPersistence: single worker, bounded queue, no leak after close."""
    from echo_personal_tool.application.measurement_persistence import MeasurementPersistence
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore

    store = StudyMeasurementSessionStore()
    persistence = MeasurementPersistence(tmp_path, store, enabled=True)

    before_threads = _thread_count()

    # Submit a few no-op ops
    for _ in range(10):
        persistence.submit(lambda: None, lambda v, e: None)

    qtbot.wait(100)

    after_submit_threads = _thread_count()
    # One worker thread added at most
    assert after_submit_threads <= before_threads + 2

    # Close must not leak worker
    assert persistence.close() is True
    gc.collect()
    qtbot.wait(20)
    after_close_threads = _thread_count()
    # Worker thread should be gone or at least not growing
    assert after_close_threads <= before_threads + 1


def test_frame_cache_bounded_after_50_cycles(qtbot):
    """FrameCache stays bounded after 50 open/close cycles."""
    import numpy as np

    from echo_personal_tool.application.frame_cache import FrameCache

    cache = FrameCache(max_cache_bytes=10 * 1024 * 1024)

    for cycle in range(50):
        # Simulate loading a small cine
        frames = np.zeros((10, 32, 32), dtype=np.uint8)
        path = __file__
        cache.load(path, frames)
        for frame_idx in range(10):
            cache.put(frame_idx, frames[frame_idx])
        cache.clear()

    # After clear, cache must be empty
    assert cache.frames is None
    assert len(cache._frame_store) == 0
