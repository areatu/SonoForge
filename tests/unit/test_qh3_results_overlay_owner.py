"""QH-3 bridge removal: the results overlay pin state is read from its owner.

Before this slice ``ViewerWidget.is_results_overlay_pinned`` forwarded to the
controller, and the controller read the label's private ``_pinned``. The
characterisation below pins the behaviour that must survive the migration:

* the controller reports exactly what the label's public ``pinned`` seam says,
  and a plain QLabel (no pin state) is never pinned;
* the viewer exposes its owner and no longer forwards the pin query;
* the main window stores a study-level overlay position only while pinned.

``TestResultsOverlayPositionOwner`` below is slice 3 of the same issue: before
it, ``ViewerWidget`` kept a second copy of the position/cleared/suppressed
state (``_results_overlay_custom_position``, ``_results_overlay_cleared``,
``_results_overlay_position_just_restored``, ``_results_overlay_suppressed``)
*and* a second implementation of the label geometry math, next to the ones
already living on ``ResultsOverlayController`` since the QH-3 pilot slice —
the controller was constructed but only ever used for ``apply_style``. The
"erase, not just hide" bugfix had only been applied to the widget's copy.
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


# Every attribute that duplicated controller state before slice 3.
_DUPLICATED_STATE = (
    "_results_overlay_custom_position",
    "_results_overlay_cleared",
    "_results_overlay_position_just_restored",
    "_results_overlay_suppressed",
)


@pytest.mark.gui
class TestResultsOverlayPositionOwner:
    def test_the_viewer_holds_no_second_copy_of_the_overlay_state(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)

        for name in _DUPLICATED_STATE:
            assert not hasattr(w, name), f"{name} would be a second source of truth"

        owner = w.results_overlay_controller
        assert owner is w.results_overlay_controller, "the owner must be stable, not rebuilt per access"

    def test_custom_position_round_trips_through_the_owner(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)

        w.set_results_overlay_position(0.3, 0.7)

        assert w.results_overlay_controller.custom_position() is True
        assert w.results_overlay_custom_position() is True
        assert w.results_overlay_position() == (0.3, 0.7)
        assert w.results_overlay_controller.position() == (0.3, 0.7)

    def test_reset_to_default_clears_the_owners_flag(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)
        w.results_overlay_controller.mark_custom_position()

        w.reset_results_overlay_to_default()

        assert w.results_overlay_controller.custom_position() is False

    def test_clear_erases_the_label_not_only_hides_it(self, qtbot) -> None:
        """Regression for the fix the widget had and the controller forgot:

        a clear/reset must erase the stored text, or a later append resurrects
        the stale value instead of starting from a blank box (item 3 analysis,
        2026-11-06 plan).
        """
        w = ViewerWidget()
        qtbot.addWidget(w)
        w.set_results_overlay("<b>HR: 60</b>")

        w.contract.on_results_overlay_clear()

        assert w.contract.results_overlay_label.text() == ""
        assert w.contract.results_overlay_label.isHidden()

    def test_cleared_flag_blocks_new_text_until_an_explicit_reset(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)
        w.results_overlay_controller.mark_cleared()

        w.set_results_overlay("new value")
        assert w.results_overlay_text() == "", "cleared-until-next-non-empty is the owner's call"

        w.results_overlay_controller.reset_cleared()
        w.set_results_overlay("new value")
        assert w.results_overlay_text() == "new value"

    def test_suppressed_hides_and_blocks_new_text(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)
        w.set_results_overlay("before")

        w.set_results_overlay_suppressed(True)
        assert w.contract.results_overlay_label.isHidden()
        assert w.results_overlay_suppressed() is True

        w.set_results_overlay("during suppression")
        assert w.contract.results_overlay_label.isHidden()

        w.set_results_overlay_suppressed(False)
        w.set_results_overlay("after")
        assert w.results_overlay_text() == "after"

    def test_main_window_reset_hook_reaches_the_owner_without_a_private_write(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)
        w.results_overlay_controller.mark_cleared()

        w.reset_results_overlay_cleared()

        assert w.results_overlay_controller.is_cleared() is False
