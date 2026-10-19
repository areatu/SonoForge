"""Focus view of a single file (UI-6, spec §4.8) — the window and its widgets.

The pure decisions are covered by ``test_focus_mode.py``; here the mode is
driven through a real ``MainWindow``: the automatic entry after a single-file
load, the F toggle, the per-tab state (S-02), the layout the mode assembles and
the floating plates.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.focus_mode import FOCUS_CARD_WIDTH, FOCUS_CINE_WIDTH
from echo_personal_tool.presentation.focus_widgets import FOCUS_HEADER_HEIGHT_MIN
from echo_personal_tool.presentation.layout.presets import LayoutConfigV2
from echo_personal_tool.presentation.main_window import MainWindow


@pytest.fixture(autouse=True)
def _isolate_qsettings(isolated_qsettings):
    return isolated_qsettings


@pytest.fixture(autouse=True)
def _stub_load_failure_dialog(monkeypatch) -> None:
    """Synthetic publishes autoload a clip whose files do not exist."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))


def _make_window(qtbot, *, single_file_focus: bool = True) -> MainWindow:
    prefs = UserPreferences(layout_state_json="")
    window = MainWindow(controller=AppController(), user_preferences=prefs)
    window._layout_document = LayoutConfigV2(single_file_focus=single_file_focus)
    window._multiview_mode = False
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)
    return window


def _instance(uid: str) -> InstanceMetadata:
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


def _publish(window: MainWindow, *uids: str) -> None:
    instances = tuple(_instance(uid) for uid in uids)
    series = SeriesMetadata(
        series_uid="1.2.3.series",
        study_uid="1.2.3",
        modality="US",
        description="A4C",
        instances=instances,
    )
    study = StudyMetadata(study_uid="1.2.3", study_datetime=datetime(2026, 10, 1), series=(series,))
    window._controller.studies_loaded.emit([study])
    QApplication.processEvents()


# ── automatic entry ─────────────────────────────────────────────────


def test_a_single_file_opens_in_focus_by_itself(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")

    assert window.focus_mode_active()
    assert window._focus_layout_active
    assert window._focus_header is not None and window._focus_header.isVisible()
    assert window._focus_layer is not None and window._focus_layer.is_visible()


def test_the_switch_keeps_a_single_file_in_the_normal_view(qtbot) -> None:
    window = _make_window(qtbot, single_file_focus=False)
    _publish(window, "1.2.3.layout")

    assert not window.focus_mode_active()
    assert not window._focus_layout_active
    assert window._viewer.transport_visible()


def test_a_multi_clip_study_never_enters_focus(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.a", "1.2.3.b")

    assert not window.focus_mode_active()


# ── F, the toggle ───────────────────────────────────────────────────


def test_f_toggles_the_focus_view(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")
    assert window.focus_mode_active()

    window.toggle_focus_mode()
    QApplication.processEvents()
    assert not window.focus_mode_active()
    assert not window._viewer.results_overlay_suppressed()
    assert window._viewer.transport_visible()

    window.toggle_focus_mode()
    QApplication.processEvents()
    assert window.focus_mode_active()


def test_f_without_a_file_explains_itself(qtbot) -> None:
    window = _make_window(qtbot)
    window.toggle_focus_mode()
    assert not window.focus_mode_active()


def test_f_refuses_a_multi_clip_workspace(qtbot) -> None:
    window = _make_window(qtbot, single_file_focus=False)
    _publish(window, "1.2.3.a", "1.2.3.b")

    window.toggle_focus_mode()
    assert not window.focus_mode_active()


# ── the layout of the mode (F1) ─────────────────────────────────────


def test_focus_leaves_the_image_alone_and_hides_the_panels(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")

    assert window._content_layout.indexOf(window._tool_panel) < 0
    assert not window._tool_panel.isVisible()
    assert not window._gallery.isVisible()
    assert window._tool_rail.isVisible()
    assert window._viewer.isVisible()
    # The gallery is detached, not destroyed: leaving must bring it back.
    window.toggle_focus_mode()
    QApplication.processEvents()
    assert window._gallery.isVisible()
    assert window._tool_panel.isVisible()


def test_the_rail_hides_its_panels_toggle_in_focus(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")

    assert not window._tool_rail.panels_button_visible()
    window.toggle_focus_mode()
    QApplication.processEvents()
    assert window._tool_rail.panels_button_visible()


def test_the_header_strip_replaces_the_tool_row(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")

    header = window._focus_header
    assert header is not None
    assert header.isVisible()
    assert header.height() >= FOCUS_HEADER_HEIGHT_MIN
    if window._tool_row is not None:
        assert not window._tool_row.isVisible()


# ── the floating plates ─────────────────────────────────────────────


def test_the_plates_stay_inside_the_viewer_and_do_not_overlap(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")
    QApplication.processEvents()

    card, cine = window._focus_layer.geometry_snapshot()
    area = window._viewer.rect()
    assert card.right() <= area.width()
    assert cine.bottom() <= area.height()
    assert not card.intersects(cine)
    assert card.width() <= FOCUS_CARD_WIDTH
    assert cine.width() <= FOCUS_CINE_WIDTH


def test_the_card_shows_the_values_of_this_file(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")

    layer = window._focus_layer
    assert layer is not None
    # An empty clip explains itself instead of showing an empty box.
    assert layer.card.has_rows() == bool(layer.card.measurement_lines())


def test_the_plate_mirrors_the_transport_state(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")
    QApplication.processEvents()

    layer = window._focus_layer
    assert layer is not None
    state = window._controller.state_manager.snapshot
    assert layer.cine.total_frames() == state.total_frames
    assert layer.cine.frame() == state.current_frame_index
    # The floating plate is the transport in focus; the built-in strip steps aside.
    assert not window._viewer.transport_visible()


# ── state of the tab (S-02) ─────────────────────────────────────────


def test_the_mode_belongs_to_the_tab(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")
    assert window.focus_mode_active()

    tab = window._tabs.active
    assert tab is not None and tab.focus_mode and tab.focus_decided

    window.toggle_focus_mode()
    QApplication.processEvents()
    assert tab.focus_mode is False
    # The exit is a decision: a later surface sync must not drag the mode back.
    assert tab.focus_decided is True


def test_an_explicit_exit_survives_a_reload_of_the_same_tab(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")
    window.toggle_focus_mode()
    QApplication.processEvents()

    _publish(window, "1.2.3.layout")
    assert not window.focus_mode_active()


def test_a_new_source_gets_its_own_automatic_decision(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")
    window.toggle_focus_mode()
    QApplication.processEvents()

    # A different file is a new single-file candidate: focus opens again.
    _publish(window, "1.2.3.other")
    assert window.focus_mode_active()


def test_report_mode_is_not_touched_by_focus(qtbot) -> None:
    window = _make_window(qtbot)
    _publish(window, "1.2.3.layout")
    tab = window._tabs.active
    assert tab is not None
    window.toggle_focus_mode()
    QApplication.processEvents()
    assert tab.report_mode is False
