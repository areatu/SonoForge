"""Editor of the printable form of the protocol (item 12 of the list).

The owner prints the sheet of his clinic: a header field the study does not
use should not take a line, the fields he does use should print in his order,
and a long protocol should fit two columns rather than three pages.

The widget is deliberately not a layout designer.  What it edits is the small
versioned :class:`~echo_personal_tool.domain.services.report_template.ReportTemplate`
— the ordered field list, three visibility switches and the column count — so
``«бланк»`` means «the same sheet, arranged my way», not «a document that may
print anything».  Import and export move that template between computers as a
JSON file; an unreadable file is reported and changes nothing.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.services.report_template import (
    COLUMNS_TWO,
    FIELD_LABEL_KEYS,
    ReportTemplate,
    default_template,
    encode_template,
    read_template_document,
)


class ReportTemplateEditor(QWidget):
    """Ordered header fields, three switches, columns, import and export."""

    changed = Signal()

    def __init__(self, template: ReportTemplate | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reportTemplateEditor")
        self._template = template if template is not None else default_template()
        self._syncing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        fields_box = QGroupBox(tr("preferences.template_fields"))
        fields_layout = QVBoxLayout(fields_box)
        hint = QLabel(tr("preferences.template_fields_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("reportTemplateHint")
        fields_layout.addWidget(hint)
        self._fields = QListWidget()
        self._fields.setObjectName("reportTemplateFields")
        self._fields.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._fields.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._fields.currentRowChanged.connect(lambda _row: self._refresh_buttons())
        self._fields.model().rowsMoved.connect(lambda *_: self.commit_drag())
        fields_layout.addWidget(self._fields, 1)

        buttons = QHBoxLayout()
        self._up = QPushButton("↑")
        self._up.setObjectName("reportTemplateUp")
        self._up.setToolTip(tr("preferences.template_move_up"))
        self._up.clicked.connect(lambda: self._move(-1))
        self._down = QPushButton("↓")
        self._down.setObjectName("reportTemplateDown")
        self._down.setToolTip(tr("preferences.template_move_down"))
        self._down.clicked.connect(lambda: self._move(1))
        self._toggle = QPushButton(tr("preferences.template_toggle_field"))
        self._toggle.setObjectName("reportTemplateToggle")
        self._toggle.clicked.connect(self._toggle_selected)
        buttons.addWidget(self._up)
        buttons.addWidget(self._down)
        buttons.addWidget(self._toggle)
        buttons.addStretch(1)
        fields_layout.addLayout(buttons)
        root.addWidget(fields_box, 1)

        form = QFormLayout()
        self._columns = QComboBox()
        self._columns.setObjectName("reportTemplateColumns")
        self._columns.addItem(tr("preferences.template_one_column"), 1)
        self._columns.addItem(tr("preferences.template_two_columns"), COLUMNS_TWO)
        self._columns.currentIndexChanged.connect(self._collect)
        self._notes = QCheckBox(tr("preferences.template_show_notes"))
        self._notes.setObjectName("reportTemplateNotes")
        self._notes.toggled.connect(self._collect)
        self._conclusion = QCheckBox(tr("preferences.template_show_conclusion"))
        self._conclusion.setObjectName("reportTemplateConclusion")
        self._conclusion.toggled.connect(self._collect)
        self._signature = QCheckBox(tr("preferences.template_show_signature"))
        self._signature.setObjectName("reportTemplateSignature")
        self._signature.toggled.connect(self._collect)
        form.addRow(tr("preferences.template_columns"), self._columns)
        form.addRow("", self._notes)
        form.addRow("", self._conclusion)
        form.addRow("", self._signature)
        root.addLayout(form)

        transfer = QHBoxLayout()
        self._export = QPushButton(tr("preferences.template_export"))
        self._export.setObjectName("reportTemplateExport")
        self._export.clicked.connect(self._export_to_file)
        self._import = QPushButton(tr("preferences.template_import"))
        self._import.setObjectName("reportTemplateImport")
        self._import.clicked.connect(self._import_from_file)
        transfer.addWidget(self._export)
        transfer.addWidget(self._import)
        transfer.addStretch(1)
        root.addLayout(transfer)

        self.set_template(self._template)

    # ── state ────────────────────────────────────────────────────

    def template(self) -> ReportTemplate:
        return self._template

    def set_template(self, template: ReportTemplate | None) -> None:
        """Show *template* without emitting ``changed`` (loading a dialog)."""
        self._template = template if template is not None else default_template()
        self._syncing = True
        try:
            self._rebuild_fields()
            index = self._columns.findData(self._template.normalized_columns)
            self._columns.setCurrentIndex(max(0, index))
            self._notes.setChecked(self._template.show_notes)
            self._conclusion.setChecked(self._template.show_conclusion)
            self._signature.setChecked(self._template.show_signature)
        finally:
            self._syncing = False
        self._refresh_buttons()

    def _rebuild_fields(self) -> None:
        self._fields.clear()
        printed = set(self._template.header_fields)
        for field_id in self._template.header_fields:
            self._add_field_row(field_id, printed=True)
        for field_id in FIELD_LABEL_KEYS:
            if field_id not in printed:
                self._add_field_row(field_id, printed=False)

    def _add_field_row(self, field_id: str, *, printed: bool) -> None:
        label = tr(FIELD_LABEL_KEYS[field_id])
        item = QListWidgetItem(f"{label}" if printed else tr("preferences.template_hidden_row", label=label))
        item.setData(Qt.ItemDataRole.UserRole, field_id)
        item.setData(Qt.ItemDataRole.UserRole + 1, printed)
        if not printed:
            item.setForeground(Qt.GlobalColor.gray)
        self._fields.addItem(item)

    def _refresh_buttons(self) -> None:
        row = self._fields.currentRow()
        item = self._fields.item(row) if row >= 0 else None
        printed = bool(item.data(Qt.ItemDataRole.UserRole + 1)) if item is not None else False
        self._up.setEnabled(row > 0 and printed)
        self._down.setEnabled(item is not None and printed and row < len(self._template.header_fields) - 1)
        self._toggle.setEnabled(item is not None)
        if item is not None:
            self._toggle.setText(
                tr("preferences.template_hide_field") if printed else tr("preferences.template_show_field")
            )
            self._fields.setDragDropMode(
                QListWidget.DragDropMode.InternalMove if printed else QListWidget.DragDropMode.NoDragDrop
            )

    # ── edits ────────────────────────────────────────────────────

    def _move(self, delta: int) -> None:
        row = self._fields.currentRow()
        order = list(self._template.header_fields)
        if row < 0 or row >= len(order):
            return
        target = row + delta
        if target < 0 or target >= len(order):
            return
        order.insert(target, order.pop(row))
        self._set_fields(order, select=target)

    def _toggle_selected(self) -> None:
        row = self._fields.currentRow()
        item = self._fields.item(row) if row >= 0 else None
        if item is None:
            return
        field_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        order = list(self._template.header_fields)
        if field_id in order:
            order.remove(field_id)
        else:
            order.append(field_id)
        self._set_fields(order, select=min(row, max(0, len(order) - 1)))

    def _set_fields(self, order: list[str], *, select: int) -> None:
        self._template = self._template.with_field_order(order)
        self._syncing = True
        try:
            self._rebuild_fields()
        finally:
            self._syncing = False
        if self._fields.count():
            self._fields.setCurrentRow(max(0, min(select, self._fields.count() - 1)))
        self._refresh_buttons()
        self.changed.emit()

    def _collect(self) -> None:
        if self._syncing:
            return
        self._template = replace(
            self._template,
            columns=int(self._columns.currentData() or 1),
            show_notes=self._notes.isChecked(),
            show_conclusion=self._conclusion.isChecked(),
            show_signature=self._signature.isChecked(),
        )
        self.changed.emit()

    def commit_drag(self) -> None:
        """Read the print order back after a drag-and-drop.

        Qt does not say what moved, so the widget reads its own rows: the
        printed ones, top to bottom, are the new order.
        """
        order = [
            str(self._fields.item(row).data(Qt.ItemDataRole.UserRole) or "")
            for row in range(self._fields.count())
            if bool(self._fields.item(row).data(Qt.ItemDataRole.UserRole + 1))
        ]
        self._template = self._template.with_field_order(order)
        self.changed.emit()

    # ── files ────────────────────────────────────────────────────

    def _export_to_file(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("preferences.template_export_title"), "report-template.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            Path(path).write_text(encode_template(self._template), encoding="utf-8")
        except OSError:
            QMessageBox.warning(self, tr("preferences.template_export"), tr("preferences.template_write_failed"))
            return
        QMessageBox.information(self, tr("preferences.template_export"), tr("preferences.template_exported", path=path))

    def _import_from_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, tr("preferences.template_import_title"), "", "JSON (*.json)")
        if not path:
            return
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except OSError:
            QMessageBox.warning(self, tr("preferences.template_import"), tr("preferences.template_read_failed"))
            return
        template = read_template_document(raw)
        if template is None:
            QMessageBox.warning(self, tr("preferences.template_import"), tr("preferences.template_read_failed"))
            return
        self.set_template(template)
        self.changed.emit()
