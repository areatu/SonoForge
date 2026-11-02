"""Tests for editors/base_editor.py."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

pytestmark = pytest.mark.gui


class TestMatchesQuery:
    def test_ignores_the_case_of_the_query_and_of_the_text(self) -> None:
        from echo_personal_tool.constructor.editors.base_editor import matches_query

        assert matches_query("IVS", "IVSd")
        assert matches_query("ivs", "IVSd")
        assert matches_query("IvS", "ivsd")
        assert matches_query("ЛЕВЫЙ", "Левый желудочек")
        assert matches_query("левый", "ЛЕВЫЙ ЖЕЛУДОЧЕК")

    def test_looks_in_every_field(self) -> None:
        from echo_personal_tool.constructor.editors.base_editor import matches_query

        assert matches_query("MK", "Митральный клапан", "mk")
        assert not matches_query("zzz", "Митральный клапан", "mk")

    def test_an_empty_query_matches_everything(self) -> None:
        from echo_personal_tool.constructor.editors.base_editor import matches_query

        assert matches_query("", "anything")


class TestBaseEditor:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.base_editor import BaseEditor

        editor = BaseEditor()
        qtbot.addWidget(editor)
        assert editor is not None

    def test_content_changed_signal(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.base_editor import BaseEditor

        editor = BaseEditor()
        qtbot.addWidget(editor)
        received = []
        editor.content_changed.connect(lambda: received.append(True))
        editor.content_changed.emit()
        assert len(received) == 1

    def test_delete_selected_noop(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.base_editor import BaseEditor

        editor = BaseEditor()
        qtbot.addWidget(editor)
        # Should not raise; the base class has nothing to delete, so nothing changes
        with qtbot.assertNotEmitted(editor.content_changed):
            editor.delete_selected()

    def test_has_parent_set(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.base_editor import BaseEditor

        parent = QWidget()
        editor = BaseEditor(parent)
        qtbot.addWidget(parent)
        qtbot.addWidget(editor)
        assert editor.parent() is parent
