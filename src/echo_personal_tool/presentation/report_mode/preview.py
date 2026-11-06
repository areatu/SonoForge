"""A4 preview of the report mode (UI-4 PR-1, spec §4.6, spike UI-4.0).

The sheet shows the exact PDF bytes of
:func:`~echo_personal_tool.application.report_export.render_report`
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

Hovering a value cell opens the «откуда значение» card of PR-4
(:mod:`.provenance`): :meth:`ReportPreview.value_at` already maps a point to
the value cell, and the card reads the lineage recorded in the document.  The
card is a child of this widget, so nothing is ever drawn into the PDF and the
sheet stays exactly the exported bytes.

``QtPdf`` ships in ``pyside6-addons``; a build trimmed to essentials has no
``QPdfView``. The import is therefore lazy and guarded: without it the
widget shows an honest «недоступно» placeholder instead of failing to load,
and the render itself (reportlab only) still works for the export path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QBuffer, QEvent, QIODevice, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget

# `import … as` binds the submodule without importing the package root (whose __init__ imports this module).
import echo_personal_tool.presentation.report_mode.view_map as view_map
from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.report_export import (
    PageRect,
    ReportExportError,
    ValueId,
    render_report,
)
from echo_personal_tool.domain.services.report_builder import ReportDocument, ReportValue
from echo_personal_tool.domain.services.report_profiles import (
    DEFAULT_PROFILE_ID,
    PROFILE_ORDER,
    normalize_profile_id,
)
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.report_mode.provenance import ClipLabelProvider, ReportValueCard

logger = logging.getLogger(__name__)

#: Rebuild debounce after a change (spike §3: render + load ≪ 500 ms budget).
DEBOUNCE_MS = 300

#: Hover tolerance of the spike's hit tests (§4.3: 3–4 pt forgives cell edges).
HIT_TOLERANCE_PT = 3.0

#: How long the card survives the pointer leaving the sheet (so it can be
#: entered and its button clicked) — spec §4.7 uses the same 250 ms grace.
CARD_GRACE_MS = 250

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


@dataclass(frozen=True)
class SheetVersion:
    """A finished version of the sheet: bytes, source document and anchors.

    «Завершить» stores exactly this triple in the tab session (UQ-07): the
    bytes are what export and print write, the document feeds the hover card
    and the anchors keep the card working without a second render.
    """

    pdf: bytes
    document: ReportDocument
    anchors: dict[ValueId, list[PageRect]] = field(default_factory=dict)


class ReportPreview(QWidget):
    """The A4 sheet of the report mode: zoom toolbar over a ``QPdfView``."""

    open_frames_requested = Signal(str, int)  # sop_instance_uid, frame_index
    #: The physician picked another report format in the sheet header (item 7
    #: of the 2026-11-06 list).  The window owns the choice — it lives in the
    #: tab, not in the preview — and rebuilds the document.
    profile_changed = Signal(str)
    #: The physician turned the «Входные данные» footnote of the calculations on
    #: or off from the sheet header (item 8 of the 2026-11-06 list).
    inputs_visibility_changed = Signal(bool)
    #: The physician asked to hide / restore one row of the sheet (item 9 of
    #: the 2026-11-06 list).  ``(value_key, hidden)`` — the window owns the set
    #: and rebuilds the document from it, so hiding never edits the bytes.
    value_visibility_changed = Signal(str, bool)
    #: The physician renamed a planimetry row from its «откуда значение» card
    #: (item 10 of the 2026-11-06 list): ``(measurement_id, new_label)``.
    value_rename_requested = Signal(str, str)

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
        self._hovered: ValueId | None = None
        self._frozen = False

        self._zoom_label = QLabel()
        self._zoom_label.setObjectName("reportZoomLabel")
        self._zoom = QComboBox()
        self._zoom.setObjectName("reportZoom")
        self._pages_label = QLabel()
        self._pages_label.setObjectName("reportPagesLabel")
        self._status_label = QLabel()
        self._status_label.setObjectName("reportStatusLabel")
        self._status_label.setVisible(False)

        self._profile_label = QLabel()
        self._profile_label.setObjectName("reportProfileLabel")
        #: Segmented «ЭхоКГ | УЗИ» of the header.  Checkable buttons in one row:
        #: the sheet says which format is printed, and the choice is one click —
        #: the owner asked for the format to be visible where the sheet is, not
        #: buried in the settings of the application.
        self._profile_buttons: dict[str, QToolButton] = {}
        #: «Входные данные» switch of the header.  A checkable button rather than
        #: a checkbox: it belongs to the segmented row of the sheet controls and
        #: must read as part of it, not as a form field of the application.
        self._inputs_button = QToolButton()
        self._inputs_button.setObjectName("reportInputsToggle")
        self._inputs_button.setCheckable(True)
        self._inputs_button.setAutoRaise(True)
        self._inputs_button.toggled.connect(lambda checked: self.inputs_visibility_changed.emit(bool(checked)))
        self._profile_id = DEFAULT_PROFILE_ID
        self._profile_row = QWidget()
        self._profile_row.setObjectName("reportProfileRow")
        profile_layout = QHBoxLayout(self._profile_row)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.setSpacing(0)
        for index, profile_id in enumerate(PROFILE_ORDER):
            button = QToolButton()
            button.setObjectName(f"reportProfile_{profile_id}")
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setProperty("segment", "first" if index == 0 else "last")
            button.clicked.connect(lambda _checked=False, chosen=profile_id: self._request_profile(chosen))
            profile_layout.addWidget(button)
            self._profile_buttons[profile_id] = button

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        toolbar.setSpacing(8)
        toolbar.addWidget(self._profile_label)
        toolbar.addWidget(self._profile_row)
        toolbar.addWidget(self._inputs_button)
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

        # PR-4: the hover card lives over the sheet and never inside it.
        self._card = ReportValueCard(self)
        self._card.rename_requested.connect(self.value_rename_requested)
        self._card.open_frames_requested.connect(self.open_frames_requested)
        self._card.hover_entered.connect(self._cancel_card_hide)
        self._card.hover_left.connect(self._schedule_card_hide)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(CARD_GRACE_MS)
        self._hide_timer.timeout.connect(self._hide_card)
        self._install_hover_filter()

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
        try:
            return int(self._pdf.pageCount()) if self._pdf is not None else 0
        except RuntimeError:  # the document is already gone during teardown
            return 0

    @property
    def font_size(self) -> int:
        return self._font_size

    @property
    def is_available(self) -> bool:
        """Whether this build can show the sheet at all (``QtPdf`` present)."""
        return self._view is not None

    def set_document_provider(self, provider: Callable[[], ReportDocument] | None) -> None:
        self._provider = provider

    @property
    def is_frozen(self) -> bool:
        """Whether the sheet is a finished version (no rebuilds, UQ-07)."""
        return self._frozen

    def set_frozen(self, frozen: bool) -> None:
        """A finished version stops following the study until a new draft."""
        self._frozen = bool(frozen)
        self.set_profile_locked(self._frozen)
        if self._frozen:
            self._timer.stop()
            self._hide_card()

    def set_font_size(self, font_size: int) -> None:
        """PDF font size of the preferences; a change schedules a rebuild."""
        if int(font_size) == self._font_size:
            return
        self._font_size = int(font_size)
        self.request_refresh()

    # ── rendering ──────────────────────────────────────────────────

    def request_refresh(self) -> None:
        """Schedule a rebuild after the debounce; bursts collapse into one.

        A frozen version ignores the request: measurements may keep changing
        in the study, the finished sheet must not (UQ-07).
        """
        if self._frozen:
            return
        self._timer.start()

    def refresh_now(self) -> bool:
        """Rebuild from the provider at once. Returns whether a sheet rendered."""
        self._timer.stop()
        if self._frozen or self._provider is None:
            return False
        try:
            document = self._provider()
        except Exception as exc:  # noqa: BLE001 - a broken snapshot must not kill the mode
            log_boundary_failure(logger, "report.render", exc, code="unexpected", level=logging.WARNING)
            self._show_status("report_mode.render_failed")
            return False
        return self._render(document)

    def set_document(self, document: ReportDocument) -> bool:
        """Render an already built document (the provider stays untouched)."""
        self._timer.stop()
        return self._render(document)

    def version(self) -> SheetVersion | None:
        """The sheet as a finished version (``None`` before the first render)."""
        if self._document is None or not self._pdf_bytes:
            return None
        return SheetVersion(pdf=self._pdf_bytes, document=self._document, anchors=self.anchors)

    def set_version(self, version: SheetVersion | None) -> bool:
        """Show a stored version without re-rendering it (UQ-07).

        Re-rendering would create *new* bytes with a new PDF identity; a fixed
        version must be the very document that was signed off, so the bytes and
        the anchors of :meth:`version` come back unchanged.
        """
        self._timer.stop()
        if version is None:
            return False
        self._hide_card()
        self._document = version.document
        self._anchors = dict(version.anchors)
        self._pdf_bytes = version.pdf
        return self._load_pdf(version.pdf)

    def _render(self, document: ReportDocument) -> bool:
        self._hide_card()
        try:
            rendered = render_report(document, font_size=self._font_size)
        except ReportExportError:
            self._show_status("report_mode.render_failed")
            return False
        self._document = document
        self._anchors = dict(rendered.anchors)
        self._pdf_bytes = rendered.pdf
        self._show_status("")
        return self._load_pdf(rendered.pdf)

    def _load_pdf(self, pdf_bytes: bytes) -> bool:
        """Load bytes into the view (no view on an essentials-only build)."""
        if self._pdf is not None:
            from PySide6.QtPdf import QPdfDocument

            # A debounced rebuild reloads the document, and QPdfView resets
            # its scroll to the top: the sheet jumped to page 1 under the
            # reader — often right under the «откуда значение» card. Remember
            # the position and put it back once the new bytes are in.
            keep = self._view_position()
            buffer = QBuffer(self)
            buffer.setData(pdf_bytes)
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
            self._restore_view_position(keep)
        self._update_pages_label()
        return True

    def _view_position(self) -> tuple[int, int, int] | None:
        """``(page, x, y)`` of the reader, or ``None`` without a view."""
        if self._view is None:
            return None
        return (
            self._view.pageNavigator().currentPage(),
            self._view.horizontalScrollBar().value(),
            self._view.verticalScrollBar().value(),
        )

    def _restore_view_position(self, keep: tuple[int, int, int] | None) -> None:
        """Put the reader back where the reload left them (clamped).

        QPdfView lays its pages out after ``load()``; the scrollbar maxima
        are only trustworthy on the next turn of the event loop, so the
        restore runs both at once and deferred. Values are clamped, so a
        rebuild with fewer pages never overshoots the new document.
        """
        if keep is None:
            return
        _page, x, y = keep

        def apply() -> None:
            try:
                if self._view is None:
                    return
                for scrollbar, value in (
                    (self._view.horizontalScrollBar(), x),
                    (self._view.verticalScrollBar(), y),
                ):
                    scrollbar.setValue(max(0, min(value, scrollbar.maximum())))
                self._update_pages_label()
            except RuntimeError:
                # The view is already deleted when a deferred restore fires
                # during teardown — an unhandled error here would abort the
                # Qt event loop of the print/export tests.
                return

        apply()
        QTimer.singleShot(0, apply)

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
        return view_map.hit_test_anchors(geoms, x_widget, y_widget, self._anchors, tolerance_pt=HIT_TOLERANCE_PT)

    def value_record(self, value_id: ValueId | None) -> ReportValue | None:
        """The document row behind a value id of the last render (PR-4)."""
        if value_id is None or self._document is None:
            return None
        group_index, value_index = value_id
        groups = self._document.groups
        if not (0 <= group_index < len(groups)):
            return None
        values = groups[group_index].values
        if not (0 <= value_index < len(values)):
            return None
        return values[value_index]

    @property
    def hovered_value(self) -> ReportValue | None:
        """The value under the pointer (``None`` when the card is hidden)."""
        return self._card.value

    @property
    def card(self) -> ReportValueCard:
        return self._card

    def set_clip_label_provider(self, provider: ClipLabelProvider | None) -> None:
        """How a clip is named in the card (the window knows the gallery)."""
        self._card.set_clip_label_provider(provider)

    def _install_hover_filter(self) -> None:
        if self._view is not None:
            self._view.viewport().setMouseTracking(True)
            self._view.viewport().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if self._view is not None and watched is self._view.viewport():
            if event.type() == QEvent.Type.MouseMove:
                self._on_hover(event.position().toPoint())
            elif event.type() == QEvent.Type.Leave:
                self._schedule_card_hide()
            elif event.type() == QEvent.Type.MouseButtonPress:
                if not self._handle_value_press(event.position().toPoint(), event.button()):
                    self._hide_card()
            elif event.type() == QEvent.Type.Wheel:
                self._hide_card()
        return super().eventFilter(watched, event)

    def _handle_value_press(self, position: QPoint, button: Qt.MouseButton) -> bool:
        """A left click on a value cell offers «скрыть в отчёте» (item 9).

        Returns ``True`` when the press belonged to a value cell, so the generic
        card hiding does not fight the menu.
        """
        if button != Qt.MouseButton.LeftButton or self._frozen:
            return False
        value = self.value_record(self.value_at(position.x(), position.y()))
        if value is None:
            return False
        menu = self._build_value_menu(value)
        if menu is None:
            return False
        menu.popup(
            self._view.viewport().mapToGlobal(position) if self._view is not None else self.mapToGlobal(position)
        )
        return True

    def _on_hover(self, position: QPoint) -> None:
        """Show the card of the value under the pointer; hide it in the gaps."""
        value_id = self.value_at(position.x(), position.y())
        if value_id is None:
            self._hide_card()
            return
        if value_id == self._hovered and self._card.isVisible():
            return
        value = self.value_record(value_id)
        if value is None:
            self._hide_card()
            return
        self._hovered = value_id
        self._card.show_value(value)
        self._place_card(position)

    def _place_card(self, position: QPoint) -> None:
        """Put the card next to the pointer, clamped inside the preview."""
        viewport = self._view.viewport() if self._view is not None else self
        anchor = viewport.mapTo(self, position)
        size = self._card.sizeHint()
        x = anchor.x() + 18
        if x + size.width() > self.width():
            x = max(0, anchor.x() - size.width() - 18)
        y = anchor.y() + 12
        if y + size.height() > self.height():
            y = max(0, self.height() - size.height() - 4)
        self._card.move(QPoint(x, y))

    def _schedule_card_hide(self) -> None:
        if self._card.isVisible():
            self._hide_timer.start()

    def _cancel_card_hide(self) -> None:
        self._hide_timer.stop()

    def _hide_card(self) -> None:
        self._hide_timer.stop()
        self._hovered = None
        self._card.hide_card()

    # ── toolbar ────────────────────────────────────────────────────

    def _apply_zoom(self) -> None:
        self._hide_card()
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
        try:
            total = self.page_count
            if total <= 0 or self._view is None:
                self._pages_label.setText("")
                return
            current = int(self._view.pageNavigator().currentPage()) + 1
        except RuntimeError:  # the view/document is already gone during teardown
            self._pages_label.setText("")
            return
        self._pages_label.setText(tr("report_mode.page_of", current=current, total=total))

    def _show_status(self, key: str) -> None:
        self._status_key = key
        self._status_label.setText(tr(key) if key else "")
        self._status_label.setVisible(bool(key))

    # ── language and theme ─────────────────────────────────────────

    # ── report format (item 7 of the 2026-11-06 list) ──────────────
    @property
    def profile_id(self) -> str:
        """The format the sheet shows."""
        return self._profile_id

    def set_profile(self, profile_id: str) -> None:
        """Show *profile_id* as the pressed button (the window owns the choice)."""
        self._profile_id = normalize_profile_id(profile_id)
        for candidate, button in self._profile_buttons.items():
            button.setChecked(candidate == self._profile_id)

    def set_inputs_visible(self, visible: bool) -> None:
        """Show the header switch as *visible* without re-emitting the signal."""
        blocked = self._inputs_button.blockSignals(True)
        self._inputs_button.setChecked(bool(visible))
        self._inputs_button.blockSignals(blocked)

    def inputs_visible(self) -> bool:
        """Whether the header switch asks for the «Входные данные» footnote."""
        return self._inputs_button.isChecked()

    def set_profile_locked(self, locked: bool) -> None:
        """A finished version keeps its format until the draft comes back."""
        for button in self._profile_buttons.values():
            button.setEnabled(not locked)
            button.setToolTip(tr("report.profile.locked") if locked else tr("report.profile.tooltip"))
        # The footnote belongs to the finished bytes too: toggling it would
        # contradict the sheet the version was frozen with.
        self._inputs_button.setEnabled(not locked)

    def _build_value_menu(self, value: ReportValue) -> QMenu | None:
        """The «скрыть / вернуть» action of one row (item 9).

        The sheet is exact PDF bytes, so a row is never removed from the
        picture: the window hides it in the document and the sheet is rebuilt.
        """
        if self._frozen or not value.key:
            return None
        action = QMenu(self)
        action.setObjectName("reportValueMenu")
        toggle = action.addAction(tr("report.hide_value"))
        toggle.triggered.connect(lambda _checked=False, key=value.key: self.value_visibility_changed.emit(key, True))
        return action

    def _request_profile(self, profile_id: str) -> None:
        """A click on the segmented row: report it, keep the buttons consistent."""
        if profile_id == self._profile_id:
            self.set_profile(profile_id)
            return
        # The pressed look follows the request; the window decides whether the
        # document really changes and calls ``set_profile`` back.
        self.set_profile(profile_id)
        self.profile_changed.emit(profile_id)

    def reload_text(self) -> None:
        """Re-localize the toolbar (the sheet itself is rebuilt by the window)."""
        self._profile_label.setText(tr("report.format"))
        for profile_id, button in self._profile_buttons.items():
            button.setText(tr(f"report.profile.{profile_id}"))
            button.setToolTip(tr("report.profile.locked") if self._frozen else tr("report.profile.tooltip"))
        # The pressed button is the state, so it survives a re-localisation.
        self.set_profile(self._profile_id)
        self._inputs_button.setText(tr("report.inputs_toggle"))
        self._inputs_button.setToolTip(tr("report.inputs_toggle_hint"))
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
        self._card.reload_text()
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
        self._card.apply_theme()
