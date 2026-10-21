"""Phrases column of the report mode (UI-4 PR-3, spec §4.6, UQ-08).

The column has three parts, top to bottom: the searchable phrase library
(grouped by report section, ✓ on the phrases already present in the text), the
conclusion editor, and — from UI-4 PR-5 — the export block.  A click on a
phrase inserts it at the cursor of the conclusion; nothing is inserted
automatically (UQ-08), and the ✓ mark only reports what the text already
contains.

User phrases belong to the physician, not to the study: they are stored
locally by :class:`~echo_personal_tool.infrastructure.report_phrase_store.PhraseStore`
and can be imported or exported as one JSON document.  The built-in starter set
lives in :mod:`echo_personal_tool.domain.services.report_phrases` and cannot be
deleted here.

The conclusion itself is a per-tab draft (``TabSession.report_conclusion``):
the window keeps the text in the tab, so switching studies does not mix two
conclusions, and hands it to the report document that builds the A4 sheet.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.measurement_catalog import SECTIONS
from echo_personal_tool.domain.services.report_phrases import (
    MAX_PHRASE_TEXT,
    MAX_USER_PHRASES,
    PHRASES,
    PhraseDocumentError,
    ReportPhrase,
    clean_text,
    inserted_phrase_ids,
    insertion_segment,
    make_user_phrase,
    normalize_for_search,
    phrase_groups,
    phrases_match,
)
from echo_personal_tool.infrastructure.i18n import get_language, tr
from echo_personal_tool.infrastructure.report_phrase_store import ImportResult, PhraseStore
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.styled_dialogs import (
    localize_dialog_button_box,
    styled_open_file,
    styled_save_file,
)

logger = logging.getLogger(__name__)

#: Spec §4.6: the phrases column is 336 px wide.
#: Width of the right column (spec §4.6: 336 px).
PANEL_WIDTH = 336
_PANEL_WIDTH = PANEL_WIDTH

#: How long an import/export/limit message stays in the column.
_STATUS_TIMEOUT_MS = 8000


class _PhraseLabel(QLabel):
    """One clickable phrase.

    ``QLabel`` rather than a button: phrases wrap onto two lines in a 336 px
    column, which ``QPushButton`` cannot do.  Keyboard activation is kept
    (Tab reaches the label, Enter/Space inserts) so the column is not
    mouse-only.
    """

    activated = Signal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("reportPhrase")
        self.setWordWrap(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setAccessibleName(text)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PhraseEditorDialog(QDialog):
    """«Своя фраза»: section, Russian and English text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reportPhraseEditor")
        self.setWindowTitle(tr("report.phrase_editor_title"))
        self.resize(480, 360)

        self._section = QComboBox()
        self._section.setObjectName("reportPhraseEditorSection")
        for section in SECTIONS.values():
            self._section.addItem(section.label(get_language()).short, section.id)

        self._ru = QPlainTextEdit()
        self._ru.setObjectName("reportPhraseEditorRu")
        self._ru.setPlaceholderText(tr("report.phrase_editor_ru"))
        self._ru.setMinimumHeight(72)
        self._en = QPlainTextEdit()
        self._en.setObjectName("reportPhraseEditorEn")
        self._en.setPlaceholderText(tr("report.phrase_editor_en"))
        self._en.setMinimumHeight(72)

        self._hint = QLabel()
        self._hint.setObjectName("reportPhraseEditorHint")
        self._hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow(tr("report.phrase_editor_section"), self._section)
        form.addRow(tr("report.phrase_editor_ru"), self._ru)
        form.addRow(tr("report.phrase_editor_en"), self._en)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        localize_dialog_button_box(buttons)
        self._save = buttons.button(QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._hint)
        layout.addWidget(buttons)

        self._ru.textChanged.connect(self._validate)
        self._en.textChanged.connect(self._validate)
        self._apply_theme()
        self._validate()

    def values(self) -> tuple[str, str, str]:
        """``(section, ru, en)`` as typed; normalization happens in the domain."""
        return str(self._section.currentData() or "general"), self._ru.toPlainText(), self._en.toPlainText()

    def set_values(self, section: str, ru: str = "", en: str = "") -> None:
        """Prefill (tests and future «edit phrase»); no validation is bypassed."""
        index = self._section.findData(section)
        self._section.setCurrentIndex(index if index >= 0 else 0)
        self._ru.setPlainText(ru)
        self._en.setPlainText(en)

    def _apply_theme(self) -> None:
        tokens = get_theme_tokens()
        self._hint.setStyleSheet(
            f"""#reportPhraseEditorHint[problem="true"] {{
                color: {tokens["state.err"]};
            }}"""
        )

    def _validate(self) -> None:
        ru = clean_text(self._ru.toPlainText())
        en = clean_text(self._en.toPlainText())
        too_long = len(ru) > MAX_PHRASE_TEXT or len(en) > MAX_PHRASE_TEXT
        self._save.setEnabled(bool(ru or en) and not too_long)
        self._hint.setText(
            tr("report.phrase_editor_too_long", limit=MAX_PHRASE_TEXT) if too_long else tr("report.phrase_editor_hint")
        )
        self._hint.setProperty("problem", too_long)
        style = self._hint.style()
        style.unpolish(self._hint)
        style.polish(self._hint)


class ReportPhrasesPanel(QFrame):
    """The right column of the report mode: phrases and the conclusion draft."""

    conclusion_changed = Signal(str)

    def __init__(self, store: PhraseStore | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reportPhrases")
        self.setFixedWidth(_PANEL_WIDTH)
        self._store = store if store is not None else PhraseStore()
        self._phrase_by_id: dict[str, ReportPhrase] = {}
        self._phrases: tuple[ReportPhrase, ...] = ()
        self._labels: dict[str, _PhraseLabel] = {}
        self._conclusion = ""
        self._read_only = False
        self._reload_library(rebuild=False)

        self._title = QLabel()
        self._title.setObjectName("reportPhrasesTitle")
        self._hint = QLabel()
        self._hint.setObjectName("reportPhrasesHint")

        header = QHBoxLayout()
        header.setContentsMargins(10, 8, 10, 2)
        header.setSpacing(6)
        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(self._hint)

        self._search = QLineEdit()
        self._search.setObjectName("reportPhrasesSearch")
        self._search.setClearButtonEnabled(True)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(10, 2, 10, 4)
        search_row.addWidget(self._search)

        self._add = self._link_button("reportPhrasesAdd")
        self._import = self._link_button("reportPhrasesImport")
        self._export = self._link_button("reportPhrasesExport")
        tools = QHBoxLayout()
        tools.setContentsMargins(10, 0, 10, 4)
        tools.setSpacing(8)
        tools.addWidget(self._add)
        tools.addStretch(1)
        tools.addWidget(self._import)
        tools.addWidget(self._export)

        self._status = QLabel()
        self._status.setObjectName("reportPhrasesStatus")
        self._status.setWordWrap(True)
        self._status.setVisible(False)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(10, 0, 10, 4)
        status_row.addWidget(self._status)

        self._host = QWidget()
        self._host.setObjectName("reportPhrasesHost")
        self._list = QVBoxLayout(self._host)
        self._list.setContentsMargins(8, 0, 8, 8)
        self._list.setSpacing(4)
        self._list.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("reportPhrasesScroll")
        scroll.viewport().setObjectName("reportPhrasesViewport")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._host)

        self._conclusion_label = QLabel()
        self._conclusion_label.setObjectName("reportConclusionLabel")
        self._editor = QPlainTextEdit()
        self._editor.setObjectName("reportConclusion")
        self._editor.setMinimumHeight(88)
        self._editor.setMaximumHeight(150)

        conclusion_box = QVBoxLayout()
        conclusion_box.setContentsMargins(10, 6, 10, 10)
        conclusion_box.setSpacing(4)
        conclusion_box.addWidget(self._conclusion_label)
        conclusion_box.addWidget(self._editor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addLayout(search_row)
        layout.addLayout(tools)
        layout.addLayout(status_row)
        layout.addWidget(scroll, 1)
        layout.addLayout(conclusion_box)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(_STATUS_TIMEOUT_MS)
        self._status_timer.timeout.connect(lambda: self._set_status(""))

        self._search.textChanged.connect(lambda _text: self._rebuild())
        self._add.clicked.connect(self._on_add_phrase)
        self._import.clicked.connect(self._on_import)
        self._export.clicked.connect(self._on_export)
        self._editor.textChanged.connect(self._on_editor_changed)

        self.reload_text()
        self.apply_theme()

    # ── state ────────────────────────────────────────────────────────

    @property
    def phrases(self) -> tuple[ReportPhrase, ...]:
        """Built-in and user phrases currently in the library."""
        return self._phrases

    @property
    def conclusion(self) -> str:
        return self._conclusion

    @property
    def store(self) -> PhraseStore:
        return self._store

    def set_conclusion(self, text: str) -> None:
        """Show a conclusion draft without emitting ``conclusion_changed``.

        The window calls this when the active tab changes, so a tab switch
        restores its own draft and cannot echo it back as an edit.
        """
        value = text or ""
        if value == self._conclusion and self._editor.toPlainText() == value:
            return
        self._editor.blockSignals(True)
        self._editor.setPlainText(value)
        self._editor.blockSignals(False)
        self._editor.moveCursor(QTextCursor.MoveOperation.End)
        self._conclusion = value
        self._refresh_marks()

    def inserted_ids(self) -> frozenset[str]:
        """Ids of the phrases the conclusion already contains."""
        return inserted_phrase_ids(self._phrases, self._conclusion, get_language())

    # ── insertion ────────────────────────────────────────────────────

    def set_read_only(self, read_only: bool) -> None:
        """A finished version accepts no edits; a new draft unlocks it (UQ-07).

        The conclusion stays selectable and copyable — only the writing is
        closed, so the physician can still read and print the version.
        """
        self._read_only = bool(read_only)
        self._editor.setReadOnly(self._read_only)

    @property
    def is_read_only(self) -> bool:
        return self._read_only

    def insert_phrase(self, phrase: ReportPhrase) -> None:
        """Insert one phrase at the cursor (or replace the selection)."""
        if self._read_only:
            return
        text = phrase.text(get_language())
        if not text:
            return
        editor = self._editor
        cursor = editor.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        full = editor.toPlainText()
        segment = insertion_segment(full[:start], full[end:], text)
        if not segment:
            return
        cursor.beginEditBlock()
        if cursor.hasSelection():
            cursor.removeSelectedText()
        cursor.insertText(segment)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)
        editor.setFocus()

    # ── editing the library ─────────────────────────────────────────

    def add_user_phrase(self, section: object, ru: object, en: object) -> ReportPhrase | None:
        """Validate, deduplicate and store a phrase; report the outcome."""
        phrase = make_user_phrase(section, ru, en)
        if phrase is None:
            return None
        if any(phrases_match(existing, phrase) for existing in self._phrases):
            self._set_status(tr("report.phrases_duplicate"))
            return None
        try:
            added = self._store.add(section, ru, en)
        except OSError:
            logger.exception("report phrases: cannot save the new phrase")
            self._set_status(tr("report.phrases_save_failed"))
            return None
        if added is None:
            self._set_status(tr("report.phrases_user_limit", limit=MAX_USER_PHRASES))
            return None
        self._reload_library()
        self._set_status(tr("report.phrases_added"))
        return added

    def remove_user_phrase(self, phrase_id: str) -> bool:
        """Delete a user phrase from the store and the list."""
        try:
            removed = self._store.remove(phrase_id)
        except OSError:
            logger.exception("report phrases: cannot delete the phrase")
            self._set_status(tr("report.phrases_save_failed"))
            return False
        if removed:
            self._reload_library()
        return removed

    # ── import / export ─────────────────────────────────────────────

    def import_phrases(self, path: Path) -> ImportResult | None:
        """Merge another library; ``None`` when the file cannot be used."""
        try:
            result = self._store.import_file(Path(path))
        except PhraseDocumentError:
            logger.warning("report phrases: %s is not a phrase document", path)
            self._set_status(tr("report.phrases_import_failed"))
            return None
        except OSError:
            logger.exception("report phrases: cannot read %s", path)
            self._set_status(tr("report.phrases_import_failed"))
            return None
        if result.added:
            self._reload_library()
        self._set_status(
            tr(
                "report.phrases_import_result",
                added=result.added,
                duplicates=result.duplicates,
                skipped=result.skipped,
            )
        )
        return result

    def export_phrases(self, path: Path) -> int | None:
        """Write the user library; ``None`` when the file cannot be written."""
        try:
            count = self._store.export_file(Path(path))
        except OSError:
            logger.exception("report phrases: cannot write %s", path)
            self._set_status(tr("report.phrases_export_failed"))
            return None
        self._set_status(tr("report.phrases_export_done", count=count))
        return count

    def _on_import(self) -> None:
        path, _ = styled_open_file(
            self,
            tr("report.phrases_import_title"),
            str(self._store.path.parent),
            tr("report.phrases_file_filter"),
        )
        if path:
            self.import_phrases(Path(path))

    def _on_export(self) -> None:
        path, _ = styled_save_file(
            self,
            tr("report.phrases_export_title"),
            str(self._store.path),
            tr("report.phrases_file_filter"),
        )
        if path:
            self.export_phrases(Path(path))

    def _on_add_phrase(self) -> None:
        dialog = PhraseEditorDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.add_user_phrase(*dialog.values())

    # ── view ─────────────────────────────────────────────────────────

    def _link_button(self, object_name: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName(object_name)
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _reload_library(self, *, rebuild: bool = True) -> None:
        user = self._store.phrases()
        known = {(normalize_for_search(phrase.ru), normalize_for_search(phrase.en)) for phrase in PHRASES}
        merged = tuple(PHRASES) + tuple(
            phrase for phrase in user if (normalize_for_search(phrase.ru), normalize_for_search(phrase.en)) not in known
        )
        self._phrases = merged
        self._phrase_by_id = {phrase.id: phrase for phrase in merged}
        if rebuild:
            self._rebuild()

    def _rebuild(self) -> None:
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._labels.clear()

        groups = phrase_groups(self._phrases, get_language(), self._search.text())
        if not groups:
            empty = QLabel(tr("report.phrases_empty"))
            empty.setObjectName("reportPhrasesEmpty")
            empty.setWordWrap(True)
            self._list.insertWidget(self._list.count() - 1, empty)
        for group in groups:
            header = QLabel(group.title)
            header.setObjectName("reportPhraseGroup")
            self._list.insertWidget(self._list.count() - 1, header)
            for phrase in group.phrases:
                self._list.insertWidget(self._list.count() - 1, self._phrase_row(phrase))
        self._refresh_marks()

    def _phrase_row(self, phrase: ReportPhrase) -> QWidget:
        row = QWidget()
        row.setObjectName("reportPhraseRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        label = _PhraseLabel(phrase.text(get_language()))
        label.setProperty("phraseId", phrase.id)
        label.setProperty("builtin", phrase.builtin)
        label.setProperty("inserted", False)
        label.activated.connect(lambda p=phrase: self.insert_phrase(p))
        layout.addWidget(label, 1)
        self._labels[phrase.id] = label

        if not phrase.builtin:
            delete = QPushButton("×")
            delete.setObjectName("reportPhraseDelete")
            delete.setFlat(True)
            delete.setFixedWidth(18)
            delete.setCursor(Qt.CursorShape.PointingHandCursor)
            delete.setToolTip(tr("report.phrases_delete_hint"))
            delete.clicked.connect(lambda _checked=False, phrase_id=phrase.id: self._delete(phrase_id))
            layout.addWidget(delete, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _delete(self, phrase_id: str) -> None:
        self.remove_user_phrase(phrase_id)

    def _refresh_marks(self) -> None:
        language = get_language()
        inserted = inserted_phrase_ids(self._phrases, self._conclusion, language)
        for phrase_id, label in self._labels.items():
            phrase = self._phrase_by_id.get(phrase_id)
            if phrase is None:
                continue
            marked = phrase_id in inserted
            label.setText(("✓ " if marked else "") + phrase.text(language))
            if bool(label.property("inserted")) != marked:
                label.setProperty("inserted", marked)
                style = label.style()
                style.unpolish(label)
                style.polish(label)
                label.update()

    def _on_editor_changed(self) -> None:
        self._conclusion = self._editor.toPlainText()
        self._refresh_marks()
        self.conclusion_changed.emit(self._conclusion)

    def _set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))
        if text:
            self._status_timer.start()
        else:
            self._status_timer.stop()

    # ── language and theme ───────────────────────────────────────────

    def reload_text(self) -> None:
        """Re-localize the column and rebuild the grouped list in the new language."""
        self._title.setText(tr("report.phrases"))
        self._hint.setText(tr("report.phrases_hint"))
        self._search.setPlaceholderText(tr("report.phrases_search"))
        self._add.setText(tr("report.phrases_add"))
        self._add.setToolTip(tr("report.phrases_add_hint"))
        self._import.setText(tr("report.phrases_import"))
        self._export.setText(tr("report.phrases_export"))
        self._conclusion_label.setText(tr("report.conclusion"))
        self._editor.setPlaceholderText(tr("report.conclusion_hint"))
        self._set_status("")
        self._rebuild()

    def apply_theme(self) -> None:
        """Paint the column from the tokens of the active theme."""
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"""
            #reportPhrases {{
                background: {tokens["surface.2"]};
                border-left: 1px solid {tokens["line.1"]};
            }}
            #reportPhrasesTitle {{
                color: {tokens["text.3"]};
                font-weight: 600;
            }}
            #reportPhrasesHint {{
                color: {tokens["text.3"]};
            }}
            #reportPhrasesHost, #reportPhrasesScroll, #reportPhrasesViewport {{
                background: {tokens["surface.2"]};
            }}
            #reportPhraseGroup {{
                color: {tokens["text.3"]};
                font-weight: 600;
                padding: 8px 2px 2px 2px;
            }}
            #reportPhrase {{
                color: {tokens["text.1"]};
                background: {tokens["surface.1"]};
                border: 1px solid {tokens["line.1"]};
                border-radius: 6px;
                padding: 6px 8px;
            }}
            #reportPhrase:hover {{
                border-color: {tokens["accent.tab"]};
            }}
            #reportPhrase:focus {{
                border-color: {tokens["accent.tab"]};
            }}
            #reportPhrase[inserted="true"] {{
                border-color: {tokens["state.ok"]};
                color: {tokens["text.1"]};
            }}
            #reportPhraseRow {{
                background: transparent;
            }}
            #reportPhraseDelete {{
                color: {tokens["text.3"]};
                border: none;
                padding: 0;
                font-weight: 600;
            }}
            #reportPhraseDelete:hover {{
                color: {tokens["state.err"]};
            }}
            #reportPhrasesAdd, #reportPhrasesImport, #reportPhrasesExport {{
                color: {tokens["accent.text"]};
                border: none;
                padding: 0 2px;
            }}
            #reportPhrasesAdd:hover, #reportPhrasesImport:hover, #reportPhrasesExport:hover {{
                text-decoration: underline;
            }}
            #reportPhrasesStatus {{
                color: {tokens["text.2"]};
            }}
            #reportPhrasesEmpty {{
                color: {tokens["text.3"]};
                font-style: italic;
                padding: 8px 2px;
            }}
            #reportConclusionLabel {{
                color: {tokens["text.3"]};
                font-weight: 600;
            }}
            #reportConclusion {{
                color: {tokens["text.1"]};
                background: {tokens["surface.0"]};
                border: 1px solid {tokens["line.1"]};
                border-radius: 6px;
                padding: 4px;
            }}
            """
        )


__all__ = ["PhraseEditorDialog", "ReportPhrasesPanel"]
