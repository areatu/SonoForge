"""Printing the report PDF (UI-4 PR-5, spec §4.6, UQ-06).

Printing prints *the same bytes* the sheet shows and the export writes (S-11):
the PDF is loaded back through ``QPdfDocument`` and each page is rasterised onto
the printer at the resolution the printer reports.  Nothing is re-laid out for
paper, so a printed value cannot differ from the on-screen one.

The module is guarded: a build without ``QtPdf`` reports ``False`` instead of
crashing, and a printer that refuses to start the painter is an honest failure
(the window shows a status line, the report stays intact).
"""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QIODevice, QSize


def print_report_pdf(pdf_bytes: bytes, printer) -> bool:
    """Draw every page of *pdf_bytes* onto *printer*; ``False`` on failure.

    One PDF page is one printed page: the page rectangle of the printer is the
    target, so the printer's own scaling and margins apply and the aspect ratio
    of the sheet is preserved by ``QPdfDocument.render``.
    """
    if not pdf_bytes:
        return False
    try:
        from PySide6.QtGui import QPainter
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPrintSupport import QPrinter
    except ImportError:  # pragma: no cover - essentials-only build
        return False

    document = QPdfDocument()
    buffer = QBuffer()
    buffer.setData(pdf_bytes)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    try:
        document.load(buffer)
        if document.status() != QPdfDocument.Status.Ready or document.pageCount() < 1:
            return False
        painter = QPainter()
        if not painter.begin(printer):
            return False
        try:
            for page in range(document.pageCount()):
                if page:
                    printer.newPage()
                rect = printer.pageRect(QPrinter.Unit.DevicePixel)
                size = QSize(int(rect.width()), int(rect.height()))
                if size.width() < 1 or size.height() < 1:
                    return False
                image = document.render(page, size)
                if image.isNull():
                    return False
                painter.drawImage(rect.topLeft(), image)
        finally:
            painter.end()
    finally:
        document.close()
        buffer.close()
    return True
