"""Right-bottom panel: image list with drag-drop, zoom, and preview."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.constructor.editors.base_editor import BaseEditor
from echo_personal_tool.constructor.storage.image_storage import ImageStorage
from echo_personal_tool.presentation.echopac_theme import get_theme_palette


class ImageEditor(BaseEditor):
    """Right-bottom panel: reference images with drag-drop and preview."""

    images_changed = Signal()

    def __init__(
        self,
        image_storage: ImageStorage,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._image_storage = image_storage
        self._images: list[str] = []
        self._zoom = 1.0
        self._build_ui()
        self.setAcceptDrops(True)

    def _build_ui(self) -> None:
        p = get_theme_palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QLabel("Изображения")
        header.setStyleSheet(
            f"color: {p['text']}; font-weight: bold; padding: 8px 12px; "
            f"background: {p['bg_control']}; border-bottom: 1px solid {p['border']};"
        )
        layout.addWidget(header)

        # Drop zone hint
        self._drop_hint = QLabel("Перетащите изображения сюда")
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_hint.setFixedHeight(40)
        self._drop_hint.setStyleSheet(
            f"color: {p['text_dim']}; border: 2px dashed {p['border']}; "
            f"margin: 4px 8px; border-radius: 4px;"
        )
        layout.addWidget(self._drop_hint)

        # Image list + preview split
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # List
        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.setStyleSheet(
            f"QListWidget {{ border: none; color: {p['text']}; background: {p['bg_panel']}; }}"
            f"QListWidget::item {{ padding: 4px 8px; border-bottom: 1px solid {p['border']}; }}"
            f"QListWidget::item:selected {{ background: {p['accent']}; color: white; }}"
            f"QListWidget::item:hover {{ background: {p['bg_button_hover']}; }}"
        )
        self._list.currentItemChanged.connect(self._on_item_changed)
        self._list.customContextMenuRequested.connect(self._context_menu)
        content_layout.addWidget(self._list, 1)

        # Preview
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(4, 4, 4, 4)

        # Zoom controls
        zoom_bar = QWidget()
        zoom_layout = QHBoxLayout(zoom_bar)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(4)

        self._zoom_combo = QComboBox()
        self._zoom_combo.addItems(["Fit", "50%", "100%", "200%", "400%"])
        self._zoom_combo.currentTextChanged.connect(self._on_zoom_changed)
        self._zoom_combo.setStyleSheet(
            f"QComboBox {{ color: {p['text']}; background: {p['bg_control']}; "
            f"border: 1px solid {p['border']}; padding: 2px 4px; }}"
        )
        zoom_layout.addWidget(self._zoom_combo)
        zoom_layout.addStretch()

        preview_layout.addWidget(zoom_bar)

        # Preview area
        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(True)
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview_scroll.setWidget(self._preview_label)
        preview_layout.addWidget(self._preview_scroll, 1)

        content_layout.addWidget(preview_widget, 2)

        layout.addWidget(content, 1)

    # ── Public API ──

    def set_images(self, images: list[str]) -> None:
        self._images = list(images)
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._list.clear()
        for img in self._images:
            item = QListWidgetItem(img)
            item.setData(Qt.ItemDataRole.UserRole, img)
            self._list.addItem(item)

    def _on_item_changed(self, current: QListWidgetItem | None, _prev: Any) -> None:
        if current:
            filename = current.data(Qt.ItemDataRole.UserRole)
            if filename:
                self._show_preview(filename)

    def _show_preview(self, filename: str) -> None:
        path = self._image_storage.resolve(filename)
        if path is None:
            self._preview_label.setText(f"Файл не найден: {filename}")
            return

        if path.suffix.lower() == ".svg":
            self._render_svg(path)
        else:
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    int(pixmap.width() * self._zoom),
                    int(pixmap.height() * self._zoom),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._preview_label.setPixmap(scaled)
            else:
                self._preview_label.setText(f"Не удалось загрузить: {filename}")

    def _render_svg(self, path: Path) -> None:
        try:
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtGui import QPainter

            renderer = QSvgRenderer(str(path))
            if renderer.isValid():
                size = renderer.defaultSize()
                scaled_size = size * self._zoom
                image = QImage(
                    int(scaled_size.width()),
                    int(scaled_size.height()),
                    QImage.Format.Format_ARGB32,
                )
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                renderer.render(painter)
                painter.end()
                self._preview_label.setPixmap(QPixmap.fromImage(image))
            else:
                self._preview_label.setText(f"Невалидный SVG: {path.name}")
        except Exception:
            self._preview_label.setText(f"Ошибка SVG: {path.name}")

    def _on_zoom_changed(self, text: str) -> None:
        zoom_map = {"Fit": 0.5, "50%": 0.5, "100%": 1.0, "200%": 2.0, "400%": 4.0}
        self._zoom = zoom_map.get(text, 1.0)
        current = self._list.currentItem()
        if current:
            filename = current.data(Qt.ItemDataRole.UserRole)
            if filename:
                self._show_preview(filename)

    # ── Drag & Drop ──

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drop_hint.setStyleSheet(
                f"color: {get_theme_palette()['accent']}; border: 2px dashed {get_theme_palette()['accent']}; "
                f"margin: 4px 8px; border-radius: 4px;"
            )

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._drop_hint.setStyleSheet(
            f"color: {get_theme_palette()['text_dim']}; border: 2px dashed {get_theme_palette()['border']}; "
            f"margin: 4px 8px; border-radius: 4px;"
        )

    def dropEvent(self, event: QDropEvent) -> None:
        self._drop_hint.setStyleSheet(
            f"color: {get_theme_palette()['text_dim']}; border: 2px dashed {get_theme_palette()['border']}; "
            f"margin: 4px 8px; border-radius: 4px;"
        )
        for url in event.mimeData().urls():
            file_path = Path(url.toLocalFile())
            if file_path.is_file():
                ext = file_path.suffix.lower()
                if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg"}:
                    filename = self._image_storage.copy(file_path)
                    if filename not in self._images:
                        self._images.append(filename)
                        self.images_changed.emit()
        self._refresh_list()

    # ── Context menu ──

    def _context_menu(self, pos: Any) -> None:
        p = get_theme_palette()
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ color: {p['text']}; background: {p['bg_control']}; border: 1px solid {p['border']}; }}"
            f"QMenu::item:selected {{ background: {p['accent']}; }}"
        )
        menu.addAction("Добавить изображение...", self._add_image)
        menu.addAction("Удалить выбранное", self._delete_image)
        menu.addAction("Открыть во внешнем просмотрщике", self._open_external)
        menu.exec(self._list.mapToGlobal(pos))

    def _add_image(self) -> None:
        from echo_personal_tool.constructor.dialogs import styled_open_files
        files = styled_open_files(
            self, "Добавить изображения", "",
            "Изображения (*.png *.jpg *.jpeg *.gif *.bmp *.svg)"
        )
        for f in files:
            filename = self._image_storage.copy(Path(f))
            if filename not in self._images:
                self._images.append(filename)
        self._refresh_list()
        self.images_changed.emit()

    def _delete_image(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        filename = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self,
            "Удалить изображение",
            f"Удалить «{filename}» из справочника?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._images.remove(filename)
            self._image_storage.delete(filename)
            self._refresh_list()
            self.images_changed.emit()

    def _open_external(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        filename = item.data(Qt.ItemDataRole.UserRole)
        path = self._image_storage.resolve(filename)
        if path:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def delete_selected(self) -> None:
        self._delete_image()
