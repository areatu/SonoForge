"""Main-view IMT overlay edits, refusal, freshness and read-only gating."""

from types import SimpleNamespace

import numpy as np
import pyqtgraph as pg
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore
from echo_personal_tool.domain.models.calibration import CalibrationContext
from echo_personal_tool.domain.models.imt import ImtRefusal
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.imt_editor import ImtEditor, show_imt_editor

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot, monkeypatch, tmp_path):
    window = QWidget()
    qtbot.addWidget(window)
    graphics = pg.GraphicsLayoutWidget(window)
    view = graphics.addViewBox(invertY=True)
    image = np.full((64, 96), 10.0)
    image[20:23] = 140
    image[23:28] = 40
    image[28:] = 220
    instance = InstanceMetadata(
        sop_instance_uid="sop",
        series_uid="series",
        path=tmp_path / "phantom.png",
        modality="US",
        number_of_frames=10,
        pixel_spacing=None,
        frame_time_ms=None,
        series_description="phantom",
    )
    state = ViewerState(
        instance=instance,
        current_frame_index=2,
        total_frames=10,
        frame_time_ms=None,
        is_playing=False,
        manual_calibration=CalibrationContext((0.1, 0.2), source="manual"),
    )
    store = StudyMeasurementSessionStore()

    class State(QObject):
        state_changed = Signal(object)

    manager = State(window)
    manager.snapshot = state
    window._controller = SimpleNamespace(
        state_manager=manager,
        resolve_study_uid=lambda _i: "1.2.3",
        frame_access=SimpleNamespace(frame=lambda *_args: image),
    )
    window._comparison = SimpleNamespace(tool_blocked=lambda _name: False)
    window._viewer = SimpleNamespace(overlay_view=view, get_viewer_context=lambda: SimpleNamespace(generation=1))
    monkeypatch.setattr(
        "echo_personal_tool.presentation.imt_editor.services_of", lambda _c: SimpleNamespace(measurement_store=store)
    )
    dialog = ImtEditor(window)
    qtbot.addWidget(dialog)
    dialog.fields["roi"].setText("0,0,96,64")
    dialog.fields["guides"].setText("20,20,28,28")
    dialog.fields["policy"].setText(".3,1.5,.75,.05")
    return dialog, store


def test_overlay_edit_save_load_requires_review(editor):
    dialog, store = editor
    dialog.propose()
    assert len(dialog.overlays) == 2
    dialog.confirm()
    assert dialog.review.draft.confirmed
    dialog.edit_started()
    assert not dialog.review.draft.confirmed
    dialog.edited()
    assert dialog.review.draft.revision == 1
    dialog.confirm()
    dialog.save()
    assert store.get("1.2.3").imt_measurements[0].confirmed
    dialog.load()
    with pytest.raises(ImtRefusal, match="review_required"):
        dialog.confirm()
    dialog.revalidate()
    dialog.confirm()
    dialog.save()
    assert store.get("1.2.3").imt_measurements[0].revision == 2
    assert len(store.get("1.2.3").imt_measurements) == 1
    dialog.clear_overlays()
    assert not dialog.overlays


def test_context_change_and_readonly_refuse(editor):
    dialog, store = editor
    dialog.propose()
    dialog.confirm()
    dialog.side.setCurrentText("L")
    dialog.check_context()
    assert not dialog.review.live and not dialog.overlays
    with pytest.raises(ImtRefusal):
        dialog.save()
    assert not store.get("1.2.3").imt_measurements
    dialog.host._comparison.tool_blocked = lambda _name: True
    with pytest.raises(ImtRefusal, match="readonly_pane"):
        dialog.propose()
    show_imt_editor(dialog.host)
    assert len(dialog.host.findChildren(ImtEditor)) == 1


def test_refused_drag_does_not_store_invalid_geometry(editor):
    dialog, store = editor
    dialog.propose()
    dialog.confirm()
    overlay = dialog.overlays[0]
    overlay.blockSignals(True)
    overlay.setPoints([(1, 40), (40, 40), (90, 40)])
    overlay.blockSignals(False)
    with pytest.raises(ImtRefusal):
        dialog.edited()
    assert not dialog.review.live and not dialog.review.draft.confirmed
    assert not store.get("1.2.3").imt_measurements


@pytest.mark.parametrize("change", ["frame", "calibration", "generation"])
def test_live_context_cannot_confirm_after_change(editor, change):
    from dataclasses import replace

    dialog, _store = editor
    dialog.propose()
    dialog.confirm()
    state = dialog.host._controller.state_manager.snapshot
    if change == "frame":
        dialog.host._controller.state_manager.snapshot = replace(state, current_frame_index=3)
    elif change == "calibration":
        dialog.host._controller.state_manager.snapshot = replace(
            state, manual_calibration=CalibrationContext((0.11, 0.2), source="manual", revision=1)
        )
    else:
        dialog.host._viewer.get_viewer_context = lambda: SimpleNamespace(generation=2)
    # Synchronous gates work before the polling timer gets its next turn.
    with pytest.raises(ImtRefusal):
        dialog.confirm()
    with pytest.raises(ImtRefusal):
        dialog.save()
    dialog.check_context()
    assert not dialog.review.live and not dialog.review.draft.confirmed


@pytest.mark.parametrize("change", ["frame", "calibration", "playback", "side", "roi"])
def test_observed_context_aba_revokes_review_before_timer(editor, change):
    from dataclasses import replace

    dialog, store = editor
    dialog.propose()
    dialog.confirm()
    manager = dialog.host._controller.state_manager
    original = manager.snapshot
    if change in ("frame", "calibration", "playback"):
        if change == "frame":
            manager.snapshot = replace(original, current_frame_index=3)
        elif change == "calibration":
            manager.snapshot = replace(
                original, manual_calibration=CalibrationContext((0.11, 0.2), source="manual", revision=1)
            )
        else:
            manager.snapshot = replace(original, is_playing=True)
        manager.state_changed.emit(manager.snapshot)
        manager.snapshot = original
        manager.state_changed.emit(original)
    elif change == "side":
        dialog.side.setCurrentText("L")
        dialog.side.setCurrentText("R")
    else:
        dialog.fields["roi"].setText("1,0,96,64")
        dialog.fields["roi"].setText("0,0,96,64")
    assert not dialog.review.live and not dialog.review.draft.confirmed and not dialog.overlays
    with pytest.raises(ImtRefusal, match="review_required"):
        dialog.confirm()
    with pytest.raises(ImtRefusal, match="review_required"):
        dialog.save()
    assert not store.get("1.2.3").imt_measurements


def test_load_revalidate_bad_pixels_preserves_stored_confirmed_record(editor):
    dialog, store = editor
    dialog.propose()
    dialog.confirm()
    dialog.save()
    saved = store.get("1.2.3").imt_measurements[0]
    dialog.load()
    dialog.host._controller.frame_access.frame = lambda *_: np.zeros((64, 96))
    with pytest.raises(ImtRefusal, match="flat_roi"):
        dialog.revalidate()
    assert not dialog.review.live and not dialog.review.draft.confirmed
    with pytest.raises(ImtRefusal, match="review_required"):
        dialog.save()
    assert store.get("1.2.3").imt_measurements == (saved,)


def test_real_state_manager_frame_and_calibration_events_invalidate_before_aba(editor):
    from echo_personal_tool.application.state_manager import StateManager

    dialog, store = editor
    # Use the real manager, and subscribe as the dialog does during construction.
    old = dialog.host._controller.state_manager.snapshot
    manager = StateManager()
    manager.set_instance(old.instance, old.total_frames, old.frame_time_ms)
    manager.set_manual_calibration(old.manual_calibration)
    manager.set_frame(old.current_frame_index)
    dialog.host._controller.state_manager = manager
    manager.state_changed.connect(dialog.context_changed)
    dialog.propose()
    dialog.confirm()
    manager.set_frame(3)
    manager.set_frame(2)
    assert not dialog.review.live and not dialog.review.draft.confirmed
    with pytest.raises(ImtRefusal, match="review_required"):
        dialog.save()
    dialog.revalidate()
    dialog.confirm()
    manager.set_manual_calibration(CalibrationContext((0.11, 0.2), source="manual", revision=1))
    manager.set_manual_calibration(old.manual_calibration)
    assert not dialog.review.live and not dialog.review.draft.confirmed
    assert not store.get("1.2.3").imt_measurements


def test_actual_overlay_edit_recomputes_and_keeps_persisted_acceptance_unchanged(editor):
    dialog, store = editor
    dialog.propose()
    dialog.confirm()
    dialog.save()
    saved = store.get("1.2.3").imt_measurements[0]
    overlay = dialog.overlays[1]
    points = [(float(p.x()), float(p.y()) + 0.5) for _, p in overlay.getLocalHandlePositions()]
    overlay.blockSignals(True)
    overlay.setPoints(points)
    overlay.blockSignals(False)
    dialog.edit_started()
    dialog.edited()
    draft = dialog.review.draft
    assert draft.revision == saved.revision + 1 and not draft.confirmed
    assert draft.media_adventitia == tuple(points) and draft.mean_mm > saved.mean_mm
    assert store.get("1.2.3").imt_measurements == (saved,)
    dialog.confirm()
    dialog.save()
    assert store.get("1.2.3").imt_measurements == (dialog.review.draft,)


def test_rectangle_selection_on_main_scene_proposes_without_numeric_input(editor, qtbot):
    from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    dialog, _store = editor
    view = dialog.host._viewer.overlay_view
    graphics = view.scene().views()[0]
    graphics.resize(640, 480)
    dialog.host.show()
    graphics.show()
    QCoreApplication.processEvents()
    view.setRange(xRange=(0, 96), yRange=(0, 64), padding=0)
    dialog.start_selection()
    for kind, point in (
        (QEvent.Type.GraphicsSceneMousePress, QPointF(4, 10)),
        (QEvent.Type.GraphicsSceneMouseMove, QPointF(90, 40)),
        (QEvent.Type.GraphicsSceneMouseRelease, QPointF(90, 40)),
    ):
        event = QGraphicsSceneMouseEvent(kind)
        event.setScenePos(view.mapViewToScene(point))
        event.setButton(Qt.MouseButton.LeftButton)
        event.setButtons(Qt.MouseButton.LeftButton)
        QCoreApplication.sendEvent(view.scene(), event)
    assert dialog.review is not None, dialog.status.text()
    assert dialog.review.live and not dialog.review.draft.confirmed
    assert dialog.review.draft.mean_mm == pytest.approx(0.8, abs=0.03)
    assert dialog.wall_roi is not None
    assert len(dialog.overlays) == 2
    assert not dialog.selection_armed
    assert get_theme_tokens()["state.ok"] in dialog.metrics["mean"].styleSheet()
    dialog.confirm()
    dialog.save()


def test_rectangle_resize_recomputes_and_frame_change_removes_selection(editor):
    from dataclasses import replace

    from PySide6.QtCore import QPointF

    dialog, store = editor
    dialog.start_selection()
    dialog.update_rectangle(QPointF(4, 10), QPointF(90, 40))
    dialog.rectangle_finished()
    dialog.confirm()
    dialog.save()
    saved = store.get("1.2.3").imt_measurements[0]
    roi = dialog.wall_roi
    dialog.rectangle_edit_started()
    roi.blockSignals(True)
    roi.setSize((80, 30))
    roi.blockSignals(False)
    dialog.rectangle_finished()
    assert dialog.review.live and not dialog.review.draft.confirmed
    assert dialog.review.draft.source.roi == (4, 10, 84, 40)
    assert store.get("1.2.3").imt_measurements == (saved,)
    manager = dialog.host._controller.state_manager
    manager.snapshot = replace(manager.snapshot, current_frame_index=3)
    manager.state_changed.emit(manager.snapshot)
    assert dialog.wall_roi is None and not dialog.overlays
    assert not dialog.review.live
    assert get_theme_tokens()["text.2"] in dialog.metrics["mean"].styleSheet()


@pytest.mark.parametrize(
    "value,color", [(0.9, "state.ok"), (0.91, "state.warn"), (1.49, "state.warn"), (1.5, "state.err")]
)
def test_reference_colors_and_minimum(editor, value, color):
    from dataclasses import replace

    dialog, _store = editor
    dialog.propose()
    dialog.review.draft = replace(dialog.review.draft, distances_mm=(value,), mean_mm=value, max_mm=value)
    dialog.summary()
    for label in dialog.metrics.values():
        assert f"{value:.3f}" in label.text()
        assert get_theme_tokens()[color] in label.styleSheet()


def test_close_cleans_selection_overlays_and_timer(editor):
    from PySide6.QtCore import QPointF, Qt

    dialog, _store = editor
    dialog.start_selection()
    dialog.update_rectangle(QPointF(4, 10), QPointF(90, 40))
    dialog.rectangle_finished()
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)  # qtbot owns deletion
    dialog.show()
    dialog.close()
    assert dialog.wall_roi is None and not dialog.overlays
    assert not dialog.timer.isActive()


def test_frame_change_while_drawing_cancels_selection(editor):
    from dataclasses import replace

    from PySide6.QtCore import QPointF

    dialog, _store = editor
    dialog.start_selection()
    dialog.update_rectangle(QPointF(4, 10), QPointF(90, 40))
    manager = dialog.host._controller.state_manager
    original = manager.snapshot
    manager.snapshot = replace(original, current_frame_index=3)
    manager.state_changed.emit(manager.snapshot)
    manager.snapshot = original
    manager.state_changed.emit(original)
    assert not dialog.selection_armed and dialog.wall_roi is None
    assert dialog.review is None
