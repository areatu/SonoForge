"""Simpson Manual/MBS live overlay and panel feedback tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.presentation.main_window import MainWindow


def _sample_instance(*, pixel_spacing: tuple[float, float] | None) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=10,
        pixel_spacing=pixel_spacing,
        frame_time_ms=33.3,
        series_description="Test",
        path=Path("/tmp/test.dcm"),
    )


def _complete_manual_ed(window: MainWindow) -> None:
    window._on_manual_simpson_requested("A4C", "ED")
    window._viewer.handle_contour_click((10.0, 40.0))
    window._viewer.handle_contour_click((50.0, 40.0))
    window._viewer.handle_contour_click((30.0, 10.0))


def test_manual_ed_shows_panel_and_overlay_without_pixel_spacing(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        _sample_instance(pixel_spacing=None),
        total_frames=10,
        frame_time_ms=33.3,
    )
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

    _complete_manual_ed(window)

    panel_text = window._viewer.results_overlay_text()
    overlay = "\n".join(window._viewer._frame_overlay_lines)
    assert "КДО ЛЖ 4C" in panel_text
    assert "px³" in panel_text
    assert "Длина:" in overlay
    assert "px" in overlay


def test_mbs_ed_updates_after_node_drag(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        _sample_instance(pixel_spacing=(0.5, 0.5)),
        total_frames=10,
        frame_time_ms=33.3,
    )
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

    window._viewer.start_model_contour(phase="ED", view="A4C")
    window._viewer.handle_contour_click((10.0, 40.0))
    window._viewer.handle_contour_click((50.0, 40.0))
    window._viewer.handle_contour_click((30.0, 10.0))

    before = window._viewer.results_overlay_text()
    mid = 16
    mx, my = window._viewer.contours()[0].points[mid]
    # Существенное смещение apex-узла: малый drag (~31,10)→(32,8) не меняет округление 2.7 mL.
    window._viewer._drag_contour_point(0, mid, mx, my)
    window._viewer._drag_contour_point(0, mid, 20.0, 3.0)
    window._viewer._finalize_contour_point_drag(0, mid, 20.0, 3.0)
    after = window._viewer.results_overlay_text()
    overlay = "\n".join(window._viewer._frame_overlay_lines)

    assert "КДО ЛЖ 4C" in before
    assert after != before
    assert "mm" in overlay
    assert "mL" in overlay


def test_overlay_restored_after_frame_change(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        _sample_instance(pixel_spacing=(0.5, 0.5)),
        total_frames=10,
        frame_time_ms=33.3,
    )
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

    _complete_manual_ed(window)
    assert window._viewer._frame_overlay_lines

    controller.state_manager.set_frame(1)
    assert not window._viewer._frame_overlay_lines

    controller.state_manager.set_frame(0)
    overlay = "\n".join(window._viewer._frame_overlay_lines)
    assert "A4C ED" in overlay
    assert "Длина:" in overlay


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
