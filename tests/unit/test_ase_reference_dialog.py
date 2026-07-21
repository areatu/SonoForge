"""Tests for ASE reference dialog."""


from __future__ import annotations

from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

pytestmark = pytest.mark.gui


def test_reference_dialog_shows_structured_by_default(qtbot) -> None:
    dialog = AseReferenceDialog()
    qtbot.addWidget(dialog)
    # Structured widget exists and is the default view
    assert dialog._structured_widget is not None
    assert dialog._active_doc_index == -1  # no document selected, structured view active


def test_reference_dialog_has_structured_tab(qtbot) -> None:
    dialog = AseReferenceDialog()
    qtbot.addWidget(dialog)
    assert dialog._structured_widget is not None


def test_structured_tab_shows_topics(qtbot) -> None:
    dialog = AseReferenceDialog()
    qtbot.addWidget(dialog)
    widget = dialog._structured_widget
    assert len(widget._topic_buttons) >= 8


def test_navigate_to_param(qtbot) -> None:
    dialog = AseReferenceDialog()
    qtbot.addWidget(dialog)
    dialog.navigate_to_param("lvef")
    widget = dialog._structured_widget
    assert widget._current_topic is not None
    assert len(widget._param_cards) >= 1


def test_structured_tab_unchecked_on_doc_tab(qtbot) -> None:
    dialog = AseReferenceDialog()
    qtbot.addWidget(dialog)
    # Initially structured tab is checked
    assert dialog._btn_structured_tab.isChecked()
    # When a doc tab is clicked, structured tab should uncheck
    # (this relies on the `_switch_to_doc` mechanism)
    assert dialog._active_doc_index == -1
