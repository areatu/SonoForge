"""Reference Constructor — visual editor dialog."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.constructor.constructor_widget import ConstructorWidget
from echo_personal_tool.constructor.storage import SchemaValidator, YamlStorage
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.keyboard_shortcuts import bind_action_shortcut, shortcut_label
from echo_personal_tool.presentation.dark_theme import get_theme_palette

_YAML_PATH = (
    Path(__file__).resolve().parents[2]
    / "echo_personal_tool"
    / "resources"
    / "references"
    / "references_structured.yaml"
)

logger = logging.getLogger(__name__)


def _load_icon(name: str) -> QPixmap:
    """A bundled glyph recoloured to the theme text colour (see ``icon_loader``)."""
    from echo_personal_tool.presentation.icon_loader import load_svg_pixmap

    return load_svg_pixmap(name, color=get_theme_palette().get("text", "#f1f5f9"))


def show_constructor_dialog(parent: QWidget | None = None) -> None:
    """Entry point: open the reference constructor."""
    try:
        dialog = ConstructorDialog(parent)
    except Exception as exc:
        QMessageBox.critical(
            parent,
            tr("constructor.load_error"),
            tr("constructor.load_error_body", exc=str(exc)),
        )
        return
    dialog.exec()


class ConstructorDialog(QDialog):
    """Frameless maximizable dialog for the reference constructor."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("constructor.window_title"))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(1200, 800)

        # Dragging state
        self._drag_pos: QPoint | None = None
        self._is_maximized = False
        self._normal_geometry: Any = None
        self._skip_close_prompt = False

        # Storage
        self._yaml_path = _YAML_PATH
        self._yaml_storage = YamlStorage(self._yaml_path)
        self._validator = SchemaValidator()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        root.addWidget(self._build_title_bar())

        # Main content: 3-panel splitter (must be created before menu/toolbar)
        self._constructor_widget = ConstructorWidget(
            yaml_storage=self._yaml_storage,
            validator=self._validator,
        )

        # Menu bar
        root.addWidget(self._build_menu())

        # Toolbar
        root.addWidget(self._build_toolbar())

        root.addWidget(self._constructor_widget, 1)

        self._apply_theme()

    # ── Title bar ──

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("constructorTitleBar")
        bar.setFixedHeight(36)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 4, 0)

        title = QLabel(tr("constructor.window_title"))
        title.setObjectName("constructorTitleLabel")
        layout.addWidget(title)
        layout.addStretch(1)

        for text, slot, tip in [
            ("—", self._minimize, tr("constructor.minimize")),
            ("□", self._toggle_maximize, tr("constructor.maximize")),
            ("×", self._close, tr("constructor.close")),
        ]:
            btn = QPushButton(text)
            btn.setObjectName("windowButton")
            btn.setFixedSize(32, 28)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        return bar

    def _minimize(self) -> None:
        self.showMinimized()

    def _toggle_maximize(self) -> None:
        if self._is_maximized:
            self.showNormal()
            if self._normal_geometry:
                self.setGeometry(self._normal_geometry)
            self._is_maximized = False
        else:
            self._normal_geometry = self.geometry()
            self.showMaximized()
            self._is_maximized = True

    def _close(self) -> None:
        self.close()

    # ── Menu bar ──

    def _build_menu(self) -> QMenuBar:
        menu_bar = QMenuBar()

        def bound(menu, text, handler, shortcut_id):
            action = menu.addAction(text, handler)
            bind_action_shortcut(action, shortcut_id)
            return action

        file_menu = menu_bar.addMenu(tr("constructor.file_menu"))
        bound(file_menu, tr("constructor.file_menu.save"), self._constructor_widget.save, "constructor_save")
        file_menu.addAction(tr("constructor.file_menu.save_as"), self._save_as)
        file_menu.addSeparator()
        file_menu.addAction(tr("constructor.file_menu.import_excel"), self._constructor_widget.import_excel)
        file_menu.addSeparator()
        file_menu.addAction(tr("constructor.file_menu.export_pdf"), self._constructor_widget.export_pdf)
        file_menu.addAction(tr("constructor.file_menu.export_html"), self._constructor_widget.export_html)
        file_menu.addSeparator()
        bound(file_menu, tr("constructor.file_menu.close"), self._close, "constructor_close")

        edit_menu = menu_bar.addMenu(tr("constructor.edit_menu"))
        bound(edit_menu, tr("constructor.edit_menu.undo"), self._constructor_widget.undo, "constructor_undo")
        edit_menu.addSeparator()
        bound(edit_menu, tr("constructor.edit_menu.find"), self._constructor_widget.focus_search, "constructor_find")
        edit_menu.addSeparator()
        bound(
            edit_menu,
            tr("constructor.edit_menu.delete"),
            self._constructor_widget.delete_selected,
            "constructor_delete",
        )

        view_menu = menu_bar.addMenu(tr("constructor.view_menu"))
        bound(view_menu, "Preview", self._constructor_widget.show_preview, "constructor_preview")
        view_menu.addSeparator()
        view_menu.addAction(tr("constructor.view_menu.validate"), self._constructor_widget.validate)
        return menu_bar

    # ── Toolbar ──

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("constructorToolbar")
        bar.setFixedHeight(36)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(4)

        for text, slot, tip in [
            (tr("constructor.save_button"), self._constructor_widget.save, shortcut_label("constructor_save")),
            ("👁 Preview", self._constructor_widget.show_preview, shortcut_label("constructor_preview")),
            ("↩ Undo", self._constructor_widget.undo, shortcut_label("constructor_undo")),
            ("📥 Excel", self._constructor_widget.import_excel, ""),
            ("📤 PDF", self._constructor_widget.export_pdf, ""),
            ("📤 HTML", self._constructor_widget.export_html, ""),
            ("⚙ Validate", self._constructor_widget.validate, ""),
        ]:
            btn = QPushButton(text)
            if tip:
                btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        layout.addStretch(1)

        # Dirty indicator
        self._dirty_label = QLabel("")
        self._dirty_label.setObjectName("constructorDirtyLabel")
        layout.addWidget(self._dirty_label)

        self._constructor_widget.dirty_changed.connect(self._on_dirty_changed)

        return bar

    def _on_dirty_changed(self, dirty: bool) -> None:
        self._dirty_label.setText("*" if dirty else "")

    def _save_as(self) -> None:
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        path, _ = styled_save_file(self, tr("constructor.save_as_title"), str(self._yaml_path), "YAML (*.yaml *.yml)")
        if path:
            self._constructor_widget.save_as(Path(path))

    # ── Theme ──

    def _apply_theme(self) -> None:
        pass

    # ── Drag support ──

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            title_bar = self.findChild(QWidget)
            if title_bar and title_bar.geometry().contains(event.pos()):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._toggle_maximize()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Prevent Enter/Return from triggering dialog default button
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            focused = self.focusWidget()
            if isinstance(focused, (QLineEdit, QSpinBox)):
                # Let QLineEdit/QSpinBox handle Enter naturally
                super().keyPressEvent(event)
                return
            # Otherwise ignore Enter to prevent dialog minimize/close
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._skip_close_prompt:
            event.accept()
            return
        if self._constructor_widget._dirty:
            reply = QMessageBox.question(
                self,
                tr("constructor.unsaved_title"),
                tr("constructor.unsaved_body"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._constructor_widget.save()
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        event.accept()
