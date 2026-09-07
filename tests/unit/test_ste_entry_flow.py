"""Regression tests for the STE entry flow (fix/ste_03 Phase 1).

Covers the viewer API that was lost in the arena merge (get_lv_contour with
phase/view filters, get_lv_epicardial_contour, ensure_lv_epicardial_contours)
and verifies that the STE toolbar handler reaches the controller with the
Simpson ED/ES frames instead of raising.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _lv_contour(phase: str, frame_index: int, *, points=None) -> object:
    from echo_personal_tool.domain.models.contour import Contour

    if points is None:
        pts = [(100.0, 60.0), (80.0, 90.0), (100.0, 130.0), (120.0, 90.0)]
    else:
        pts = points
    return Contour(
        phase=phase,
        view="A4C",
        chamber="LV",
        points=[(float(x), float(y)) for x, y in pts],
        source="manual",
        frame_index=frame_index,
    )


@pytest.fixture()
def viewer():
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    w = ViewerWidget()
    yield w
    w.close()


class TestViewerSteApi:
    def test_get_lv_contour_filters_by_phase_and_view(self, viewer) -> None:
        ed = _lv_contour("ED", 3)
        es = _lv_contour("ES", 7)
        viewer.apply_contours([ed, es])

        assert viewer.get_lv_contour(phase="ED", view="A4C").phase == "ED"
        assert viewer.get_lv_contour(phase="ES", view="A4C").phase == "ES"
        # Historical behaviour: no filters returns the first LV contour.
        assert viewer.get_lv_contour().phase == "ED"
        # Filtered miss returns None (no crash with unexpected kwargs).
        assert viewer.get_lv_contour(phase="ED", view="A2C") is None

    def test_ensure_lv_epicardial_contours_creates_for_missing_phases(self, viewer) -> None:
        ed = _lv_contour("ED", 3)
        es = _lv_contour("ES", 7)
        viewer.apply_contours([ed, es])

        created = viewer.ensure_lv_epicardial_contours(view="A4C")
        assert len(created) == 2
        epi_phases = {c.phase for c in created}
        assert epi_phases == {"ED", "ES"}
        for c in created:
            assert c.chamber == "LV_EPI"
            assert len(c.points) >= 4
            assert viewer.get_lv_epicardial_contour(phase=c.phase, view="A4C") is c

        # Second run is a no-op (idempotent, existing EPI not overwritten).
        assert viewer.ensure_lv_epicardial_contours(view="A4C") == []

    def test_epicardial_pen_is_distinct(self, viewer) -> None:
        ed = _lv_contour("ED", 3)
        epi = replace(ed, chamber="LV_EPI")
        assert viewer._contour_pen_for(epi) is not None


@pytest.fixture()
def mock_controller():
    from echo_personal_tool.domain.models.viewer_state import ViewerState

    snapshot = ViewerState(
        instance=None,
        current_frame_index=0,
        total_frames=0,
        frame_time_ms=None,
        is_playing=False,
        contours=(),
        linear_measurements=(),
        measurement_snapshot=None,
        decode_in_progress=False,
        manual_pixel_spacing=None,
        scroll_navigation=False,
    )
    c = MagicMock()
    c.state_manager = MagicMock()
    c.state_manager.snapshot = snapshot
    c.playback_config = MagicMock(scroll_debounce_ms=100)
    c.studies = []
    c.get_cached_frames.return_value = []
    c._frame_cache = MagicMock(_total_frames=20)
    c._current_study_uid = None
    c._measurement_session = {}
    return c


@pytest.fixture()
def main_window(mock_controller):
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.main_window import MainWindow

    prefs = UserPreferences(
        theme_mode="dark",
        ui_font_size=13,
        layout_state_json="",
        confirm_reset=False,
        auto_play=False,
        magnetic_snap_enabled=False,
        despeckle_enabled=False,
        length_display_unit="mm",
        pdf_font_size=11,
        results_overlay_custom_position=False,
        language="ru",
    )
    with (
        patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"),
        patch("echo_personal_tool.presentation.main_window.load_user_preferences", return_value=prefs),
        patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
        patch.object(mock_controller, "compute_overlay_snapshot", return_value=None),
    ):
        w = MainWindow(controller=mock_controller)
    yield w
    w.close()


class TestSpeckleLaunchFlow:
    def test_ste_handler_launches_with_simpson_ed_es_frames(self, main_window, monkeypatch) -> None:
        from PySide6.QtWidgets import QDialog

        ed = _lv_contour("ED", 3)
        es = _lv_contour("ES", 7)
        # Pre-create epicardial contours so the handler does not early-return
        # with "press STE again" and instead proceeds to the dialog.
        contours = [ed, es]
        for c in (ed, es):
            from echo_personal_tool.domain.services.myocardial_zone import expand_contour_to_zone

            pts = np.asarray(c.points, dtype=np.float64)
            epi = expand_contour_to_zone(pts, thickness_px=20.0)
            contours.append(
                replace(
                    c,
                    chamber="LV_EPI",
                    points=[(float(x), float(y)) for x, y in epi],
                    source="ste_auto",
                )
            )

        main_window._viewer._current_frame = np.zeros((200, 200), dtype=np.uint8)
        main_window._viewer.apply_contours(contours)

        captured = {}
        main_window._controller.run_speckle_tracking = MagicMock(
            side_effect=lambda *a, **kw: captured.update({"args": a, "kwargs": kw})
        )
        monkeypatch.setattr("echo_personal_tool.presentation.ui_animations.exec_animated", lambda *a, **k: QDialog.DialogCode.Accepted)

        # No exception: the handler previously crashed on the missing
        # get_lv_contour(phase=..., view=...) kwargs signature.
        main_window._on_speckle_tracking_requested()

        assert captured, "run_speckle_tracking was not called"
        kwargs = captured["kwargs"]
        assert kwargs.get("manual_ed") == 3
        assert kwargs.get("manual_es") == 7
        contour_arg = captured["args"][0]
        assert contour_arg.chamber == "LV"
        assert contour_arg.phase == "ED"
