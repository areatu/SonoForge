"""The study strip must not rebuild its tabs on selection/caption changes."""

from unittest.mock import patch

import pytest
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QTabBar

from echo_personal_tool.presentation.tab_bar import TabStrip

pytestmark = pytest.mark.gui


def test_selection_keeps_bar_and_close_button_identity_without_add_remove(qtbot):
    strip = TabStrip()
    qtbot.addWidget(strip)
    items = [("a", "A"), ("b", "B"), ("c", "C")]
    strip.set_tabs(items, "a")
    bar = strip._bar
    buttons = [bar.tabButton(i, QTabBar.ButtonPosition.RightSide) for i in range(3)]
    selected = []
    strip.tab_selected.connect(selected.append)
    with (
        patch.object(bar, "addTab", wraps=bar.addTab) as add,
        patch.object(bar, "removeTab", wraps=bar.removeTab) as remove,
        patch.object(bar, "setTabText", wraps=bar.setTabText) as text,
        patch.object(bar, "setCurrentIndex", wraps=bar.setCurrentIndex) as current,
    ):
        strip.set_tabs(items, "b")
        strip.set_tabs(items, "b")  # completion of an async load: no-op
        assert strip._bar is bar
        assert add.call_count == remove.call_count == text.call_count == 0
        assert current.call_count == 1
    assert [bar.tabButton(i, QTabBar.ButtonPosition.RightSide) for i in range(3)] == buttons
    assert strip.current_tab_id() == "b"
    qtbot.wait(1)
    assert selected == []


def test_same_ids_update_only_changed_caption_and_tooltip(qtbot):
    strip = TabStrip()
    qtbot.addWidget(strip)
    strip.set_tabs([("a", "Loading"), ("b", "B")], "a")
    with patch.object(strip._bar, "addTab", wraps=strip._bar.addTab) as add:
        strip.set_tabs([("a", "Study A"), ("b", "B")], "a")
        assert add.call_count == 0
    assert strip.caption("a") == strip._bar.tabToolTip(0) == "Study A"
    with QSignalBlocker(strip._bar):
        strip.set_tabs([("a", "Study A"), ("b", "B")], "b")
        assert strip._bar.signalsBlocked(), "nested calls must restore the previous block state"


def test_membership_and_order_changes_still_rebuild(qtbot):
    strip = TabStrip()
    qtbot.addWidget(strip)
    for items, active in [
        ([("a", "A"), ("b", "B")], "b"),
        ([("b", "B"), ("a", "A")], "a"),
        ([("a", "A")], "a"),
        ([], None),
    ]:
        strip.set_tabs(items, active)
        assert strip.tab_ids() == [tab_id for tab_id, _ in items]
        assert strip.current_tab_id() == active


def test_tab_bar_is_movable_and_reports_drag_moves(qtbot):
    """Э9 §4: tabs can be dragged to reorder."""
    strip = TabStrip()
    qtbot.addWidget(strip)
    assert strip._bar.isMovable()
    strip.set_tabs([("a", "A"), ("b", "B"), ("c", "C")], "a")
    moves = []
    strip.tab_moved.connect(lambda frm, to: moves.append((frm, to)))
    strip._bar.moveTab(0, 2)
    qtbot.waitUntil(lambda: bool(moves), timeout=1000)
    assert moves == [(0, 2)]


def test_context_menu_close_and_close_others(qtbot):
    """Э9 §4: the tab context menu offers «Закрыть» and «Закрыть другие»."""
    from unittest.mock import patch

    from echo_personal_tool.infrastructure.i18n import tr

    strip = TabStrip()
    qtbot.addWidget(strip)
    strip.show()
    qtbot.waitExposed(strip)
    strip.set_tabs([("a", "A"), ("b", "B"), ("c", "C")], "a")
    closed = []
    others = []
    strip.tab_close_requested.connect(closed.append)
    strip.tab_close_others_requested.connect(others.append)
    pos = strip._bar.tabRect(1).center()

    captured: dict = {}

    def _choose_first(menu, global_pos):
        captured["actions"] = [action.text() for action in menu.actions()]
        return menu.actions()[0]

    with patch.object(strip, "_exec_tab_menu", _choose_first):
        strip._show_context_menu(pos)
    qtbot.waitUntil(lambda: bool(closed), timeout=1000)
    assert closed == ["b"]
    assert others == []
    assert captured["actions"] == [tr("tabs.close"), tr("tabs.close_others")]

    with patch.object(strip, "_exec_tab_menu", lambda menu, global_pos: menu.actions()[1]):
        strip._show_context_menu(pos)
    qtbot.waitUntil(lambda: bool(others), timeout=1000)
    assert others == ["b"]
    assert closed == ["b"]

    # Cancelling the menu emits nothing new.
    with patch.object(strip, "_exec_tab_menu", lambda menu, global_pos: None):
        strip._show_context_menu(pos)
    qtbot.wait(5)
    assert closed == ["b"] and others == ["b"]
