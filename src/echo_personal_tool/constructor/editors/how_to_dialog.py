"""Dialog for authoring bilingual reference-card measurement instructions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.dark_theme import get_theme_palette

_LANGUAGES = ("ru", "en")


def _steps_for_language(value: object, language: str) -> list[str]:
    """Read one language from either the current or a legacy text shape."""
    if not isinstance(value, Mapping):
        return []
    raw_steps = value.get(language, [])
    if isinstance(raw_steps, str):
        raw_steps = [raw_steps]
    if not isinstance(raw_steps, Sequence):
        return []
    return [step.strip() for step in raw_steps if isinstance(step, str) and step.strip()]


class HowToDialog(QDialog):
    """Edit one instruction per line for each UI language.

    The output uses ``{"ru": [...], "en": [...]}``. A translation may be
    filled later; both locale keys are kept, and the reference card falls back
    to the available language until the second translation is added.
    """

    def __init__(self, how_to: Mapping[str, object] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("constructorHowToDialog")
        self.setWindowTitle(tr("constructor.meta.how_to_title"))
        self.setMinimumSize(520, 340)
        self.resize(640, 400)

        self._editors: dict[str, QPlainTextEdit] = {}
        self._build_ui(how_to or {})

    def _build_ui(self, how_to: Mapping[str, object]) -> None:
        palette = get_theme_palette()
        self.setStyleSheet(
            f"QDialog#constructorHowToDialog {{ background: {palette['bg_panel']}; }}"
            f"QLabel {{ color: {palette['text']}; }}"
            f"QPlainTextEdit {{ color: {palette['text']}; background: {palette['bg_control']}; "
            f"border: 1px solid {palette['border']}; padding: 6px; }}"
            f"QTabWidget::pane {{ border: 1px solid {palette['border']}; }}"
            f"QTabBar::tab {{ color: {palette['text']}; background: {palette['bg_control']}; "
            f"padding: 6px 12px; }}"
            f"QTabBar::tab:selected {{ background: {palette['accent_tab']}; }}"
            f"QPushButton {{ color: {palette['text']}; background: {palette['bg_control']}; "
            f"border: 1px solid {palette['border']}; padding: 4px 12px; }}"
            f"QPushButton:hover {{ background: {palette['bg_button_hover']}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        help_label = QLabel(tr("constructor.meta.how_to_help"), self)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        tabs = QTabWidget(self)
        tabs.setObjectName("constructorHowToTabs")
        for language, label_key in (
            ("ru", "constructor.meta.how_to_ru"),
            ("en", "constructor.meta.how_to_en"),
        ):
            editor = QPlainTextEdit(tabs)
            editor.setObjectName(f"constructorHowTo{language.upper()}Edit")
            editor.setPlaceholderText(tr("constructor.meta.how_to_placeholder"))
            editor.setPlainText("\n".join(_steps_for_language(how_to, language)))
            self._editors[language] = editor
            tabs.addTab(editor, tr(label_key))
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def how_to(self) -> dict[str, list[str]] | None:
        """Return normalized translations, or ``None`` when the field is cleared."""
        result = {
            language: [line.strip() for line in self._editors[language].toPlainText().splitlines() if line.strip()]
            for language in _LANGUAGES
        }
        return result if any(result.values()) else None
