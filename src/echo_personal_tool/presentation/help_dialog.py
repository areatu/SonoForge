"""Native in-app reader for the bundled user guide."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QMarginsF, QUrl
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget

from echo_personal_tool.infrastructure.i18n import get_language, tr


def help_document_path(language: str | None = None) -> Path:
    """Resolve the localized HELP document in source and PyInstaller builds."""
    language = language or get_language()
    filename = "HELP_RU.md" if language == "ru" else "HELP_EN.md"
    source_root = Path(__file__).resolve().parents[3]
    runtime_root = Path(getattr(sys, "_MEIPASS", source_root))
    candidates = (runtime_root / "docs" / filename, source_root / "docs" / filename)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


class HelpDialog(QDialog):
    """Display the user guide with Qt's native Markdown renderer."""

    def __init__(self, parent: QWidget | None = None, *, language: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("helpDialog")
        self.setWindowTitle(tr("start_page.help"))
        self.setMinimumSize(680, 480)
        self.resize(980, 720)

        layout = QVBoxLayout(self)
        self._browser = QTextBrowser(self)
        self._browser.setObjectName("helpDocument")
        self._browser.setOpenExternalLinks(True)
        path = help_document_path(language)
        if path.is_file():
            self._browser.document().setBaseUrl(QUrl.fromLocalFile(str(path.parent) + "/"))
            self._browser.setMarkdown(path.read_text(encoding="utf-8"))
        else:
            self._browser.setPlainText(tr("start_page.help_unavailable"))
        layout.addWidget(self._browser, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText(tr("button.close"))
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


def show_help_dialog(parent: QWidget | None = None) -> None:
    dialog = HelpDialog(parent)
    dialog.exec()


def export_help_pdf(language: str | None = None, *, target: Path | None = None) -> Path | None:
    """Render the bundled HELP document to a PDF with in-document links.

    The Markdown is laid out by ``QTextDocument`` and printed through
    ``QPrinter`` into a PDF file, so the guide opens in the platform PDF viewer
    instead of only on GitHub. Returns ``None`` when the guide file is missing.
    """
    language = language or get_language()
    path = help_document_path(language)
    if not path.is_file():
        return None
    from PySide6.QtPrintSupport import QPrinter

    document = QTextDocument()
    document.setBaseUrl(QUrl.fromLocalFile(str(path.parent) + "/"))
    document.setMarkdown(path.read_text(encoding="utf-8"))

    suffix = "RU" if language == "ru" else "EN"
    output = target or Path(tempfile.gettempdir()) / f"SonoForge-HELP-{suffix}.pdf"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(output))
    printer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(12.0, 12.0, 12.0, 12.0),
            QPageLayout.Unit.Millimeter,
        )
    )
    document.print_(printer)
    return output if output.is_file() else None


def open_help_pdf(parent: QWidget | None = None) -> Path | None:
    """Export the guide to PDF (if needed) and open it in the system viewer."""
    from PySide6.QtGui import QDesktopServices

    pdf = export_help_pdf()
    if pdf is None:
        show_help_dialog(parent)
        return None
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf)))
    return pdf
