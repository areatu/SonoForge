"""Multiview widget tests: pane header/markers, transport bar and marker strip."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.domain.models.multiview import EventMarker, PaneId, PlaybackMode
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation import multiview_pane
from echo_personal_tool.presentation.multiview_marker_strip import MarkerStrip, marker_color
from echo_personal_tool.presentation.multiview_pane import VIEW_LABELS, MultiViewPaneWidget
from echo_personal_tool.presentation.multiview_transport import MultiViewTransportBar


@pytest.fixture()
def pane(qtbot):
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    viewer = ViewerWidget()
    widget = MultiViewPaneWidget(PaneId.LEFT, viewer)
    qtbot.addWidget(widget)
    widget.resize(900, 500)
    widget.show()
    qtbot.waitExposed(widget)
    yield widget


class TestPaneHeader:
    def test_pane_letter_and_object_name(self, pane) -> None:
        assert pane.objectName() == "multiviewPane_left"
        assert pane._letter_label.text() == "A"

    def test_right_pane_uses_the_letter_b(self, qtbot) -> None:
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        widget = MultiViewPaneWidget(PaneId.RIGHT, ViewerWidget())
        qtbot.addWidget(widget)
        assert widget._letter_label.text() == "B"
        assert widget.objectName() == "multiviewPane_right"

    def test_empty_pane_shows_the_placeholder(self, pane) -> None:
        pane.set_header(file_name="—", frame_text="—", has_clip=False, error=None)
        assert pane._placeholder.isVisible()
        assert pane._placeholder.text() == tr("multiview.placeholder.select_second")

    def test_placeholder_is_a_child_of_the_pane(self, pane) -> None:
        # A parentless placeholder would become a stray top-level window
        # ("SonoForge <2>") at startup with Multiview restored.
        assert pane.isAncestorOf(pane._placeholder)
        assert pane._placeholder.window() is pane.window()

    def test_loaded_pane_hides_the_placeholder(self, pane) -> None:
        pane.set_header(file_name="a4c.dcm", frame_text="3/30", has_clip=True, error=None)
        assert not pane._placeholder.isVisible()
        assert pane._file_label.text() == "a4c.dcm"
        assert pane._frame_label.text() == "3/30"

    def test_load_error_replaces_the_placeholder_text(self, pane) -> None:
        pane.set_header(file_name="a4c.dcm", frame_text="—", has_clip=False, error="Cannot read file")
        assert pane._placeholder.isVisible()
        assert pane._placeholder.text() == "Cannot read file"
        assert pane._file_label.toolTip() == "Cannot read file"

    def test_active_state_drives_the_badge_and_the_style_property(self, pane) -> None:
        pane.set_active(True)
        assert pane.is_active() is True
        assert pane._active_label.isVisible()
        assert pane.property("active") is True
        pane.set_active(False)
        assert pane._active_label.isHidden()
        assert pane.property("active") is False


class TestPaneSignals:
    def test_clicking_the_image_activates_the_pane(self, pane, qtbot) -> None:
        seen: list[PaneId] = []
        pane.activated.connect(seen.append)
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(4, 4),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        from PySide6.QtWidgets import QApplication

        QApplication.sendEvent(pane.viewer, event)
        assert seen == [PaneId.LEFT]

    def test_clicking_the_header_activates_the_pane(self, pane) -> None:
        seen: list[PaneId] = []
        pane.activated.connect(seen.append)
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(4, 4),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(pane._header, event)
        assert seen == [PaneId.LEFT]

    def test_header_buttons_keep_their_own_meaning(self, pane, monkeypatch) -> None:
        """A click on a header button must not activate the pane (spec 10.1)."""
        menus: list[_FakeMenu] = []
        monkeypatch.setattr(multiview_pane, "QMenu", _FakeMenu.factory(menus))
        seen: list[PaneId] = []
        pane.activated.connect(seen.append)
        pane._view_button.click()
        pane._menu_button.click()
        assert seen == []
        # the view menu offers "none" plus every known projection
        assert len(menus[0].actions) == 1 + len(VIEW_LABELS)
        # the pane menu offers replace / clear / clear all / clear pane
        assert len(menus[1].actions) == 5  # 4 entries plus the separator

    def test_replace_button_emits_the_pane(self, pane) -> None:
        seen: list[PaneId] = []
        pane.replace_requested.connect(seen.append)
        pane._replace_button.click()
        assert seen == [PaneId.LEFT]

    def test_clicking_empty_placeholder_arms_that_pane(self, pane) -> None:
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        pane.set_header(file_name="—", frame_text="—", has_clip=False, error=None)
        seen: list[PaneId] = []
        pane.replace_requested.connect(seen.append)
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(4, 4),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(pane._placeholder, event)
        assert seen == [PaneId.LEFT]

    def test_marker_button_emits_its_ordinal(self, pane) -> None:
        seen: list[int] = []
        pane.marker_place_requested.connect(lambda _pane, ordinal: seen.append(ordinal))
        pane.set_cycle_count(1)
        assert len(pane._marker_buttons) == 2
        # MK1 stays disabled until MK0 exists, so place it first
        pane._marker_buttons[0].click()
        pane.set_markers((EventMarker(frame_index=0),), 30, 0)
        pane._marker_buttons[1].click()
        assert seen == [0, 1]

    def test_clear_buttons_emit_the_pane(self, pane) -> None:
        clears: list[PaneId] = []
        pane.markers_cleared.connect(clears.append)
        pane.all_markers_cleared.connect(clears.append)
        pane._marker_buttons_layout.itemAt(2).widget().click()
        pane._marker_buttons_layout.itemAt(3).widget().click()
        assert clears == [PaneId.LEFT, PaneId.LEFT]

    def test_marker_strip_click_is_forwarded(self, pane) -> None:
        seen: list[tuple[PaneId, int]] = []
        pane.marker_seek_requested.connect(lambda pane_id, frame: seen.append((pane_id, frame)))
        pane.marker_strip.marker_clicked.emit(7)
        assert seen == [(PaneId.LEFT, 7)]

    def test_marker_strip_removal_is_forwarded(self, pane) -> None:
        seen: list[tuple[PaneId, int]] = []
        pane.marker_remove_requested.connect(lambda pane_id, ordinal: seen.append((pane_id, ordinal)))
        pane.marker_strip.marker_remove_requested.emit(2)
        assert seen == [(PaneId.LEFT, 2)]


class TestPaneMarkers:
    def test_cycle_count_grows_the_marker_buttons(self, pane) -> None:
        pane.set_cycle_count(1)
        assert [button.text() for button in pane._marker_buttons] == [
            tr("multiview.marker.set", label="MK0"),
            tr("multiview.marker.set", label="MK1"),
        ]
        pane.set_cycle_count(2)
        assert len(pane._marker_buttons) == 3
        assert tr("multiview.marker.set", label="MK2") in [b.text() for b in pane._marker_buttons]

    def test_placed_markers_are_marked(self, pane) -> None:
        pane.set_cycle_count(1)
        pane.set_markers((EventMarker(frame_index=0), EventMarker(frame_index=9)), 30, 4)
        assert pane._marker_buttons[0].property("placed") is True
        assert pane._marker_buttons[1].property("placed") is True

    def test_a_marker_may_be_re_placed(self, pane) -> None:
        pane.set_cycle_count(1)
        pane.set_markers((EventMarker(frame_index=0), EventMarker(frame_index=9)), 30, 4)
        # both slots are filled, so both buttons stay usable (spec 9: a marker
        # may be moved as long as the order stays forward)
        assert pane._marker_buttons[0].isEnabled() is True
        assert pane._marker_buttons[1].isEnabled() is True

    def test_markers_cannot_be_skipped(self, pane) -> None:
        pane.set_cycle_count(2)
        # three buttons, no marker yet: only MK0 may be placed
        assert len(pane._marker_buttons) == 3
        assert pane._marker_buttons[0].isEnabled() is True
        assert pane._marker_buttons[1].isEnabled() is False
        assert pane._marker_buttons[2].isEnabled() is False
        pane.set_markers((EventMarker(frame_index=0),), 30, 0)
        assert pane._marker_buttons[0].isEnabled() is True
        assert pane._marker_buttons[1].isEnabled() is True
        assert pane._marker_buttons[2].isEnabled() is False

    def test_marker_bar_visibility_is_toggleable(self, pane) -> None:
        pane.set_marker_bar_visible(True)
        assert pane._marker_bar.isVisible()
        pane.set_marker_bar_visible(False)
        assert not pane._marker_bar.isVisible()

    def test_window_is_forwarded_to_the_strip(self, pane) -> None:
        pane.set_window((3, 17))
        assert pane._marker_strip._window == (3, 17)
        pane.set_window(None)
        assert pane._marker_strip._window is None

    def test_view_labels_are_a_fixed_list(self, pane) -> None:
        assert "A4C" in VIEW_LABELS and "A2C" in VIEW_LABELS
        assert len(set(VIEW_LABELS)) == len(VIEW_LABELS)


class TestTransportBar:
    @pytest.fixture()
    def bar(self, qtbot):
        widget = MultiViewTransportBar()
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)
        return widget

    def test_independent_is_the_default_mode(self, bar) -> None:
        assert bar._mode_buttons[PlaybackMode.INDEPENDENT].isChecked()
        assert not bar._mode_buttons[PlaybackMode.COMMON_WINDOW].isChecked()

    def test_mode_button_emits_the_mode(self, bar) -> None:
        seen: list[PlaybackMode] = []
        bar.mode_changed.connect(seen.append)
        bar._mode_buttons[PlaybackMode.COMMON_WINDOW].click()
        assert seen == [PlaybackMode.COMMON_WINDOW]

    def test_cycle_combo_is_hidden_outside_the_marker_mode(self, bar) -> None:
        bar.refresh_mode(PlaybackMode.COMMON_WINDOW)
        assert not bar._cycle_combo.isVisible()
        assert not bar._cycle_label.isVisible()
        bar.refresh_mode(PlaybackMode.EVENT_CYCLE)
        assert bar._cycle_combo.isVisible()
        assert bar._cycle_label.isVisible()

    def test_speed_labels_are_hidden_in_the_independent_mode(self, bar) -> None:
        bar.refresh_mode(PlaybackMode.INDEPENDENT)
        assert not bar._left_rate_label.isVisible()
        assert not bar._right_rate_label.isVisible()
        assert not bar._unlink_button.isVisible()

    def test_stop_is_disabled_in_the_independent_mode(self, bar) -> None:
        bar.refresh_mode(PlaybackMode.INDEPENDENT)
        assert not bar._stop_button.isEnabled()
        bar.refresh_mode(PlaybackMode.COMMON_WINDOW)
        assert bar._stop_button.isEnabled()

    def test_play_button_flips_its_caption(self, bar) -> None:
        assert bar._play_button.text() == tr("multiview.transport.play")
        bar.set_playing(True)
        assert bar._play_button.text() == tr("multiview.transport.pause")
        bar.set_playing(False)
        assert bar._play_button.text() == tr("multiview.transport.play")

    def test_refresh_mode_keeps_the_playing_caption(self, bar) -> None:
        bar.set_playing(True)
        bar.refresh_mode(PlaybackMode.EVENT_CYCLE)
        assert bar._play_button.text() == tr("multiview.transport.pause")

    def test_rate_combo_offers_the_supported_band(self, bar) -> None:
        rates = [bar._rate_combo.itemData(index) for index in range(bar._rate_combo.count())]
        assert rates == [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

    def test_rate_combo_emits_the_chosen_rate(self, bar) -> None:
        seen: list[float] = []
        bar.rate_changed.connect(seen.append)
        bar._rate_combo.setCurrentIndex(bar._rate_combo.findData(1.5))
        assert seen == [1.5]

    def test_set_rate_selects_the_matching_entry(self, bar) -> None:
        bar.set_rate(0.75)
        assert bar._rate_combo.currentData() == 0.75

    def test_cycle_combo_emits_the_count(self, bar) -> None:
        seen: list[int] = []
        bar.cycle_count_changed.connect(seen.append)
        bar._cycle_combo.setCurrentIndex(bar._cycle_combo.findData(2))
        assert seen == [2]

    def test_set_cycle_count_selects_the_entry(self, bar) -> None:
        bar.set_cycle_count(2)
        assert bar._cycle_combo.currentData() == 2

    def test_stop_and_unlink_emit(self, bar) -> None:
        bar.refresh_mode(PlaybackMode.COMMON_WINDOW)
        stops: list[int] = []
        unlinks: list[int] = []
        bar.stop_clicked.connect(lambda: stops.append(1))
        bar.unlink_clicked.connect(lambda: unlinks.append(1))
        bar._stop_button.click()
        bar._unlink_button.click()
        assert stops == [1]
        assert unlinks == [1]

    def test_stay_stays_disabled_without_a_synchronised_mode(self, bar) -> None:
        bar.refresh_mode(PlaybackMode.INDEPENDENT)
        stops: list[int] = []
        bar.stop_clicked.connect(lambda: stops.append(1))
        bar._stop_button.click()
        assert stops == []

    def test_status_and_rate_labels(self, bar) -> None:
        bar.set_status("По времени")
        assert bar._status_label.text() == "По времени"
        assert bar._status_label.toolTip() == "По времени"
        bar.set_pane_rates("k 0.89×", "k 1.11×")
        assert bar._left_rate_label.text() == "k 0.89×"
        assert bar._right_rate_label.text() == "k 1.11×"


class TestMarkerStrip:
    @pytest.fixture()
    def strip(self, qtbot):
        widget = MarkerStrip()
        qtbot.addWidget(widget)
        widget.resize(300, 18)
        widget.set_track(0.0, 300.0)
        widget.show()
        qtbot.waitExposed(widget)
        return widget

    def test_markers_map_onto_the_track(self, strip) -> None:
        strip.set_markers((EventMarker(frame_index=0), EventMarker(frame_index=9)), 10)
        rects = strip.marker_rects()
        assert len(rects) == 2
        assert rects[0][0].center().x() == pytest.approx(0.0, abs=1e-6)
        assert rects[1][0].center().x() == pytest.approx(300.0, abs=1e-6)

    def test_single_frame_clip_puts_every_marker_at_the_start(self, strip) -> None:
        strip.set_markers((EventMarker(frame_index=0),), 1)
        assert strip.marker_rects()[0][0].center().x() == pytest.approx(0.0)

    def test_out_of_range_marker_is_clamped(self, strip) -> None:
        strip.set_markers((EventMarker(frame_index=99),), 10)
        assert strip.marker_rects()[0][0].center().x() == pytest.approx(300.0)

    def test_tooltip_lists_the_markers(self, strip) -> None:
        strip.set_markers((EventMarker(frame_index=3),), 30)
        strip.refresh_tooltip()
        assert "1. " in strip.toolTip()
        assert "#4" in strip.toolTip()

    def test_empty_strip_has_no_tooltip(self, strip) -> None:
        strip.set_markers((), 30)
        strip.refresh_tooltip()
        assert strip.toolTip() == ""

    def test_window_band_is_dropped_when_empty(self, strip) -> None:
        strip.set_markers((), 30)
        strip.set_window(5, 5)
        assert strip._window is None
        strip.set_window(9, 4)
        assert strip._window is None
        strip.set_window(2, 20)
        assert strip._window == (2, 20)

    def test_colours_cycle(self) -> None:
        assert marker_color(0) != marker_color(1)
        assert marker_color(0) == marker_color(len(_MARKER_COLORS_SAFE))

    def test_clicking_a_marker_seeks(self, strip) -> None:
        seen: list[int] = []
        strip.marker_clicked.connect(seen.append)
        strip.set_markers((EventMarker(frame_index=5),), 30)
        centre = strip.marker_rects()[0][0].center()
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        strip.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(centre),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert seen == [5]


_MARKER_COLORS_SAFE = ("#ff5252", "#ffb300", "#40c4ff", "#69f0ae", "#e040fb", "#ffd740")


class _FakeMenu:
    """Stands in for QMenu so a click never opens a modal popup."""

    def __init__(self, actions: list[str]) -> None:
        self.actions = actions

    @classmethod
    def factory(cls, sink: list[_FakeMenu]):
        def build(*_args, **_kwargs):
            menu = cls([])
            sink.append(menu)
            return menu

        return build

    def addAction(self, text=None, *_args, **_kwargs):
        self.actions.append(text or "")
        return _FakeAction()

    def addSeparator(self) -> None:
        self.actions.append("---")

    def exec(self, *_args, **_kwargs):
        return None


class _FakeAction:
    def setCheckable(self, _value: bool) -> None:
        pass

    def setChecked(self, _value: bool) -> None:
        pass

    def text(self) -> str:
        return ""
