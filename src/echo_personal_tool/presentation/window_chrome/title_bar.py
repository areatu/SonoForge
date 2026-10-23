"""Windows 11-style window title bar: app menu, study tabs, command field, controls.

UI-1 PR-2 (spec §4.1, §4.3, §4.5, §9, §11 — UA-19). One 38 px row carries what
used to be two rows plus the window buttons of the system bar:

* the logo doubles as the application menu (settings, layout, help, about, quit);
* the study tabs — the existing :class:`~echo_personal_tool.presentation.tab_bar.TabStrip`
  is *adopted*, not re-created, so its identity, drag-reorder and context menu
  keep working;
* the «+» button is a control of the *title bar*: the strip itself stays
  tab-only (``tabStripNew`` remains absent, as Э9 requires);
* the command field («Команда, измерение, клип…») is focused with Ctrl+K; the
  command palette of TP-6 replaces its behaviour, the field is the contract;
* the window controls are 46 px wide and reach the top-right corner of the
  screen (Fitts), like the caption buttons of a native Windows 11 window.

The legacy stylesheet is pinned byte for byte by ``tests/fixtures/ui/stylesheet_*.golden.txt``
(the UI-0 gate), so the bar paints itself from semantic tokens through a scoped
stylesheet of its own; no rule of the shared sheet changes with this PR.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, QStringListModel, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCompleter,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from echo_personal_tool.presentation.ui_metrics import control_height, line_height, title_bar_height
from echo_personal_tool.presentation.window_chrome.caption_drag import CaptionDragMixin
from echo_personal_tool.presentation.window_chrome.hit_test import Zone

#: Height of the caption row at 100 % (spec §4.1); it grows with the UI font.
TITLE_BAR_HEIGHT_PX = 38
#: Width of one window control: «свернуть / развернуть / закрыть» по 46 px (spec §4.1).
WINDOW_CONTROL_WIDTH_PX = 46
#: The command field never takes the whole row: tabs keep their room (mockup 01).
COMMAND_FIELD_MIN_WIDTH_PX = 240
COMMAND_FIELD_MAX_WIDTH_PX = 420

_ICON_DIR = Path(__file__).resolve().parent.parent.parent / "resources" / "icons"


def _icon_dir() -> Path:
    import sys

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        return Path(meipass) / "echo_personal_tool" / "resources" / "icons"
    return _ICON_DIR


def load_icon(name: str) -> QIcon:
    """Load a bundled glyph tinted with ``text.1`` of the active theme."""
    from echo_personal_tool.presentation.dark_theme import get_theme_tokens

    svg_path = _icon_dir() / f"{name}.svg"
    if svg_path.is_file():
        svg_text = svg_path.read_text(encoding="utf-8")
        svg_text = svg_text.replace("currentColor", get_theme_tokens()["text.1"])
        pixmap = QPixmap()
        pixmap.loadFromData(svg_text.encode("utf-8"))
        if not pixmap.isNull():
            return QIcon(pixmap)
    return QIcon()


class WindowTitleBar(CaptionDragMixin, QWidget):
    """The caption row of the main window (spec §4.1)."""

    command_text_changed = Signal(str)
    command_submitted = Signal(str)
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from echo_personal_tool.infrastructure.i18n import tr

        self.setObjectName("windowTitleBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._tab_strip: QWidget | None = None
        self._menu: QMenu | None = None

        self._app_button = QToolButton(self)
        self._app_button.setObjectName("appMenuButton")
        self._app_button.setAutoRaise(True)
        self._app_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._app_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._app_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._app_button.setToolTip(tr("title_bar.app_menu_tooltip"))

        self._command_edit = QLineEdit(self)
        self._command_edit.setObjectName("commandField")
        self._command_edit.setPlaceholderText(tr("title_bar.command_placeholder"))
        self._command_edit.setClearButtonEnabled(True)
        self._command_edit.setMinimumWidth(COMMAND_FIELD_MIN_WIDTH_PX)
        self._command_edit.setMaximumWidth(COMMAND_FIELD_MAX_WIDTH_PX)
        self._command_edit.textChanged.connect(self.command_text_changed.emit)
        self._command_edit.returnPressed.connect(self._emit_command)
        self._search_action = self._command_edit.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition)
        self._command_completer = QCompleter(QStringListModel([], self), self._command_edit)
        self._command_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._command_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._command_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._command_edit.setCompleter(self._command_completer)
        self._command_edit.installEventFilter(self)

        self._btn_minimize = self._window_control_button("minimizeButton", tr("system_bar.minimize"))
        self._btn_minimize.clicked.connect(self.minimize_requested.emit)
        self._btn_maximize = self._window_control_button("maximizeButton", tr("system_bar.maximize"))
        self._btn_maximize.clicked.connect(self.maximize_requested.emit)
        self._btn_close = self._window_control_button("closeButton", tr("system_bar.close"))
        self._btn_close.clicked.connect(self.close_requested.emit)

        self._window_controls = QWidget(self)
        self._window_controls.setObjectName("windowControls")
        self._window_controls.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        controls_layout = QHBoxLayout(self._window_controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(0)
        for button in (self._btn_minimize, self._btn_maximize, self._btn_close):
            controls_layout.addWidget(button)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._app_button, 0)
        # Stretch of the tab area is deliberately zero: the tabs stay next to
        # the logo, the free space sits between them and the command field.  The
        # «+» of a new tab is gone: it was never added to this layout, so it sat
        # at (0, 0) of the caption and covered the logo/menu button (UI
        # acceptance 2026-10-23, item 7).  A new tab is Ctrl+T / ⌘T.
        self._content_layout = layout
        self._content_index = layout.count()
        layout.addStretch(1)
        layout.addWidget(self._command_edit, 0)
        layout.addWidget(self._window_controls, 0)

        self.reload_icons()
        self.update_control_height()

    # ----- construction helpers -------------------------------------------

    def _window_control_button(self, object_name: str, tooltip: str) -> QPushButton:
        button = QPushButton(self)
        button.setObjectName(object_name)
        button.setToolTip(tooltip)
        button.setFlat(True)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return button

    # ----- content ---------------------------------------------------------

    def adopt_tab_strip(self, strip: QWidget) -> None:
        """Take ownership of the study tab strip (it is moved, never rebuilt).

        The strip is re-measured against this row, so its tabs take the height
        of a caption control instead of the height of a full-width row.
        """
        self._tab_strip = strip
        strip.setParent(self)
        self._content_layout.insertWidget(self._content_index, strip, 0)
        updater = getattr(strip, "update_control_height", None)
        if callable(updater):
            updater(self)

    @property
    def tab_strip(self) -> QWidget | None:
        return self._tab_strip

    def set_app_menu(self, menu: QMenu | None) -> None:
        """Attach the application menu to the logo button."""
        self._menu = menu
        self._app_button.setMenu(menu)

    @property
    def app_button(self) -> QToolButton:
        return self._app_button

    @property
    def command_field(self) -> QLineEdit:
        return self._command_edit

    def set_tabs_visible(self, visible: bool) -> None:
        """Show/hide the tab strip of the caption."""
        if self._tab_strip is not None:
            self._tab_strip.setVisible(visible)

    def set_command_choices(self, labels: Iterable[str]) -> None:
        """Feed the completion model of the command field (discovery until TP-6)."""
        model = self._command_completer.model()
        if isinstance(model, QStringListModel):
            model.setStringList(list(labels))

    def command_text(self) -> str:
        return self._command_edit.text()

    def set_command_text(self, text: str) -> None:
        self._command_edit.setText(text)

    def focus_command_field(self) -> None:
        """Focus the legacy inline command field when requested directly."""
        self._command_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._command_edit.selectAll()

    def _emit_command(self) -> None:
        self.command_submitted.emit(self._command_edit.text().strip())

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001 - QEvent
        """Escape in the command field returns the keyboard to the viewer."""
        if watched is self._command_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._command_edit.clear()
                self._command_edit.clearFocus()
                return True
        return super().eventFilter(watched, event)

    # ----- geometry --------------------------------------------------------

    def _control_button_height(self) -> int:
        return max(self.height(), TITLE_BAR_HEIGHT_PX) - 1

    def update_control_height(self) -> None:
        """Re-measure the row and its controls after a font or scale change (Э4)."""
        self.ensurePolished()
        height = max(TITLE_BAR_HEIGHT_PX, title_bar_height(self, padding=18, minimum=TITLE_BAR_HEIGHT_PX))
        self.setFixedHeight(height)
        controls_height = self._control_button_height()
        for button in (self._btn_minimize, self._btn_maximize, self._btn_close):
            button.setFixedSize(WINDOW_CONTROL_WIDTH_PX, controls_height)
        self._command_edit.setFixedHeight(control_height(self, padding=8, minimum=24))
        icon_side = max(10, min(16, line_height(self) - 4))
        self._app_button.setIconSize(QSize(icon_side + 4, icon_side + 4))
        self._btn_minimize.setIconSize(QSize(icon_side, icon_side))
        self._btn_maximize.setIconSize(QSize(icon_side, icon_side))
        self._btn_close.setIconSize(QSize(icon_side, icon_side))
        if self._tab_strip is not None:
            self._tab_strip.update_control_height(self)
        self.apply_theme()

    def caption_buttons(self) -> Mapping[Zone, QWidget | None]:
        """Window controls of this row for the hit-test (spec §8.3, UA-01)."""
        return {
            Zone.MIN: self._btn_minimize,
            Zone.MAX: self._btn_maximize,
            Zone.CLOSE: self._btn_close,
        }

    def window_controls_visible(self) -> bool:
        """True when the custom window controls are shown (false with the OS frame)."""
        return not self._window_controls.isHidden()

    def set_window_controls_visible(self, visible: bool) -> None:
        """Hide the custom controls when the fallback OS window frame is on (UA-20)."""
        self._window_controls.setVisible(visible)

    def _caption_double_clicked(self) -> None:
        self.maximize_requested.emit()

    # ----- theme and text --------------------------------------------------

    def apply_theme(self) -> None:
        """Paint the row from semantic tokens (no rule of the shared sheet changes)."""
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        tokens = get_theme_tokens()
        controls_height = self._control_button_height()
        self.setStyleSheet(
            f"""
#windowTitleBar {{
    background: {tokens["surface.1"]};
    border-bottom: 1px solid {tokens["line.1"]};
}}
#windowTitleBar QToolButton#appMenuButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 3px;
}}
#windowTitleBar QToolButton#appMenuButton:hover,
#windowTitleBar QToolButton#appMenuButton:focus,
#windowTitleBar QToolButton#appMenuButton:pressed {{
    background: {tokens["surface.3"]};
    border-color: {tokens["line.1"]};
}}
/* The logo is the menu: a separate arrow would only add noise (mockup 01). */
#windowTitleBar QToolButton#appMenuButton::menu-indicator {{
    image: none;
    width: 0;
    height: 0;
}}
#windowTitleBar QLineEdit#commandField {{
    background: {tokens["surface.2"]};
    color: {tokens["text.1"]};
    border: 1px solid {tokens["line.1"]};
    border-radius: 6px;
    padding: 2px 8px;
    selection-background-color: {tokens["accent"]};
    selection-color: {tokens["accent.on"]};
}}
#windowTitleBar QLineEdit#commandField:focus {{
    border-color: {tokens["accent"]};
}}
#windowTitleBar QWidget#windowControls {{
    background: transparent;
}}
#windowTitleBar #windowControls QPushButton {{
    min-width: {WINDOW_CONTROL_WIDTH_PX}px;
    max-width: {WINDOW_CONTROL_WIDTH_PX}px;
    min-height: {controls_height}px;
    max-height: {controls_height}px;
    border: none;
    border-radius: 0;
    background: transparent;
    padding: 0;
}}
#windowTitleBar #windowControls QPushButton:hover,
#windowTitleBar #windowControls QPushButton:focus {{
    background: {tokens["surface.3"]};
}}
#windowTitleBar #windowControls QPushButton#closeButton:hover,
#windowTitleBar #windowControls QPushButton#closeButton:focus {{
    background: {tokens["state.danger.solid"]};
    color: {tokens["state.danger.on"]};
}}
"""
        )

    def reload_icons(self) -> None:
        """Re-read every glyph with the ``text.1`` of the active theme."""
        from echo_personal_tool.presentation.dark_theme import get_logo_path

        logo = get_logo_path()
        if logo.exists():
            pixmap = QPixmap(str(logo))
            self._app_button.setIcon(QIcon(pixmap))
            self._app_button.setText("")
        else:  # a broken installation must still show a usable menu button
            self._app_button.setIcon(QIcon())
            self._app_button.setText("SonoForge")
            self._app_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._search_action.setIcon(load_icon("search"))
        self._btn_minimize.setIcon(load_icon("minimize"))
        self.update_maximize_button(False)
        self._btn_close.setIcon(load_icon("close"))

    def reload_text(self) -> None:
        """Re-read every label and tooltip for the active language."""
        from echo_personal_tool.infrastructure.i18n import tr

        self._app_button.setToolTip(tr("title_bar.app_menu_tooltip"))
        self._command_edit.setPlaceholderText(tr("title_bar.command_placeholder"))
        self._btn_minimize.setToolTip(tr("system_bar.minimize"))
        self._btn_close.setToolTip(tr("system_bar.close"))
        self.update_maximize_button(bool(self._btn_maximize.property("windowMaximized")))

    def update_maximize_button(self, is_maximized: bool) -> None:
        """Switch the «развернуть» glyph and tooltip to «восстановить»."""
        from echo_personal_tool.infrastructure.i18n import tr

        self._btn_maximize.setProperty("windowMaximized", bool(is_maximized))
        if is_maximized:
            self._btn_maximize.setIcon(load_icon("restore"))
            self._btn_maximize.setToolTip(tr("system_bar.restore"))
        else:
            self._btn_maximize.setIcon(load_icon("maximize"))
            self._btn_maximize.setToolTip(tr("system_bar.maximize"))


__all__ = [
    "COMMAND_FIELD_MAX_WIDTH_PX",
    "COMMAND_FIELD_MIN_WIDTH_PX",
    "TITLE_BAR_HEIGHT_PX",
    "WINDOW_CONTROL_WIDTH_PX",
    "WindowTitleBar",
    "load_icon",
]
