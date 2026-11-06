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
        from echo_personal_tool.application.report_export import ReportExportError

        def broken(document, *, font_size=10):
            raise ReportExportError("pdf_export_failed")

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


class TestScrollRetention:
    """A rebuild must not jump the sheet back to page 1 (UI-4 PR-4 follow-up).

    ``_load_pdf`` closes and reloads ``QPdfDocument``; QPdfView then resets
    its scrollbars to zero, so every debounced refresh — often landing while
    the reader is hovering a value with the «откуда значение» card open —
    threw the whole page back to the top.
    """

    def test_a_rebuild_keeps_the_reader_position(self, qtbot) -> None:
        widget = _make(qtbot, lambda: _document(groups=30))
        assert widget.refresh_now() is True
        assert widget.page_count >= 2, "the position only matters on a multi-page sheet"
        qtbot.wait(100)  # let QPdfView's initial post-load layout land first
        scrollbar = widget._view.verticalScrollBar()
        assert scrollbar.maximum() > 0
        scrollbar.setValue(min(900, scrollbar.maximum()))
        qtbot.wait(20)
        assert scrollbar.value() > 0

        # The debounced rebuild's effect: same content, new bytes.
        widget.set_document(_document(groups=30))
        qtbot.wait(50)  # the deferred restore runs on the next event-loop turn

        assert scrollbar.value() > 0, "a rebuild must not jump the sheet to the top"

    def test_the_restore_clamps_to_the_new_document(self, qtbot) -> None:
        widget = _make(qtbot, lambda: _document(groups=30))
        assert widget.refresh_now() is True
        qtbot.wait(100)  # initial layout settles before the reader scrolls
        deep = widget._view.verticalScrollBar().maximum()
        assert deep > 0
        widget._view.verticalScrollBar().setValue(deep)
        qtbot.wait(20)
        assert widget._view.verticalScrollBar().value() > 0

        # The new document is a single page: the old offset cannot survive,
        # but the restore must clamp instead of overshooting.
        widget.set_document(_document(groups=1))
        qtbot.wait(50)

        scrollbar = widget._view.verticalScrollBar()
        assert 0 <= scrollbar.value() <= scrollbar.maximum()


class TestReportFormatHeader:
    """Item 7 of the 2026-11-06 list: «ЭхоКГ | УЗИ» in the sheet header.

    The preview owns the buttons; the window owns the choice.  A click reports
    the intent, and a finished sheet keeps its format until the draft returns.
    """

    def test_the_header_shows_one_button_per_format(self, qtbot) -> None:
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ORDER

        widget = _make(qtbot, lambda: _document())
        assert set(widget._profile_buttons) == set(PROFILE_ORDER)
        assert widget.profile_id == PROFILE_ORDER[0]
        assert widget._profile_buttons[PROFILE_ORDER[0]].isChecked()

    def test_a_click_reports_the_intent_and_presses_the_button(self, qtbot) -> None:
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ULTRASOUND

        widget = _make(qtbot, lambda: _document())
        seen: list[str] = []
        widget.profile_changed.connect(seen.append)

        widget._profile_buttons[PROFILE_ULTRASOUND].click()

        assert seen == [PROFILE_ULTRASOUND]
        assert widget.profile_id == PROFILE_ULTRASOUND
        assert widget._profile_buttons[PROFILE_ULTRASOUND].isChecked()

    def test_a_click_on_the_active_format_reports_nothing(self, qtbot) -> None:
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ECHO

        widget = _make(qtbot, lambda: _document())
        seen: list[str] = []
        widget.profile_changed.connect(seen.append)

        widget._profile_buttons[PROFILE_ECHO].click()

        assert seen == []
        assert widget._profile_buttons[PROFILE_ECHO].isChecked()

    def test_a_finished_sheet_locks_the_format(self, qtbot) -> None:
        widget = _make(qtbot, lambda: _document())
        widget.set_frozen(True)
        assert not any(button.isEnabled() for button in widget._profile_buttons.values())

        widget.set_frozen(False)
        assert all(button.isEnabled() for button in widget._profile_buttons.values())

    def test_an_unknown_format_never_becomes_the_pressed_one(self, qtbot) -> None:
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ECHO

        widget = _make(qtbot, lambda: _document())
        widget.set_profile("thyroid")
        assert widget.profile_id == PROFILE_ECHO
