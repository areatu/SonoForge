"""Reference Constructor — visual editor dialog."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenuBar,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.constructor.constructor_widget import ConstructorWidget
from echo_personal_tool.constructor.storage import SchemaValidator, YamlStorage
from echo_personal_tool.presentation.echopac_theme import get_theme_palette
from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI

_YAML_PATH = Path(__file__).resolve().parents[2] / "echo_personal_tool" / "resources" / "references" / "references_structured.yaml"

logger = logging.getLogger(__name__)


def _load_icon(name: str) -> QPixmap:
    """Load SVG icon recolored to theme text."""
    from PySide6.QtGui import QIcon
    import sys
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        icon_dir = Path(meipass) / "echo_personal_tool" / "resources" / "icons"
    else:
        icon_dir = Path(__file__).resolve().parents[1] / "resources" / "icons"
    svg_path = icon_dir / f"{name}.svg"
    if svg_path.is_file():
        svg_text = svg_path.read_text(encoding="utf-8")
        color = get_theme_palette().get("text", "#f1f5f9")
        svg_text = svg_text.replace("currentColor", color)
        pixmap = QPixmap()
        pixmap.loadFromData(svg_text.encode("utf-8"))
        return pixmap
    return QPixmap()


def show_constructor_dialog(parent: QWidget | None = None) -> None:
    """Entry point: open the reference constructor."""
    try:
        dialog = ConstructorDialog(parent)
    except Exception as exc:
        QMessageBox.critical(
            parent,
            "Ошибка загрузки",
            f"Не удалось открыть конструктор:\n{exc}",
        )
        return
    dialog.exec()


class ConstructorDialog(QDialog):
    """Frameless maximizable dialog for the reference constructor."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Конструктор справочника")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(1200, 800)

        # Dragging state
        self._drag_pos: QPoint | None = None
        self._is_maximized = False
        self._normal_geometry: Any = None

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
        p = get_theme_palette()
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet(f"background: {p['bg_panel']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 4, 0)

        title = QLabel("Конструктор справочника")
        title.setStyleSheet(f"color: {p['text']}; font-weight: bold; font-size: 13px;")
        layout.addWidget(title)
        layout.addStretch(1)

        for text, slot, tip in [
            ("—", self._minimize, "Свернуть"),
            ("□", self._toggle_maximize, "Развернуть"),
            ("×", self._close, "Закрыть"),
        ]:
            btn = QPushButton(text)
            btn.setFixedSize(32, 28)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ border: none; color: {p['text']}; font-size: 14px; }}"
                f"QPushButton:hover {{ background: {p['bg_button_hover']}; }}"
            )
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
        p = get_theme_palette()
        menu_bar = QMenuBar()
        menu_bar.setStyleSheet(
            f"QMenuBar {{ background: {p['bg_panel']}; color: {p['text']}; }}"
            f"QMenuBar::item:selected {{ background: {p['bg_button_hover']}; }}"
        )

        file_menu = menu_bar.addMenu("Файл")
        file_menu.addAction("Сохранить", self._constructor_widget.save, "Ctrl+S")
        file_menu.addAction("Сохранить как...", self._save_as)
        file_menu.addSeparator()
        file_menu.addAction("Импорт Excel...", self._constructor_widget.import_excel)
        file_menu.addSeparator()
        file_menu.addAction("Экспорт PDF...", self._constructor_widget.export_pdf)
        file_menu.addAction("Экспорт HTML...", self._constructor_widget.export_html)
        file_menu.addSeparator()
        file_menu.addAction("Закрыть", self._close, "Ctrl+Q")

        edit_menu = menu_bar.addMenu("Правка")
        edit_menu.addAction("Отменить (к сохранению)", self._constructor_widget.undo, "Ctrl+Z")
        edit_menu.addSeparator()
        edit_menu.addAction("Найти...", self._constructor_widget.focus_search, "Ctrl+F")
        edit_menu.addSeparator()
        edit_menu.addAction("Удалить выбранные", self._constructor_widget.delete_selected, "Delete")

        view_menu = menu_bar.addMenu("Вид")
        view_menu.addAction("Preview", self._constructor_widget.show_preview, "Ctrl+P")
        view_menu.addSeparator()
        view_menu.addAction("Проверка целостности", self._constructor_widget.validate)

        return menu_bar

    # ── Toolbar ──

    def _build_toolbar(self) -> QWidget:
        p = get_theme_palette()
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet(f"background: {p['bg_control']}; border-bottom: 1px solid {p['border']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(4)

        for text, slot, tip in [
            ("💾 Сохранить", self._constructor_widget.save, "Ctrl+S"),
            ("👁 Preview", self._constructor_widget.show_preview, "Ctrl+P"),
            ("↩ Undo", self._constructor_widget.undo, "Ctrl+Z"),
            ("📥 Excel", self._constructor_widget.import_excel, ""),
            ("📤 PDF", self._constructor_widget.export_pdf, ""),
            ("📤 HTML", self._constructor_widget.export_html, ""),
            ("⚙ Validate", self._constructor_widget.validate, ""),
        ]:
            btn = QPushButton(text)
            if tip:
                btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ border: 1px solid {p['border']}; border-radius: 3px; "
                f"padding: 2px 8px; color: {p['text']}; background: {p['bg_panel']}; }}"
                f"QPushButton:hover {{ background: {p['bg_button_hover']}; }}"
                f"QPushButton:pressed {{ background: {p['bg_button_pressed']}; }}"
            )
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        layout.addStretch(1)

        # Dirty indicator
        self._dirty_label = QLabel("")
        self._dirty_label.setStyleSheet(f"color: {p['accent']}; font-weight: bold; font-size: 14px;")
        layout.addWidget(self._dirty_label)

        self._constructor_widget.dirty_changed.connect(self._on_dirty_changed)

        return bar

    def _on_dirty_changed(self, dirty: bool) -> None:
        self._dirty_label.setText("*" if dirty else "")

    def _save_as(self) -> None:
        from echo_personal_tool.constructor.dialogs import styled_save_file
        path, _ = styled_save_file(
            self, "Сохранить как", str(self._yaml_path), "YAML (*.yaml *.yml)"
        )
        if path:
            self._constructor_widget.save_as(Path(path))

    # ── Theme ──

    def _apply_theme(self) -> None:
        p = get_theme_palette()
        self.setStyleSheet(
            f"QDialog {{ background: {p['bg_panel']}; color: {p['text']}; }}"
            f"QSplitter::handle {{ background: {p['border']}; }}"
        )

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
        if self._constructor_widget._dirty:
            reply = QMessageBox.question(
                self,
                "Несохранённые изменения",
                "Есть несохранённые изменения. Сохранить перед закрытием?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._constructor_widget.save()
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        event.accept()
