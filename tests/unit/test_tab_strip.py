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
