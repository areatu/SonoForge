"""A4 preview of the report mode (UI-4 PR-1, spec §4.6, spike UI-4.0).

The sheet is the ``render_report`` bytes in a ``QPdfView`` (MultiPage +
FitToWidth), rebuilt synchronously after a 300 ms debounce. The cases pin
the render contract (bytes, anchors, page count), the zoom toolbar, the
debounce, the failure surfaces and the essentials-only fallback; the
geometry itself is pinned without Qt in ``test_report_view_map.py``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
pytestmark = pytest.mark.gui

from echo_personal_tool.domain.services.report_builder import (  # noqa: E402
    PatientInfo,
    ReportDocument,
    ReportGroup,
    ReportValue,
)
from echo_personal_tool.infrastructure.i18n import tr  # noqa: E402
from echo_personal_tool.presentation.report_mode import preview as preview_module  # noqa: E402
from echo_personal_tool.presentation.report_mode.preview import DEBOUNCE_MS, ReportPreview  # noqa: E402


def _document(groups: int = 1) -> ReportDocument:
    built = []
    for index in range(groups):
        built.append(
            ReportGroup(
                title=f"Группа {index}",
                key="lv",
                values=(
                    ReportValue(
                        label="КДР ЛЖ",
                        value="52.0",
                        unit="мм",
                        norm="36–51",
                        pathological=False,
                        group="lv",
                    ),
                    ReportValue(
                        label="ФВ ЛЖ",
                        value="48.0",
                        unit="%",
                        norm="52–72",
                        pathological=True,
                        group="lv",
                    ),
                ),
            )
        )
    return ReportDocument(patient=PatientInfo(name="Иванов И.И.", sex="M"), groups=tuple(built))


def _make(qtbot, provider=None, **kwargs) -> ReportPreview:
    widget = ReportPreview(provider if provider is not None else _document, **kwargs)
    qtbot.addWidget(widget)
    widget.resize(900, 1100)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


class TestRendering:
    def test_refresh_renders_the_provider_document(self, qtbot) -> None:
        document = _document()
        widget = _make(qtbot, lambda: document)
        assert widget.refresh_now() is True
        assert widget.document is document
        assert widget.pdf_bytes[:5] == b"%PDF-"
        assert widget.page_count == 1
        assert set(widget.anchors) == {(0, 0), (0, 1)}
        assert widget._pages_label.text() == "Страница 1 из 1"
        assert widget._status_label.isVisible() is False

    def test_the_empty_document_still_renders_a_sheet(self, qtbot) -> None:
        widget = _make(qtbot, ReportDocument)
        assert widget.refresh_now() is True
        assert widget.page_count == 1
        assert widget.anchors == {}

    def test_set_document_renders_without_the_provider(self, qtbot) -> None:
        calls: list[int] = []

        def provider() -> ReportDocument:
            calls.append(1)
            return _document()

        widget = _make(qtbot, provider)
        assert widget.set_document(_document(groups=2)) is True
        assert calls == []
        assert set(widget.anchors) == {(0, 0), (0, 1), (1, 0), (1, 1)}

    def test_a_long_study_spans_pages_in_multipage_mode(self, qtbot) -> None:
        from PySide6.QtPdfWidgets import QPdfView

        widget = _make(qtbot, lambda: _document(groups=30))
        assert widget.refresh_now() is True
        assert widget.page_count >= 2
        assert widget._view.pageMode() == QPdfView.PageMode.MultiPage

    def test_request_refresh_is_debounced_and_collapses_bursts(self, qtbot) -> None:
        calls: list[int] = []

        def provider() -> ReportDocument:
            calls.append(1)
            return _document()

        widget = _make(qtbot, provider)
        widget.request_refresh()
        widget.request_refresh()
        widget.request_refresh()
        assert calls == []  # nothing synchronous — the debounce owns the timing
        qtbot.wait(DEBOUNCE_MS + 250)
        assert calls == [1]
        assert widget.page_count == 1

    def test_font_size_change_schedules_a_rebuild(self, qtbot) -> None:
        widget = _make(qtbot, font_size=10)
        widget.set_font_size(10)
        assert widget._timer.isActive() is False
        widget.set_font_size(12)
        assert widget.font_size == 12
        assert widget._timer.isActive() is True
        widget._timer.stop()


class TestFailures:
    def test_a_failing_provider_shows_a_status_instead_of_raising(self, qtbot) -> None:
        def provider() -> ReportDocument:
            raise RuntimeError("snapshot is gone")

        widget = _make(qtbot, provider)
        assert widget.refresh_now() is False
        assert widget._status_label.isVisible() is True
        assert widget._status_label.text() == tr("report_mode.render_failed")
        assert widget.pdf_bytes == b""

    def test_a_render_failure_shows_the_same_status(self, qtbot, monkeypatch) -> None:
        from echo_personal_tool.infrastructure.measurement_report_pdf import PdfExportError

        def broken(document, *, font_size=10):
            raise PdfExportError("pdf_export_failed")

        monkeypatch.setattr(preview_module, "render_report", broken)
        widget = _make(qtbot)
        assert widget.refresh_now() is False
        assert widget._status_label.text() == tr("report_mode.render_failed")

    def test_without_qtpdf_the_widget_degrades_to_a_placeholder(self, qtbot, monkeypatch) -> None:
        monkeypatch.setattr(preview_module, "_pdf_view_classes", lambda: None)
        widget = ReportPreview(_document)
        qtbot.addWidget(widget)
        widget.show()
        assert widget.is_available is False
        assert widget._placeholder is not None
        assert widget._placeholder.text() == tr("report_mode.unavailable")
        # The render itself (reportlab) still works — only the sheet is missing.
        assert widget.refresh_now() is True
        assert widget.pdf_bytes[:5] == b"%PDF-"
        assert widget.page_count == 0
        assert widget.value_at(10, 10) is None


class TestZoomAndGeometry:
    def test_zoom_defaults_to_fit_width_and_follows_the_combo(self, qtbot) -> None:
        from PySide6.QtPdfWidgets import QPdfView

        widget = _make(qtbot)
        widget.refresh_now()
        assert widget._view.zoomMode() == QPdfView.ZoomMode.FitToWidth
        widget._zoom.setCurrentIndex(widget._zoom.findData(1.0))
        assert widget._view.zoomMode() == QPdfView.ZoomMode.Custom
        assert widget._view.zoomFactor() == pytest.approx(1.0)
        widget._zoom.setCurrentIndex(widget._zoom.findData("fit_page"))
        assert widget._view.zoomMode() == QPdfView.ZoomMode.FitInView

    def test_reload_text_keeps_the_chosen_zoom(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.i18n import set_language

        widget = _make(qtbot)
        widget._zoom.setCurrentIndex(widget._zoom.findData(1.5))
        try:
            set_language("en")
            widget.reload_text()
        finally:
            set_language("ru")
        assert widget._zoom.currentData() == 1.5
        assert widget._zoom.itemText(0) == "Fit width"

    def test_value_at_hits_the_cell_under_the_point(self, qtbot) -> None:
        from echo_personal_tool.presentation.report_mode import view_map

        widget = _make(qtbot)
        widget.refresh_now()
        qtbot.wait(50)
        sizes = [
            (widget._pdf.pagePointSize(page).width(), widget._pdf.pagePointSize(page).height())
            for page in range(widget._pdf.pageCount())
        ]
        geoms = view_map.document_geometry(
            widget._view, screen_res=widget._screen_res, page_sizes_pt=sizes, current_page=0
        )
        box = view_map.page_rect_to_viewport(geoms[0], widget.anchors[(0, 1)][0])
        assert widget.value_at(box.center().x(), box.center().y()) == (0, 1)
        assert widget.value_at(2, 2) is None
