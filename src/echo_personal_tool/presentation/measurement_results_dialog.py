"""Dialog for study-wide measurement results and PDF export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.measurement_report_formatter import (
    format_measurement_report,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.measurement_report_pdf import (
    PdfExportError,
    export_measurement_report_pdf,
)


class MeasurementResultsDialog(QDialog):
    """Show study report and export to PDF."""

    def __init__(
        self,
        snapshot: MeasurementSnapshot | None,
        *,
        parent=None,
        default_pdf_name: str = "echo_measurements.pdf",
        length_display_unit: str = "mm",
        pdf_font_size: int = 10,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("measurement_results.title"))
        self.resize(520, 640)
        self._report_text = format_measurement_report(
            snapshot,
            length_display_unit=length_display_unit,
        )
        self._pdf_font_size = pdf_font_size
        self._default_pdf_name = default_pdf_name

        self._text = QPlainTextEdit(self._report_text)
        self._text.setReadOnly(True)

        export_button = QPushButton(tr("measurement_results.export_pdf"))
        export_button.clicked.connect(self._export_pdf)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(self._text)
        layout.addWidget(export_button)
        layout.addWidget(buttons)

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
            export_measurement_report_pdf(
                self._report_text,
                output_path,
                font_size=self._pdf_font_size,
            )
        except PdfExportError as exc:
            QMessageBox.warning(self, tr("measurement_results.pdf_error.title"), str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_path.resolve())))
