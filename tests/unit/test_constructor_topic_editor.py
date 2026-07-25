"""Tests for editors/topic_editor.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from echo_personal_tool.constructor.models import TopicModel

pytestmark = pytest.mark.gui

_THEME = {
    "bg_dark": "#111827",
    "bg_panel": "#1a2332",
    "bg_control": "#243044",
    "bg_button": "#2e4054",
    "bg_button_hover": "#3a5068",
    "bg_button_pressed": "#1e2a38",
    "accent": "#9ca3b0",
    "accent_bright": "#b0b8c0",
    "accent_tab": "#3b82f6",
    "text": "#f1f5f9",
    "text_dim": "#94a3b8",
    "border": "#334155",
}


@pytest.fixture
def topics() -> list[TopicModel]:
    return [
        TopicModel(name="Левый желудочек", slug="lv"),
        TopicModel(name="Правый желудочек", slug="rv"),
        TopicModel(name="Митральный клапан", slug="mk"),
    ]


@pytest.fixture
def editor(qtbot) -> TopicEditor:
    from echo_personal_tool.constructor.editors.topic_editor import TopicEditor

    with patch(
        "echo_personal_tool.constructor.editors.topic_editor.get_theme_palette",
        return_value=_THEME,
    ):
        w = TopicEditor()
    qtbot.addWidget(w)
    return w


class TestSetTopics:
    def test_set_topics(self, editor, topics) -> None:
        editor.set_topics(topics)
        assert len(editor._topics) == 3
        assert len(editor._all_items) == 3

    def test_set_empty(self, editor) -> None:
        editor.set_topics([])
        assert len(editor._topics) == 0


class TestFilter:
    def test_filter_match(self, editor, topics) -> None:
        editor.set_topics(topics)
        editor.filter("левый")
        assert editor._list.count() == 1

    def test_filter_no_match(self, editor, topics) -> None:
        editor.set_topics(topics)
        editor.filter("zzz")
        assert editor._list.count() == 0

    def test_filter_slug(self, editor, topics) -> None:
        editor.set_topics(topics)
        editor.filter("mk")
        assert editor._list.count() == 1

    def test_clear_filter(self, editor, topics) -> None:
        editor.set_topics(topics)
        editor.filter("левый")
        editor.clear_filter()
        assert editor._list.count() == 3


class TestAddTopic:
    def test_add_topic(self, editor) -> None:
        editor.set_topics([])
        spy_signal = editor.topics_changed
        editor._add_topic()
        assert len(editor._topics) == 1
        assert editor._topics[0].slug == "new_topic_1"

    def test_add_topic_unique_slug(self, editor) -> None:
        existing = [TopicModel(name="T", slug="new_topic_1")]
        editor.set_topics(existing)
        editor._add_topic()
        assert editor._topics[-1].slug == "new_topic_2"

    def test_add_topic_emits_signal(self, editor) -> None:
        editor.set_topics([])
        received = []
        editor.topics_changed.connect(lambda: received.append(True))
        editor._add_topic()
        assert len(received) >= 1


class TestDuplicateTopic:
    def test_duplicate(self, editor, topics) -> None:
        editor.set_topics(topics)
        # Select first item to duplicate
        editor._list.setCurrentRow(0)
        editor._duplicate_topic()
        assert len(editor._topics) == 4
        assert "copy_1" in editor._topics[-1].slug

    def test_duplicate_no_selection(self, editor) -> None:
        editor.set_topics([])
        editor._duplicate_topic()
        assert len(editor._topics) == 0

    def test_duplicate_emits_signal(self, editor, topics) -> None:
        editor.set_topics(topics)
        editor._list.setCurrentRow(0)
        received = []
        editor.topics_changed.connect(lambda: received.append(True))
        editor._duplicate_topic()
        assert len(received) >= 1


class TestDeleteTopic:
    @patch("echo_personal_tool.constructor.editors.topic_editor.QMessageBox")
    def test_delete_confirmed(self, mock_msgbox, editor, topics) -> None:
        mock_msgbox.question.return_value = mock_msgbox.StandardButton.Yes
        editor.set_topics(topics)
        editor._list.setCurrentRow(0)
        editor._delete_selected()
        assert len(editor._topics) == 2

    @patch("echo_personal_tool.constructor.editors.topic_editor.QMessageBox")
    def test_delete_cancelled(self, mock_msgbox, editor, topics) -> None:
        mock_msgbox.question.return_value = mock_msgbox.StandardButton.No
        editor.set_topics(topics)
        editor._list.setCurrentRow(0)
        editor._delete_selected()
        assert len(editor._topics) == 3

    def test_delete_no_selection(self, editor) -> None:
        editor.set_topics([])
        editor._delete_selected()
        assert len(editor._topics) == 0
