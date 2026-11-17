"""Main-view IMT overlay edits, refusal, freshness and read-only gating."""

from types import SimpleNamespace

import numpy as np
import pyqtgraph as pg
import pytest
from PySide6.QtWidgets import QWidget

from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore
from echo_personal_tool.domain.models.calibration import CalibrationContext
from echo_personal_tool.domain.models.imt import ImtRefusal
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
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
    window._controller = SimpleNamespace(
        state_manager=SimpleNamespace(snapshot=state),
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
