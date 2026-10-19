"""A4 preview of the report mode (UI-4 PR-1, spec §4.6, spike UI-4.0).

The sheet shows the exact PDF bytes of
:func:`~echo_personal_tool.infrastructure.measurement_report_pdf.render_report`
in a ``QPdfView`` (path (а) of the spike): what is on screen is what the
export writes (S-11). A rebuild is cheap enough to stay synchronous — the
spike measured 55 ms p95 for a typical report against the 500 ms budget —
so edits only schedule it through a 300 ms debounce (:data:`DEBOUNCE_MS`).

The widget owns presentation only. The window hands it a
``document_provider`` that builds the current
:class:`~echo_personal_tool.domain.services.report_builder.ReportDocument`;
the provider runs at rebuild time, never at schedule time, so the sheet
always shows the freshest study. The rendered document and its value-cell
anchors stay available (:attr:`document`, :attr:`anchors`,
:meth:`value_at`) for the «откуда значение» hover of PR-4; PR-1 draws no
hover card and no «измерить» markers.

``QtPdf`` ships in ``pyside6-addons``; a build trimmed to essentials has no
``QPdfView``. The import is therefore lazy and guarded: without it the
widget shows an honest «недоступно» placeholder instead of failing to load,
and the render itself (reportlab only) still works for the export path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QBuffer, QIODevice, Qt, QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from echo_personal_tool.domain.services.report_builder import ReportDocument
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.measurement_report_pdf import (
    PageRect,
    PdfExportError,
    ValueId,
    render_report,
)
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.report_mode import view_map

logger = logging.getLogger(__name__)

#: Rebuild debounce after a change (spike §3: render + load ≪ 500 ms budget).
DEBOUNCE_MS = 300

#: Hover tolerance of the spike's hit tests (§4.3: 3–4 pt forgives cell edges).
HIT_TOLERANCE_PT = 3.0

_ZOOM_FIT_WIDTH = "fit_width"
_ZOOM_FIT_PAGE = "fit_page"
#: Custom factors of the zoom combo; 1.0 is Qt's «100 %» (spike §4.1:
#: ``zoomFactor`` 1.0 means ``logicalDPI/72`` px per point, not 1 px/pt).
_ZOOM_FACTORS: tuple[float, ...] = (0.5, 0.75, 1.0, 1.5, 2.0)


def _pdf_view_classes() -> tuple[type, type] | None:
    """``(QPdfDocument, QPdfView)`` or ``None`` on an essentials-only build."""
    try:
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
    except ImportError:  # pragma: no cover - exercised via monkeypatch in tests
        return None
    return QPdfDocument, QPdfView


class ReportPreview(QWidget):
    """The A4 sheet of the report mode: zoom toolbar over a ``QPdfView``."""

    def __init__(
        self,
        document_provider: Callable[[], ReportDocument] | None = None,
        *,
        font_size: int = 10,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("reportPreview")
        self._provider = document_provider
        self._font_size = font_size
        self._document: ReportDocument | None = None
        self._anchors: dict[ValueId, list[PageRect]] = {}
        self._pdf_bytes: bytes = b""
        self._status_key = ""

        self._zoom_label = QLabel()
        self._zoom_label.setObjectName("reportZoomLabel")
        self._zoom = QComboBox()
        self._zoom.setObjectName("reportZoom")
        self._pages_label = QLabel()
        self._pages_label.setObjectName("reportPagesLabel")
        self._status_label = QLabel()
        self._status_label.setObjectName("reportStatusLabel")
        self._status_label.setVisible(False)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        toolbar.setSpacing(8)
        toolbar.addWidget(self._zoom_label)
        toolbar.addWidget(self._zoom)
        toolbar.addWidget(self._pages_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self._status_label)

        self._pdf = None
        self._view = None
        self._buffer: QBuffer | None = None
        self._screen_res: float | None = None
        self._placeholder: QLabel | None = None
        classes = _pdf_view_classes()
        if classes is not None:
            pdf_document_cls, pdf_view_cls = classes
            self._pdf = pdf_document_cls(self)
            self._view = pdf_view_cls(self)
            self._view.setObjectName("reportPdfView")
            self._view.setDocument(self._pdf)
            # Spike §6: the sheet scrolls through every page at column width.
            self._view.setPageMode(pdf_view_cls.PageMode.MultiPage)
            self._view.setZoomMode(pdf_view_cls.ZoomMode.FitToWidth)
            # Qt captures the screen resolution at construction (spike §4.2);
            # the mapping must read the same value once, here.
            self._screen_res = view_map.screen_resolution_for(self._view)
            navigator = self._view.pageNavigator()
            if hasattr(navigator, "currentPageChanged"):
                navigator.currentPageChanged.connect(lambda _page: self._update_pages_label())
            body: QWidget = self._view
        else:  # pragma: no cover - the fallback itself is covered via monkeypatch
            self._placeholder = QLabel()
            self._placeholder.setObjectName("reportUnavailable")
            self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._placeholder.setWordWrap(True)
            body = self._placeholder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(toolbar)
        layout.addWidget(body, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.refresh_now)
        self._zoom.currentIndexChanged.connect(self._apply_zoom)

        self.apply_theme()
        self.reload_text()

    # ── state ──────────────────────────────────────────────────────

    @property
    def document(self) -> ReportDocument | None:
        """The document the sheet was rendered from (``None`` before a render)."""
        return self._document

    @property
    def anchors(self) -> dict[ValueId, list[PageRect]]:
        """Value-cell rectangles of the last render, in page points (§8.4)."""
        return dict(self._anchors)

    @property
    def pdf_bytes(self) -> bytes:
        """The exact bytes on screen — the bytes the export writes (S-11)."""
        return self._pdf_bytes

    @property
    def page_count(self) -> int:
        return int(self._pdf.pageCount()) if self._pdf is not None else 0

    @property
    def font_size(self) -> int:
        return self._font_size

    @property
    def is_available(self) -> bool:
        """Whether this build can show the sheet at all (``QtPdf`` present)."""
        return self._view is not None

    def set_document_provider(self, provider: Callable[[], ReportDocument] | None) -> None:
        self._provider = provider

    def set_font_size(self, font_size: int) -> None:
        """PDF font size of the preferences; a change schedules a rebuild."""
        if int(font_size) == self._font_size:
            return
        self._font_size = int(font_size)
        self.request_refresh()

    # ── rendering ──────────────────────────────────────────────────

    def request_refresh(self) -> None:
        """Schedule a rebuild after the debounce; bursts collapse into one."""
        self._timer.start()

    def refresh_now(self) -> bool:
        """Rebuild from the provider at once. Returns whether a sheet rendered."""
        self._timer.stop()
        if self._provider is None:
            return False
        try:
            document = self._provider()
        except Exception:  # noqa: BLE001 - a broken snapshot must not kill the mode
            logger.exception("report preview: the document provider failed")
            self._show_status("report_mode.render_failed")
            return False
        return self._render(document)

    def set_document(self, document: ReportDocument) -> bool:
        """Render an already built document (the provider stays untouched)."""
        self._timer.stop()
        return self._render(document)

    def _render(self, document: ReportDocument) -> bool:
        try:
            rendered = render_report(document, font_size=self._font_size)
        except PdfExportError:
            self._show_status("report_mode.render_failed")
            return False
        self._document = document
        self._anchors = dict(rendered.anchors)
        self._pdf_bytes = rendered.pdf
        self._show_status("")
        if self._pdf is not None:
            from PySide6.QtPdf import QPdfDocument

            buffer = QBuffer(self)
            buffer.setData(rendered.pdf)
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            self._pdf.close()
            self._pdf.load(buffer)
            if self._buffer is not None:
                self._buffer.close()
            self._buffer = buffer
            if self._pdf.status() != QPdfDocument.Status.Ready:
                self._show_status("report_mode.render_failed")
                self._update_pages_label()
                return False
        self._update_pages_label()
        return True

    # ── geometry for PR-4 ──────────────────────────────────────────

    def value_at(self, x_widget: float, y_widget: float) -> ValueId | None:
        """The value cell under a viewport point, or ``None`` (PR-4 hover).

        Coordinates are in the ``QPdfView`` viewport's own system — the same
        space a mouse event on the viewport reports.
        """
        if self._view is None or self._pdf is None or self._screen_res is None or not self._anchors:
            return None
        page_sizes = [
            (self._pdf.pagePointSize(page).width(), self._pdf.pagePointSize(page).height())
            for page in range(self._pdf.pageCount())
        ]
        if not page_sizes:
            return None
        geoms = view_map.document_geometry(
            self._view,
            screen_res=self._screen_res,
            page_sizes_pt=page_sizes,
            current_page=self._view.pageNavigator().currentPage(),
        )
        return view_map.hit_test_anchors(
            geoms, x_widget, y_widget, self._anchors, tolerance_pt=HIT_TOLERANCE_PT
        )

    # ── toolbar ────────────────────────────────────────────────────

    def _apply_zoom(self) -> None:
        if self._view is None:
            return
        from PySide6.QtPdfWidgets import QPdfView

        choice = self._zoom.currentData()
        if choice == _ZOOM_FIT_WIDTH:
            self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        elif choice == _ZOOM_FIT_PAGE:
            self._view.setZoomMode(QPdfView.ZoomMode.FitInView)
        elif isinstance(choice, (int, float)):
            self._view.setZoomMode(QPdfView.ZoomMode.Custom)
            self._view.setZoomFactor(float(choice))

    def _update_pages_label(self) -> None:
        total = self.page_count
        if total <= 0 or self._view is None:
            self._pages_label.setText("")
            return
        current = int(self._view.pageNavigator().currentPage()) + 1
        self._pages_label.setText(tr("report_mode.page_of", current=current, total=total))

    def _show_status(self, key: str) -> None:
        self._status_key = key
        self._status_label.setText(tr(key) if key else "")
        self._status_label.setVisible(bool(key))

    # ── language and theme ─────────────────────────────────────────

    def reload_text(self) -> None:
        """Re-localize the toolbar (the sheet itself is rebuilt by the window)."""
        self._zoom_label.setText(tr("report_mode.zoom"))
        current = self._zoom.currentData() if self._zoom.count() else _ZOOM_FIT_WIDTH
        self._zoom.blockSignals(True)
        self._zoom.clear()
        self._zoom.addItem(tr("report_mode.zoom_fit_width"), _ZOOM_FIT_WIDTH)
        self._zoom.addItem(tr("report_mode.zoom_fit_page"), _ZOOM_FIT_PAGE)
        for factor in _ZOOM_FACTORS:
            self._zoom.addItem(f"{round(factor * 100)} %", factor)
        index = self._zoom.findData(current)
        self._zoom.setCurrentIndex(index if index >= 0 else 0)
        self._zoom.blockSignals(False)
        if self._placeholder is not None:
            self._placeholder.setText(tr("report_mode.unavailable"))
        if self._status_key:
            self._status_label.setText(tr(self._status_key))
        self._update_pages_label()

    def apply_theme(self) -> None:
        """Paint from the tokens of the active theme; the sheet stays PDF-white."""
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"""
            #reportPreview {{
                background: {tokens["surface.0"]};
            }}
            #reportZoomLabel, #reportPagesLabel {{
                color: {tokens["text.2"]};
            }}
            #reportStatusLabel {{
                color: {tokens["state.err"]};
            }}
            #reportUnavailable {{
                color: {tokens["text.2"]};
                background: {tokens["surface.1"]};
                border-top: 1px solid {tokens["line.1"]};
            }}
            #reportPdfView {{
                background: {tokens["surface.0"]};
                border-top: 1px solid {tokens["line.1"]};
            }}
            """
        )
