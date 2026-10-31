"""Export block of the report mode (UI-4 PR-5, spec §4.6, UQ-06/UQ-07).

The right column ends with what a surgeon does with a finished report: export
the PDF, print it, and finish the version.  Per UQ-06 only PDF and print exist
in this release — DICOM SR and «В PACS» stay hidden until their own spec, so
this panel deliberately has no disabled stubs for them.

«Завершить» is *not* an electronic signature (UQ-07): it fixes the version the
sheet shows, makes the report read-only and turns the button into «Новый
черновик» — editing starts a fresh draft.  Version storage is a separate
decision together with QH, so the frozen version lives in the tab session only
and is never written to disk here.

The panel does no I/O itself: it emits intent (export, print, finish, draft) and
shows the status line the window sets after the action.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

#: How long a status line stays on screen (same rhythm as the phrases column).
STATUS_TIMEOUT_MS = 6000


class ReportExportPanel(QFrame):
    """«Экспорт» and «Завершить» under the phrases column."""

    export_requested = Signal()
    print_requested = Signal()
    finish_requested = Signal()
    draft_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reportExport")
        self._finished = False

        self._title = QLabel()
        self._title.setObjectName("reportExportTitle")

        self._banner = QLabel()
        self._banner.setObjectName("reportExportBanner")
        self._banner.setWordWrap(True)
        self._banner.setVisible(False)

        self._pdf = QPushButton()
        self._pdf.setObjectName("reportExportPdf")
        self._pdf.setCursor(Qt.CursorShape.PointingHandCursor)
        self._print = QPushButton()
        self._print.setObjectName("reportExportPrint")
        self._print.setCursor(Qt.CursorShape.PointingHandCursor)
        self._finish = QPushButton()
        self._finish.setObjectName("reportFinish")
        self._finish.setCursor(Qt.CursorShape.PointingHandCursor)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(6)
        buttons.addWidget(self._pdf)
        buttons.addWidget(self._print)
        buttons.addStretch(1)
        buttons.addWidget(self._finish)

        self._status = QLabel()
        self._status.setObjectName("reportExportStatus")
        self._status.setWordWrap(True)
        self._status.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setSpacing(4)
        layout.addWidget(self._title)
        layout.addWidget(self._banner)
        layout.addLayout(buttons)
        layout.addWidget(self._status)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(STATUS_TIMEOUT_MS)
        self._status_timer.timeout.connect(lambda: self.set_status(""))

        self._pdf.clicked.connect(self.export_requested)
        self._print.clicked.connect(self.print_requested)
        self._finish.clicked.connect(self._on_finish_clicked)

        self.reload_text()
        self.apply_theme()

    # ── state ────────────────────────────────────────────────────────

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def finish_button(self) -> QPushButton:
        return self._finish

    @property
    def pdf_button(self) -> QPushButton:
        return self._pdf

    @property
    def print_button(self) -> QPushButton:
        return self._print

    def set_finished(self, finished: bool) -> None:
        """Switch between «Завершить» and «Новый черновик» with its banner."""
        self._finished = bool(finished)
        self._finish.setText(tr("report.draft_new") if self._finished else tr("report.finish"))
        self._finish.setToolTip(tr("report.draft_new_hint") if self._finished else tr("report.finish_hint"))
        self._banner.setText(tr("report.finish_banner"))
        self._banner.setVisible(self._finished)
        # Export and print stay available: a finished version is exactly what
        # one exports (UQ-07).
        self._pdf.setEnabled(True)
        self._print.setEnabled(True)

    def set_status(self, text: str) -> None:
        """Show (or clear) the outcome line of the last export/print."""
        self._status.setText(text)
        self._status.setVisible(bool(text))
        if text:
            self._status_timer.start()
        else:
            self._status_timer.stop()

    def _on_finish_clicked(self) -> None:
        if self._finished:
            self.draft_requested.emit()
        else:
            self.finish_requested.emit()

    # ── language and theme ───────────────────────────────────────────

    def reload_text(self) -> None:
        self._title.setText(tr("report.export"))
        self._pdf.setText(tr("report.export_pdf"))
        self._pdf.setToolTip(tr("report.export_pdf_hint"))
        self._print.setText(tr("report.print"))
        self._print.setToolTip(tr("report.print_hint"))
        self.set_finished(self._finished)

    def apply_theme(self) -> None:
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"""
            #reportExport {{
                background: {tokens["surface.2"]};
                border-top: 1px solid {tokens["line.1"]};
            }}
            #reportExportTitle {{
                color: {tokens["text.3"]};
                font-weight: 600;
            }}
            #reportExportBanner {{
                color: {tokens["state.warn"]};
            }}
            #reportExportStatus {{
                color: {tokens["text.2"]};
            }}
            #reportExportPdf, #reportExportPrint {{
                color: {tokens["accent.text"]};
                border: 1px solid {tokens["line.1"]};
                border-radius: 3px;
                padding: 2px 8px;
            }}
            #reportExportPdf:hover, #reportExportPrint:hover {{
                background: {tokens["surface.3"]};
            }}
            #reportFinish {{
                color: {tokens["text.1"]};
                border: 1px solid {tokens["line.1"]};
                border-radius: 3px;
                padding: 2px 10px;
            }}
            #reportFinish:hover {{
                background: {tokens["surface.3"]};
            }}
            """
        )
