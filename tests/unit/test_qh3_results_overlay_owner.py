"""QH-3 bridge removal: the results overlay pin state is read from its owner.

Before this slice ``ViewerWidget.is_results_overlay_pinned`` forwarded to the
controller, and the controller read the label's private ``_pinned``. The
characterisation below pins the behaviour that must survive the migration:

* the controller reports exactly what the label's public ``pinned`` seam says,
  and a plain QLabel (no pin state) is never pinned;
* the viewer exposes its owner and no longer forwards the pin query;
* the main window stores a study-level overlay position only while pinned.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QLabel, QWidget

from echo_personal_tool.presentation.main_window import MainWindow
from echo_personal_tool.presentation.viewer.overlay_controller import ResultsOverlayController
from echo_personal_tool.presentation.viewer_widget import ResultsOverlayLabel, ViewerWidget


@pytest.mark.gui
class TestResultsOverlayPinOwner:
    def test_controller_reports_the_label_public_pin_state(self, qtbot) -> None:
        host = QWidget()
        qtbot.addWidget(host)
        label = ResultsOverlayLabel(host)
        controller = ResultsOverlayController(label, lambda: None)

        assert controller.is_pinned() is False
        label.pinned = True
        assert controller.is_pinned() is True
        label.pinned = False
        assert controller.is_pinned() is False

    def test_plain_label_without_pin_state_is_not_pinned(self, qtbot) -> None:
        host = QWidget()
        qtbot.addWidget(host)
        controller = ResultsOverlayController(QLabel(host), lambda: None)

        assert controller.is_pinned() is False

    def test_viewer_exposes_the_owner_and_no_forwarding_bridge(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)

        assert not hasattr(ViewerWidget, "is_results_overlay_pinned")
        owner = w.results_overlay_controller
        assert isinstance(owner, ResultsOverlayController)
        assert owner.is_pinned() is False
        w.contract.results_overlay_label.pinned = True
        assert owner.is_pinned() is True

    def test_main_window_keeps_study_position_only_while_pinned(self) -> None:
        """Characterises MainWindow._on_results_overlay_position_changed without a window."""
        state = {"pinned": False}
        viewer = SimpleNamespace(results_overlay_controller=SimpleNamespace(is_pinned=lambda: state["pinned"]))
        controller = SimpleNamespace(
            state_manager=SimpleNamespace(snapshot=SimpleNamespace(instance=None)),
            resolve_study_uid=lambda instance: "study-1",
        )
        fake_window = SimpleNamespace(
            _viewer=viewer,
            _controller=controller,
            _last_overlay_position=None,
            _instance_overlay_positions={},
            _study_overlay_positions={},
        )

        MainWindow._on_results_overlay_position_changed(fake_window, 0.25, 0.5)
        assert fake_window._last_overlay_position == (0.25, 0.5)
        assert fake_window._study_overlay_positions == {}

        state["pinned"] = True
        MainWindow._on_results_overlay_position_changed(fake_window, 0.75, 0.125)
        assert fake_window._study_overlay_positions == {"study-1": (0.75, 0.125)}
