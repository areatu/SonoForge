"""Study report window: grouped measurements, patient data, conclusion, PDF.

The window renders :class:`ReportDocument` — the same structure the PDF export
writes — so what the physician sees on screen is what gets printed. Values
outside the reference range are highlighted, and the reference range itself is
shown next to the value so the reader does not have to trust the colour.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.report_builder import (
    PatientInfo,
    ReportDocument,
    build_report_document,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.measurement_report_pdf import (
    PdfExportError,
    export_report_document_pdf,
)

#: Colour used for values outside the reference range (screen and PDF).
_PATHOLOGY_COLOR = QColor("#C0392B")

#: Header fields in print order: ``(PatientInfo attribute, i18n key)``.
_TEXT_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "report.patient_name"),
    ("patient_id", "report.patient_id"),
    ("birth_date", "report.birth_date"),
    ("age", "report.age"),
    ("study_date", "report.study_date"),
    ("institution", "report.institution"),
    ("equipment", "report.equipment"),
    ("physician", "report.physician"),
    ("indication", "report.indication"),
)


class ReportDialog(QDialog):
    """Structured study report with an editable header and conclusion."""

    def __init__(
        self,
        snapshot: MeasurementSnapshot | None,
        *,
        patient: PatientInfo | None = None,
        parent=None,
        default_pdf_name: str = "echo_report.pdf",
        length_display_unit: str = "mm",
        pdf_font_size: int = 10,
    ) -> None:
        super().__init__(parent)
        self._snapshot = snapshot
        self._initial_patient = patient or PatientInfo()
        self._default_pdf_name = default_pdf_name
        self._length_display_unit = length_display_unit
        self._pdf_font_size = pdf_font_size

        self.setWindowTitle(tr("report.title"))
        self.resize(760, 720)

        self._fields: dict[str, QLineEdit] = {}
        self._build_header()
        self._tree = self._build_tree()
        self._conclusion = QPlainTextEdit()
        self._conclusion.setPlaceholderText(tr("report.conclusion_hint"))
        self._conclusion.setPlainText(self._initial_patient.conclusion)
        self._conclusion.setMinimumHeight(80)

        conclusion_box = QGroupBox(tr("report.conclusion"))
        conclusion_layout = QVBoxLayout(conclusion_box)
        conclusion_layout.addWidget(self._conclusion)

        note = QLabel(tr("report.pathology_note"))
        note.setStyleSheet("color: #C0392B;")

        export_button = QPushButton(tr("measurement_results.export_pdf"))
        export_button.clicked.connect(self._export_pdf)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        bottom = QHBoxLayout()
        bottom.addWidget(export_button)
        bottom.addStretch(1)
        bottom.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(self._header_box)
        layout.addWidget(self._tree, 1)
        layout.addWidget(note)
        layout.addWidget(conclusion_box)
        layout.addLayout(bottom)

        self._rebuild()

    # ── construction ─────────────────────────────────────────────────────
    def _build_header(self) -> None:
        self._header_box = QGroupBox(tr("report.patient"))
        form = QFormLayout(self._header_box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._sex = QComboBox()
        self._sex.addItem(tr("report.sex_unknown"), "")
        self._sex.addItem(tr("report.sex_male"), "M")
        self._sex.addItem(tr("report.sex_female"), "F")
        self._sex.setCurrentIndex(
            0 if not self._initial_patient.sex else self._sex_index_for(self._initial_patient.sex)
        )
        # Sex decides which reference range applies, so the table is rebuilt.
        self._sex.currentIndexChanged.connect(self._rebuild)

        for attribute, label_key in _TEXT_FIELDS:
            editor = QLineEdit(str(getattr(self._initial_patient, attribute) or ""))
            self._fields[attribute] = editor
            form.addRow(tr(label_key), editor)
        form.addRow(tr("report.sex"), self._sex)

        height = self._initial_patient.height_cm
        weight = self._initial_patient.weight_kg
        bsa = self._initial_patient.bsa_m2
        self._body_metrics = QLabel(self._body_metrics_text(height, weight, bsa))
        form.addRow("", self._body_metrics)

    @staticmethod
    def _sex_index_for(sex: str) -> int:
        """Combo index for a DICOM sex code; ``O``/unknown stays "not specified"."""
        code = sex.casefold()[:1]
        if code in ("f", "ж", "w"):
            return 2
        if code in ("m", "м"):
            return 1
        return 0

    @staticmethod
    def _body_metrics_text(height: float | None, weight: float | None, bsa: float | None) -> str:
        parts: list[str] = []
        if height is not None:
            parts.append(f"{tr('report.height')}: {height:.0f}")
        if weight is not None:
            parts.append(f"{tr('report.weight')}: {weight:.0f}")
        if bsa is not None:
            parts.append(f"{tr('report.bsa')}: {bsa:.2f}")
        return "   ".join(parts)

    def _build_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(
            [
                tr("report.col_parameter"),
                tr("report.col_value"),
                tr("report.col_unit"),
                tr("report.col_norm"),
            ]
        )
        tree.setRootIsDecorated(True)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        return tree

    # ── state ────────────────────────────────────────────────────────────
    def patient_info(self) -> PatientInfo:
        """Patient header as currently edited in the dialog."""
        values: dict[str, object] = {attribute: editor.text().strip() for attribute, editor in self._fields.items()}
        return PatientInfo(
            name=str(values.get("name", "")),
            patient_id=str(values.get("patient_id", "")),
            birth_date=str(values.get("birth_date", "")),
            age=str(values.get("age", "")),
            sex=str(self._sex.currentData() or ""),
            study_date=str(values.get("study_date", "")),
            height_cm=self._initial_patient.height_cm,
            weight_kg=self._initial_patient.weight_kg,
            bsa_m2=self._initial_patient.bsa_m2,
            physician=str(values.get("physician", "")),
            institution=str(values.get("institution", "")),
            indication=str(values.get("indication", "")),
            equipment=str(values.get("equipment", "")),
            conclusion=self._conclusion.toPlainText(),
        )

    def document(self) -> ReportDocument:
        """The report exactly as it would be printed right now."""
        return build_report_document(
            self._snapshot,
            self.patient_info(),
            sex=str(self._sex.currentData() or ""),
            length_display_unit=self._length_display_unit,
        )

    def _rebuild(self) -> None:
        document = self.document()
        self._fill_tree(document)
        self._body_metrics.setText(
            self._body_metrics_text(
                document.patient.height_cm,
                document.patient.weight_kg,
                document.patient.bsa_m2,
            )
        )

    def _fill_tree(self, document: ReportDocument) -> None:
        self._tree.clear()
        pathology = QBrush(_PATHOLOGY_COLOR)
        for group in document.groups:
            top = QTreeWidgetItem([group.title, "", "", ""])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            self._tree.addTopLevelItem(top)
            for value in group.values:
                item = QTreeWidgetItem([value.label, value.value, value.unit, value.norm])
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight)
                if value.pathological:
                    for column in range(4):
                        item.setForeground(column, pathology)
                    bold = item.font(1)
                    bold.setBold(True)
                    item.setFont(1, bold)
                top.addChild(item)
            top.setExpanded(True)
        self._tree.resizeColumnToContents(0)

    # ── export ───────────────────────────────────────────────────────────
    def _export_pdf(self) -> None:
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        path, _ = styled_save_file(
            self,
            tr("measurement_results.save_pdf"),
            self._default_pdf_name,
            "PDF (*.pdf)",
        )
        if not path:
            return
        output_path = Path(path)
        if output_path.suffix.lower() != ".pdf":
            output_path = output_path.with_suffix(".pdf")
        try:
            export_report_document_pdf(
                self.document(),
                output_path,
                font_size=self._pdf_font_size,
            )
        except PdfExportError as exc:
            QMessageBox.warning(self, tr("measurement_results.pdf_error.title"), str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_path.resolve())))
