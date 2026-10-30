"""GUI tests for the phrases column of the report mode (UI-4 PR-3).

The cases pin the contract of spec §4.6: groups by section, search, a click
inserting at the cursor, ✓ on the phrases the conclusion already contains, the
conclusion draft, the local library (add/delete/import/export) and the fact
that every colour comes from the active theme.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("pytestqt")
pytestmark = pytest.mark.gui

from echo_personal_tool.domain.measurement_catalog import SECTIONS  # noqa: E402
from echo_personal_tool.domain.services.report_phrases import (  # noqa: E402
    MAX_PHRASE_TEXT,
    PHRASES,
    ReportPhrase,
    dumped_document,
    make_user_phrase,
    parse_phrase_document,
)
from echo_personal_tool.infrastructure.report_phrase_store import PhraseStore  # noqa: E402
from echo_personal_tool.presentation.report_mode import phrases as phrases_module  # noqa: E402
from echo_personal_tool.presentation.report_mode.phrases import (  # noqa: E402
    PhraseEditorDialog,
    ReportPhrasesPanel,
)

#: A colour literal inside a stylesheet (must be a token value, not a hardcode).
_COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def store(tmp_path) -> PhraseStore:
    return PhraseStore(tmp_path / "phrases.json")


@pytest.fixture()
def panel(qtbot, store) -> ReportPhrasesPanel:
    widget = ReportPhrasesPanel(store)
    qtbot.addWidget(widget)
    widget.resize(336, 760)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _flush() -> None:
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _labels(panel: ReportPhrasesPanel):
    from PySide6.QtWidgets import QLabel

    return [label for label in panel.findChildren(QLabel) if label.objectName() == "reportPhrase"]


def _label_for(panel: ReportPhrasesPanel, phrase: ReportPhrase):
    return next(label for label in _labels(panel) if label.property("phraseId") == phrase.id)


def _headers(panel: ReportPhrasesPanel) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in panel.findChildren(QLabel) if label.objectName() == "reportPhraseGroup"]


def _status(panel: ReportPhrasesPanel) -> str:
    from PySide6.QtWidgets import QLabel

    return panel.findChild(QLabel, "reportPhrasesStatus").text()


class TestColumn:
    def test_the_column_lists_the_starter_set_by_section(self, panel) -> None:
        from PySide6.QtWidgets import QLabel

        assert panel.findChild(QLabel, "reportPhrasesTitle").text() == "Фразы"
        assert panel.findChild(QLabel, "reportPhrasesHint").text() == "клик — вставить"
        assert _headers(panel)[0] == SECTIONS["general"].label("ru").short
        assert SECTIONS["lv"].label("ru").short in _headers(panel)
        assert len(_labels(panel)) == len(PHRASES)
        assert panel.conclusion == ""

    def test_search_filters_by_text_in_either_language_and_shows_the_empty_state(self, panel) -> None:
        panel._search.setText("аорты")
        _flush()
        aorta = {phrase.id for phrase in PHRASES if phrase.section == "aorta"}
        assert {label.property("phraseId") for label in _labels(panel)} == aorta

        panel._search.setText("left ventricular cavity")
        _flush()
        assert {label.property("phraseId") for label in _labels(panel)} == {"builtin.lv.no_dilation"}

        panel._search.setText("zzz-no-such-phrase")
        _flush()
        from PySide6.QtWidgets import QLabel

        empty = panel.findChild(QLabel, "reportPhrasesEmpty")
        assert empty is not None and empty.text() == "Ничего не найдено"
        assert _labels(panel) == []


class TestInsertion:
    def test_a_click_inserts_the_phrase_at_the_cursor(self, panel) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QTextCursor
        from PySide6.QtTest import QTest

        phrase = next(item for item in PHRASES if item.id == "builtin.lv.wall_thickness")
        panel.set_conclusion("Полость ЛЖ не расширена")
        panel._editor.moveCursor(QTextCursor.MoveOperation.End)
        emitted: list[str] = []
        panel.conclusion_changed.connect(emitted.append)

        QTest.mouseClick(_label_for(panel, phrase), Qt.MouseButton.LeftButton)

        assert panel.conclusion == "Полость ЛЖ не расширена. Толщина стенок левого желудочка в норме."
        assert emitted[-1] == panel.conclusion

    def test_a_phrase_can_be_inserted_from_the_keyboard(self, panel) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        phrase = PHRASES[3]
        label = _label_for(panel, phrase)
        label.setFocus()
        QTest.keyClick(label, Qt.Key.Key_Return)
        assert phrase.text("ru") in panel.conclusion

    def test_the_check_mark_follows_the_conclusion(self, panel) -> None:
        phrase = PHRASES[0]
        panel.set_conclusion(phrase.text("ru"))
        label = _label_for(panel, phrase)
        assert label.text().startswith("✓ ")
        assert label.property("inserted") is True

        panel.set_conclusion("")
        label = _label_for(panel, phrase)
        assert label.text() == phrase.text("ru")
        assert label.property("inserted") is False

    def test_set_conclusion_does_not_emit_but_typing_does(self, panel) -> None:
        emitted: list[str] = []
        panel.conclusion_changed.connect(emitted.append)

        panel.set_conclusion("черновик")
        assert emitted == []

        panel._editor.setPlainText("правка")
        assert emitted and emitted[-1] == "правка"
        assert panel.conclusion == "правка"


class TestUserLibrary:
    def test_a_user_phrase_is_stored_listed_and_can_be_deleted(self, panel, store) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QPushButton

        added = panel.add_user_phrase("lv", "Своя фраза", "My phrase")
        assert added is not None
        assert store.phrases() == (added,)
        _flush()

        label = _label_for(panel, added)
        assert label.property("builtin") is False
        assert label.text() == "Своя фраза"

        delete = next(
            button for button in panel.findChildren(QPushButton) if button.objectName() == "reportPhraseDelete"
        )
        QTest.mouseClick(delete, Qt.MouseButton.LeftButton)
        _flush()

        assert store.phrases() == ()
        assert all(label.property("phraseId") != added.id for label in _labels(panel))

    def test_a_duplicate_of_a_builtin_phrase_is_refused_with_a_status(self, panel, store) -> None:
        result = panel.add_user_phrase("lv", PHRASES[0].ru, PHRASES[0].en)
        assert result is None
        assert store.phrases() == ()
        assert "уже есть" in _status(panel)

    def test_import_and_export_use_one_document(self, panel, store, tmp_path) -> None:
        imported = make_user_phrase("la", "Импортированная фраза", "Imported phrase")
        assert imported is not None
        source = tmp_path / "library.json"
        source.write_text(dumped_document((imported,)), encoding="utf-8")

        result = panel.import_phrases(source)

        assert result is not None and result.added == 1
        assert "Добавлено: 1" in _status(panel)
        assert any(phrase.id == imported.id for phrase in panel.phrases)

        target = tmp_path / "export.json"
        assert panel.export_phrases(target) == 1
        assert parse_phrase_document(target.read_text(encoding="utf-8")).phrases == (imported,)
        assert "Сохранено фраз: 1" in _status(panel)

        again = panel.import_phrases(source)
        assert again is not None and again.duplicates == 1

    def test_a_broken_file_is_reported_instead_of_raising(self, panel, tmp_path) -> None:
        source = tmp_path / "broken.json"
        source.write_text("{not json", encoding="utf-8")
        assert panel.import_phrases(source) is None
        assert "Не удалось" in _status(panel)

    def test_the_action_buttons_go_through_the_styled_file_dialogs(self, panel, monkeypatch, tmp_path) -> None:
        imported = make_user_phrase("lv", "Через диалог", "Through the dialog")
        assert imported is not None
        source = tmp_path / "source.json"
        source.write_text(dumped_document((imported,)), encoding="utf-8")
        calls: list[tuple[str, str]] = []

        def _open(*args, **kwargs):
            calls.append(("open", args[0].objectName()))
            return str(source), ""

        target = tmp_path / "target.json"

        def _save(*args, **kwargs):
            calls.append(("save", args[0].objectName()))
            return str(target), ""

        monkeypatch.setattr(phrases_module, "styled_open_file", _open)
        monkeypatch.setattr(phrases_module, "styled_save_file", _save)

        panel._import.click()
        panel._export.click()

        assert calls == [("open", "reportPhrases"), ("save", "reportPhrases")]
        assert target.is_file()


class TestLanguageAndTheme:
    def test_reload_text_switches_the_language_and_keeps_the_conclusion(self, panel) -> None:
        from echo_personal_tool.infrastructure.i18n import set_language

        phrase = PHRASES[3]
        panel.set_conclusion("Текст заключения")
        set_language("en")
        panel.reload_text()
        _flush()

        from PySide6.QtWidgets import QLabel

        assert panel.findChild(QLabel, "reportPhrasesTitle").text() == "Phrases"
        assert SECTIONS["lv"].label("en").short in _headers(panel)
        assert panel.conclusion == "Текст заключения"
        assert _label_for(panel, phrase).text() == phrase.en

    def test_every_colour_is_a_token_of_the_active_theme(self, panel) -> None:
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        allowed = set(get_theme_tokens().values())
        literals = set(_COLOUR_LITERAL.findall(panel.styleSheet()))
        assert literals
        assert literals <= allowed


class TestConclusionAutofill:
    """The explicit autofill button: one undo step, read-only and failure safety."""

    @staticmethod
    def _result(text: str, block: str, *, changed: bool = True, status: str = "added"):
        from echo_personal_tool.application.report_conclusion import ConclusionAutofillResult

        return ConclusionAutofillResult(
            text=text,
            generated_block=block,
            status_key=f"report.conclusion.status.{status}",
            changed=changed,
            finding_count=1,
        )

    def test_button_is_disabled_without_a_provider_and_enabled_with_one(self, panel, store) -> None:
        from PySide6.QtWidgets import QPushButton

        assert panel.findChild(QPushButton, "reportConclusionAutofill").isEnabled() is False
        widget = ReportPhrasesPanel(store, conclusion_autofill_provider=lambda: self._result("• A", "• A"))
        assert widget.conclusion_autofill_button.isEnabled() is True

    def test_click_applies_the_provider_result_and_emits_the_managed_block(self, panel) -> None:
        from PySide6.QtWidgets import QLabel

        panel.set_conclusion_autofill_provider(lambda: self._result("Ручной текст.\n\n• A", "• A"))
        panel.set_conclusion("Ручной текст.")
        emitted: list[str] = []
        blocks: list[str] = []
        panel.conclusion_changed.connect(emitted.append)
        panel.generated_conclusion_changed.connect(blocks.append)

        panel.conclusion_autofill_button.click()

        assert panel.conclusion == "Ручной текст.\n\n• A"
        assert emitted[-1] == panel.conclusion
        assert blocks == ["• A"]
        status = panel.findChild(QLabel, "reportConclusionAutofillStatus")
        assert status.isVisible()
        assert status.text() == "Черновик заключения добавлен."

    def test_one_click_is_one_undo_step(self, panel) -> None:
        panel.set_conclusion_autofill_provider(lambda: self._result("До\n\n• A", "• A"))
        panel.set_conclusion("До")
        panel.conclusion_autofill_button.click()
        assert panel.conclusion == "До\n\n• A"
        panel._editor.undo()
        assert panel.conclusion == "До"

    def test_read_only_finished_report_cannot_be_autofilled(self, panel) -> None:
        calls: list[int] = []

        def provider():
            calls.append(1)
            return self._result("• A", "• A")

        panel.set_conclusion_autofill_provider(provider)
        panel.set_conclusion("Завершено")
        panel.set_read_only(True)
        assert panel.conclusion_autofill_button.isEnabled() is False
        panel._on_autofill_conclusion()
        assert calls == []
        assert panel.conclusion == "Завершено"

    def test_provider_failure_leaves_the_text_unchanged(self, panel) -> None:
        from PySide6.QtWidgets import QLabel

        def provider():
            raise RuntimeError("patient text must not be logged")

        panel.set_conclusion_autofill_provider(provider)
        panel.set_conclusion("Ручной текст")
        panel.conclusion_autofill_button.click()
        assert panel.conclusion == "Ручной текст"
        assert panel.findChild(QLabel, "reportConclusionAutofillStatus").text() == (
            "Не удалось сформировать заключение. Текст не изменён."
        )

    def test_button_and_hint_follow_the_ui_language(self, panel) -> None:
        from echo_personal_tool.infrastructure.i18n import set_language

        panel.set_conclusion_autofill_provider(lambda: self._result("• A", "• A"))
        assert panel.conclusion_autofill_button.text() == "Заполнить заключение"
        set_language("en")
        panel.reload_text()
        assert panel.conclusion_autofill_button.text() == "Fill conclusion"
        assert "adult TTE" in panel.conclusion_autofill_button.toolTip()
        set_language("ru")
        panel.reload_text()


class TestEditorDialog:
    def test_validation_and_values(self, qtbot) -> None:
        dialog = PhraseEditorDialog()
        qtbot.addWidget(dialog)
        assert dialog._save.isEnabled() is False

        dialog.set_values("lv", "Фраза", "")
        assert dialog._save.isEnabled() is True
        assert dialog.values() == ("lv", "Фраза", "")

        dialog.set_values("lv", "x" * (MAX_PHRASE_TEXT + 1), "")
        assert dialog._save.isEnabled() is False
        assert str(MAX_PHRASE_TEXT) in dialog._hint.text()

    def test_every_catalog_section_is_offered(self, qtbot) -> None:
        dialog = PhraseEditorDialog()
        qtbot.addWidget(dialog)
        assert dialog._section.count() == len(SECTIONS)
        assert {dialog._section.itemData(index) for index in range(dialog._section.count())} == set(SECTIONS)
