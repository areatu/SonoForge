"""Tests for editors/base_editor.py."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

pytestmark = pytest.mark.gui


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
        # Should not raise
        editor.delete_selected()

    def test_has_parent_set(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.base_editor import BaseEditor

        parent = QWidget()
        editor = BaseEditor(parent)
        qtbot.addWidget(parent)
        qtbot.addWidget(editor)
        assert editor.parent() is parent
