"""Main 3-panel layout for the reference constructor."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.constructor.editors.image_editor import ImageEditor
from echo_personal_tool.constructor.editors.metadata_editor import MetadataEditor
from echo_personal_tool.constructor.editors.parameter_table_editor import (
    ParameterTableEditor,
)
from echo_personal_tool.constructor.editors.pathology_editor import PathologyEditor
from echo_personal_tool.constructor.editors.topic_editor import TopicEditor
from echo_personal_tool.constructor.models import ReferenceModel
from echo_personal_tool.constructor.storage import (
    ImageStorage,
    SchemaValidator,
    YamlStorage,
)
from echo_personal_tool.presentation.echopac_theme import get_theme_palette

logger = logging.getLogger(__name__)


class ConstructorWidget(QWidget):
    """3-panel reference constructor: topics | parameters | pathologies+images."""

    dirty_changed = Signal(bool)

    def __init__(
        self,
        yaml_storage: YamlStorage,
        validator: SchemaValidator,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._yaml_storage = yaml_storage
        self._validator = validator
        self._images_storage = ImageStorage(yaml_storage.path.parent / "images")
        self._current_pathology: PathologyModel | None = None

        # Load working copy
        raw = yaml_storage.load()
        self._model = ReferenceModel.from_dict(raw)
        self._saved_state = self._model.deep_copy()
        self._dirty = False

        self._build_ui()
        self._connect_signals()
        self._refresh_all()

    # ── UI ──

    def _build_ui(self) -> None:
        p = get_theme_palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Search bar
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("Поиск параметра, патологии, темы...")
        self._search_bar.setStyleSheet(
            f"QLineEdit {{ border: 1px solid {p['border']}; border-radius: 4px; "
            f"padding: 6px 10px; color: {p['text']}; background: {p['bg_control']}; font-size: 13px; }}"
            f"QLineEdit:focus {{ border: 1px solid {p['accent']}; }}"
        )
        layout.addWidget(self._search_bar)

        # 3-panel splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: topics
        self._topic_editor = TopicEditor()
        splitter.addWidget(self._topic_editor)

        # Center panel: parameter table
        self._param_table = ParameterTableEditor()
        splitter.addWidget(self._param_table)

        # Right panel: pathologies + images stacked
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._pathology_editor = PathologyEditor()
        right_layout.addWidget(self._pathology_editor, 2)

        self._image_editor = ImageEditor(self._images_storage)
        right_layout.addWidget(self._image_editor, 1)

        splitter.addWidget(right_widget)

        splitter.setSizes([200, 500, 300])
        layout.addWidget(splitter, 1)

        # Bottom bar: metadata
        self._metadata_editor = MetadataEditor()
        layout.addWidget(self._metadata_editor)

    # ── Signals ──

    def _connect_signals(self) -> None:
        self._topic_editor.topic_selected.connect(self._on_topic_selected)
        self._topic_editor.topics_changed.connect(self._mark_dirty)

        self._pathology_editor.pathology_selected.connect(self._on_pathology_selected)
        self._pathology_editor.pathologies_changed.connect(self._mark_dirty)

        self._param_table.parameters_changed.connect(self._mark_dirty)
        self._param_table.parameter_selected.connect(self._on_parameter_selected)

        self._image_editor.images_changed.connect(self._on_images_changed)
        self._metadata_editor.metadata_changed.connect(self._mark_dirty)

        self._search_bar.textChanged.connect(self._on_search)

    # ── Selection ──

    def _on_topic_selected(self, slug: str) -> None:
        topic = self._model.get_topic(slug)
        if topic:
            self._pathology_editor.set_pathologies(topic.pathologies)
            self._param_table.set_parameters([])
            self._image_editor.set_images([])

    def _on_pathology_selected(self, pathology_slug: str) -> None:
        # Find pathology across all topics
        for topic in self._model.topics:
            for patho in topic.pathologies:
                if patho.slug == pathology_slug:
                    self._current_pathology = patho
                    self._param_table.set_pathology(patho)
                    self._image_editor.set_images(patho.image_paths)
                    return
        self._current_pathology = None

    def _on_parameter_selected(self, param_id: str) -> None:
        result = self._model.find_parameter(param_id)
        if result:
            _, patho, param = result
            self._metadata_editor.set_parameter(param)

    def _on_images_changed(self) -> None:
        """Sync image list from editor back to pathology model."""
        if self._current_pathology is not None:
            self._current_pathology.image_paths = list(self._image_editor._images)
            self._mark_dirty()

    # ── Search ──

    def _on_search(self, query: str) -> None:
        if not query.strip():
            self._topic_editor.clear_filter()
            self._pathology_editor.clear_filter()
            self._param_table.clear_filter()
            return

        q = query.lower()
        self._topic_editor.filter(q)
        self._pathology_editor.filter(q)
        self._param_table.filter(q)

    # ── Refresh ──

    def _refresh_all(self) -> None:
        self._topic_editor.set_topics(self._model.topics)
        self._param_table.set_parameters([])
        self._pathology_editor.set_pathologies([])
        self._image_editor.set_images([])

    # ── Dirty tracking ──

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.dirty_changed.emit(True)

    def _clear_dirty(self) -> None:
        self._dirty = False
        self.dirty_changed.emit(False)

    # ── Save / Undo ──

    def save(self) -> None:
        errors = self._validator.validate(self._model.to_dict())
        if errors:
            msg = "\n".join(str(e) for e in errors[:20])
            QMessageBox.warning(
                self,
                "Ошибки валидации",
                f"Найдено {len(errors)} ошибок:\n\n{msg}",
            )
            return
        self._yaml_storage.save(self._model.to_dict())
        self._saved_state = self._model.deep_copy()
        self._clear_dirty()

    def save_as(self, path: Path) -> None:
        errors = self._validator.validate(self._model.to_dict())
        if errors:
            msg = "\n".join(str(e) for e in errors[:20])
            QMessageBox.warning(self, "Ошибки валидации", f"{len(errors)} ошибок:\n{msg}")
            return
        storage = YamlStorage(path)
        storage.save(self._model.to_dict())
        self._yaml_path = path
        self._saved_state = self._model.deep_copy()
        self._clear_dirty()

    def undo(self) -> None:
        if not self._dirty:
            return
        reply = QMessageBox.question(
            self,
            "Отмена",
            "Отменить все изменения с момента последнего сохранения?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._model = self._saved_state.deep_copy()
            self._clear_dirty()
            self._refresh_all()

    # ── Delete selected ──

    def delete_selected(self) -> None:
        # Delegate to active editor
        focused = self.focusWidget()
        if hasattr(focused, "delete_selected"):
            focused.delete_selected()

    # ── Search focus ──

    def focus_search(self) -> None:
        self._search_bar.setFocus()
        self._search_bar.selectAll()

    # ── Import / Export ──

    def import_excel(self) -> None:
        from echo_personal_tool.constructor.dialogs import styled_open_file
        path, _ = styled_open_file(
            self, "Импорт Excel", "", "Excel (*.xlsx *.xls)"
        )
        if path:
            try:
                from echo_personal_tool.constructor.importers.excel_importer import (
                    import_excel_file,
                )
                imported = import_excel_file(Path(path))
                # Merge imported data into model
                for topic_data in imported.get("topics", []):
                    existing = self._model.get_topic(topic_data.get("slug", ""))
                    if existing:
                        for patho_data in topic_data.get("pathologies", []):
                            # Add pathology if not exists
                            pass  # TODO: implement merge logic
                self._mark_dirty()
            except Exception as exc:
                QMessageBox.critical(self, "Ошибка импорта", str(exc))

    def export_pdf(self) -> None:
        from echo_personal_tool.constructor.dialogs import styled_save_file
        path, _ = styled_save_file(
            self, "Экспорт PDF", "", "PDF (*.pdf)"
        )
        if path:
            try:
                from echo_personal_tool.constructor.exporters.pdf_exporter import (
                    export_to_pdf,
                )
                export_to_pdf(self._model, Path(path))
            except Exception as exc:
                QMessageBox.critical(self, "Ошибка экспорта", str(exc))

    def export_html(self) -> None:
        from echo_personal_tool.constructor.dialogs import styled_save_file
        path, _ = styled_save_file(
            self, "Экспорт HTML", "", "HTML (*.html)"
        )
        if path:
            try:
                from echo_personal_tool.constructor.exporters.html_exporter import (
                    export_to_html,
                )
                export_to_html(self._model, Path(path))
            except Exception as exc:
                QMessageBox.critical(self, "Ошибка экспорта", str(exc))

    # ── Preview ──

    def show_preview(self) -> None:
        from echo_personal_tool.constructor.preview.reference_preview import (
            ReferencePreviewWindow,
        )
        preview = ReferencePreviewWindow(self._model, self)
        preview.resize(900, 700)
        preview.show()

    # ── Validation ──

    def validate(self) -> None:
        errors = self._validator.validate(self._model.to_dict())
        if errors:
            msg = "\n".join(str(e) for e in errors)
            QMessageBox.warning(self, "Ошибки валидации", f"{len(errors)} ошибок:\n\n{msg}")
        else:
            QMessageBox.information(self, "Валидация", "Ошибок не найдено ✓")
