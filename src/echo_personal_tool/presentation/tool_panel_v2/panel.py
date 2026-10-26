"""Framework of the measurement panel 2.0 (TP-2, spec 2026-10-15 §4.2).

What this slice implements behind the experimental flag ``tool_panel_v2``
(default on since the TP-2 gate):

* the context segments «Авто / 2D / М / Допплер» with the PW/CW/TDI chip and
  the «по DICOM» source line;
* quick tiles (4) and favourites (1–9) of the current context, taken from the
  version-3 layout with catalog defaults as a fallback; the digits 1–9
  activate the favourites without a mouse (A-03);
* anatomical sections with expandable rows, the «2/9» progress in the header
  and a «скрыто для контекста» line;
* the search field with RU/EN/synonym and wrong-layout matching; Enter
  activates the first result (A-01, A-02);
* arrow traversal of the expanded sections (A-13 keyboard-only path);
* the footer with height, weight, the one BSA of the study and the report
  button;
* the S2 norm card of UI-5 at the rows (400 ms hover or the registry key) and
  the «Нормы» switch of the norm dots (UD-14, UQ-03).

What comes in the next slices: the removal of the old blinking and a
status provider that feeds the row states and the section progress.

The panel emits the same ``action_requested(action, view, phase, extra)``
signal as the old Measures menu (D-09); the window does not learn a second
way to start a measurement.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QFontMetrics, QKeyEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain import tool_settings as settings
from echo_personal_tool.domain.measurement_catalog import CATALOG, ToolSpec
from echo_personal_tool.domain.tool_layout_v3 import Layout, decode_layout, default_layout, migrate_sections
from echo_personal_tool.domain.tool_panel_view import (
    FAVORITES_COUNT,
    PANEL_CONTEXT_2D,
    PANEL_CONTEXT_DOPPLER,
    PANEL_CONTEXT_M,
    PANEL_CONTEXTS,
    PanelView,
    ToolMatch,
    emitted_action,
    favorite_key,
    find_tool_for_action,
    is_vessel_tool,
    needs_doppler_time,
    normalize_doppler_mode,
    normalize_panel_context,
    panel_view,
    resolve_layout_context,
    search_tools,
)
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.theme.token_restyle import TokenRestyleMixin
from echo_personal_tool.presentation.tool_panel_v2.footer import PanelFooter
from echo_personal_tool.presentation.tool_panel_v2.protocol_card import ProtocolCard
from echo_personal_tool.presentation.tool_panel_v2.sections import (
    STATE_DONE,
    STATE_LOCKED,
    STATE_NOT_STARTED,
    STATE_STALE,
    STATE_WARNING,
    TOOL_MIME,
    ToolRow,
    ToolSection,
)
from echo_personal_tool.presentation.ui_animations import HoverButtonMixin

#: The panel of the redesign asks for 320 px and a 280–420 px splitter (§4.2).
PANEL_WIDTH = 320
PANEL_MIN_WIDTH = 280
PANEL_MAX_WIDTH = 420

_CONTEXT_MAX_COLUMNS = len(PANEL_CONTEXTS) + 1
_QUICK_COLUMNS = 2
_FAVORITE_MAX_COLUMNS = 3
_CONTEXT_GRID_SPACING = 2
_CHIP_GRID_SPACING = 4
_CHIP_HORIZONTAL_PADDING = 4
_CHIP_BORDER_WIDTH = 1
_CHIP_TEXT_INSETS = 2 * (_CHIP_HORIZONTAL_PADDING + _CHIP_BORDER_WIDTH)

#: UI-5: the S2 card waits out the pointer travelling from the row to the card
#: before it hides; the same tick watches the card itself.
_CARD_HIDE_GRACE_MS = 250

_CONTEXT_KEYS: Mapping[str, str] = {
    "auto": "panel.context_auto",
    PANEL_CONTEXT_2D: "panel.context_2d",
    PANEL_CONTEXT_M: "panel.context_m",
    PANEL_CONTEXT_DOPPLER: "panel.context_doppler",
}

_MODE_LABELS: Mapping[str, str] = {
    "": "panel.mode_auto",
    "PW": "panel.mode_pw",
    "CW": "panel.mode_cw",
    "TDI": "panel.mode_tdi",
}


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
            continue
        child = item.layout()
        if child is not None:
            _clear_layout(child)


class ToolPanelV2(TokenRestyleMixin, QWidget):
    """Contextual measurement panel; the Measures tab of the tool panel."""

    action_requested = Signal(object, str, str, str)
    patient_metrics_changed = Signal(object, object)
    auto_play_changed = Signal(bool)
    results_requested = Signal()
    doppler_mode_changed = Signal(str)
    #: Protocol card hooks (TP-3 PR-3): the window owns ``ProtocolRunner``.
    protocol_selected = Signal(str)
    protocol_step_activated = Signal(int)
    protocol_stop_requested = Signal()
    #: Footer of the protocol card: (protocol_id, enabled) / skip.
    protocol_auto_advance_toggled = Signal(str, bool)
    protocol_skip_requested = Signal()
    #: UI-5: «Открыть в справочнике» of the S2 card — the window opens S1.
    open_reference_requested = Signal(str)
    #: UI-5: the «Нормы» switch moved (UD-14/UQ-03 — the window remembers it).
    norms_toggled = Signal(bool)
    #: TP-5: the pencil of the panel opens the Tools settings editor.
    edit_requested = Signal(str)
    #: TP-5: in-place editing changed the layout (encoded version-3 document).
    layout_changed = Signal(str)

    #: Lets ``ToolPanel`` pick the implementation without importing it twice.
    is_v2 = True
    #: The panel is wider than the legacy one and accepts a splitter drag.
    preferred_min_width = PANEL_MIN_WIDTH
    preferred_max_width = PANEL_MAX_WIDTH

    def __init__(self, preferences: Any | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolPanelV2")
        self._preferences = preferences
        self._layout_v3: Layout = self._load_layout(preferences)
        self._auto_context: str = PANEL_CONTEXT_2D
        self._manual_context: str | None = None
        self._syncing_mode = False
        self._syncing_context = False
        self._doppler_mode: str = ""
        self._show_hidden = False
        self._edit_mode = False
        self._edit_restore_hidden = False
        self._open_sections: set[str] = set()
        self._rows: dict[str, ToolRow] = {}
        self._row_sections: dict[str, ToolSection] = {}
        self._tile_buttons: dict[str, QPushButton] = {}
        self._quick_buttons: list[QPushButton] = []
        self._favorite_buttons: list[QPushButton] = []
        self._quick_ids: list[str] = []
        self._favorite_ids: list[str] = []
        self._context_columns = 0
        self._favorite_columns = 0
        self._chip_reflow_scheduled = False
        self._highlight_id: str | None = None
        self._time_ok = True
        self._vessel_ok = False
        self._patient_metrics: tuple[float | None, float | None, object] = (None, None, None)
        self._auto_play = bool(getattr(preferences, "auto_play", False))
        self._matches: dict[str, ToolMatch] = {}
        self._last_query = ""
        self._view: PanelView | None = None
        self._section_widgets: list[ToolSection] = []
        self._norms_visible = False
        self._reference_sex_provider: Callable[[], str] = lambda: ""
        self._card_open_connected = False
        self._last_statuses: tuple[Any, ...] = ()
        self._card_hide_timer = QTimer(self)
        self._card_hide_timer.setSingleShot(True)
        self._card_hide_timer.setInterval(_CARD_HIDE_GRACE_MS)
        self._card_hide_timer.timeout.connect(self._hide_card_if_idle)
        # Owned by the panel: a zero-delay chip reflow must be cancelled when the
        # widget is destroyed, otherwise the queued callback touches a deleted
        # QGridLayout (RuntimeError under tests, segfault at shutdown).
        self._chip_reflow_timer = QTimer(self)
        self._chip_reflow_timer.setSingleShot(True)
        self._chip_reflow_timer.timeout.connect(self._reflow_panel_chips)

        self._build()
        self._footer.set_auto_play(self._auto_play)
        self._rebuild()

    # ── Construction ───────────────────────────────────────────────

    def _build(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        self._context_buttons: dict[str, QPushButton] = {}
        self._context_group = QButtonGroup(self)
        self._context_group.setExclusive(True)
        context_row = QGridLayout()
        self._context_grid = context_row
        context_row.setContentsMargins(6, 6, 6, 0)
        context_row.setSpacing(_CONTEXT_GRID_SPACING)
        for index, context in enumerate(("auto", *PANEL_CONTEXTS)):
            button = QPushButton(tr(_CONTEXT_KEYS[context]))
            button.setObjectName("panelContextButton")
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setProperty("_panel_full_text", button.text())
            button.setToolTip(button.text())
            button.setAccessibleName(button.text())
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, c=context: self._on_context_clicked(c))
            self._context_group.addButton(button)
            self._context_buttons[context] = button
            context_row.addWidget(button, 0, index)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(6, 4, 6, 0)
        mode_row.setSpacing(4)
        self._mode_label = QLabel(tr("panel.mode"))
        self._mode_combo = QComboBox()
        self._mode_combo.setObjectName("panelModeCombo")
        self._mode_combo.setMinimumWidth(0)
        self._mode_combo.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        for data in ("", "PW", "CW", "TDI"):
            self._mode_combo.addItem(tr(_MODE_LABELS[data]), data)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._source_label = QLabel()
        self._source_label.setObjectName("panelContextSource")
        self._source_label.setMinimumWidth(0)
        self._source_label.setWordWrap(True)
        self._source_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._source_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mode_row.addWidget(self._mode_label)
        mode_row.addWidget(self._mode_combo)
        mode_row.addWidget(self._source_label, 1)

        self._search = QLineEdit()
        self._search.setObjectName("panelSearch")
        self._search.setPlaceholderText(tr("panel.search_placeholder"))
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(0)
        self._search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._search.textChanged.connect(self._on_search_text_changed)
        self._search.returnPressed.connect(self._activate_first_match)
        self._search.installEventFilter(self)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(6, 4, 6, 4)
        search_row.addWidget(self._search)
        self._search_hint = QLabel("/")
        self._search_hint.setObjectName("panelSearchHint")
        self._search_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._search_hint.setFixedWidth(18)
        search_row.addWidget(self._search_hint)
        self._edit_button = QPushButton("✎")
        self._edit_button.setObjectName("panelEditButton")
        self._edit_button.setToolTip(tr("panel.edit_tools"))
        self._edit_button.setAccessibleName(tr("panel.edit_tools"))
        self._edit_button.setFixedWidth(24)
        self._edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_button.clicked.connect(self._on_edit_clicked)
        search_row.addWidget(self._edit_button)

        # ── Content page: quick, favourites, hidden line, sections ──
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(2)

        self._quick_box = self._group_box("panel.quick")
        self._quick_grid = QGridLayout()
        self._quick_grid.setContentsMargins(6, 0, 6, 4)
        self._quick_grid.setSpacing(_CHIP_GRID_SPACING)
        self._quick_box.layout().addLayout(self._quick_grid)  # type: ignore[union-attr]
        content_layout.addWidget(self._quick_box)

        self._favorites_box = self._group_box("panel.favorites")
        self._favorites_grid = QGridLayout()
        self._favorites_grid.setContentsMargins(6, 0, 6, 4)
        self._favorites_grid.setSpacing(_CHIP_GRID_SPACING)
        self._favorites_box.layout().addLayout(self._favorites_grid)  # type: ignore[union-attr]
        content_layout.addWidget(self._favorites_box)

        for drop_zone in (self._quick_box, self._favorites_box):
            drop_zone.setAcceptDrops(True)
            drop_zone.installEventFilter(self)

        self._protocol_card = ProtocolCard(self._language())
        self._protocol_card.protocol_selected.connect(self.protocol_selected.emit)
        self._protocol_card.step_activated.connect(self.protocol_step_activated.emit)
        self._protocol_card.stop_requested.connect(self.protocol_stop_requested.emit)
        self._protocol_card.auto_advance_toggled.connect(self.protocol_auto_advance_toggled.emit)
        self._protocol_card.skip_requested.connect(self.protocol_skip_requested.emit)
        content_layout.addWidget(self._protocol_card)

        hidden_row = QHBoxLayout()
        hidden_row.setContentsMargins(6, 0, 6, 2)
        self._hidden_label = QLabel()
        self._hidden_label.setWordWrap(True)
        self._hidden_label.setMinimumWidth(0)
        self._hidden_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._hidden_label.setObjectName("panelHiddenLabel")
        self._hidden_toggle = QPushButton()
        self._hidden_toggle.setObjectName("panelHiddenToggle")
        self._hidden_toggle.setMinimumWidth(0)
        self._hidden_toggle.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._hidden_toggle.setFlat(True)
        self._hidden_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hidden_toggle.clicked.connect(self._toggle_hidden)
        hidden_row.addWidget(self._hidden_label, 1)
        hidden_row.addWidget(self._hidden_toggle)
        self._hidden_row = QWidget()
        self._hidden_row.setLayout(hidden_row)
        content_layout.addWidget(self._hidden_row)

        # UI-5 (UD-14, UQ-03): the «Нормы» switch over the list — the norm dots
        # are off by default and the window remembers the position.
        norms_row = QHBoxLayout()
        norms_row.setContentsMargins(6, 0, 6, 2)
        norms_row.addStretch(1)
        self._norms_check = QCheckBox(tr("panel.norms"))
        self._norms_check.setObjectName("panelNormsCheck")
        self._norms_check.setToolTip(tr("panel.norms_hint"))
        self._norms_check.toggled.connect(self._on_norms_toggled)
        norms_row.addWidget(self._norms_check)
        content_layout.addLayout(norms_row)

        self._sections_host = QWidget()
        self._sections_host.setMinimumWidth(0)
        self._sections_layout = QVBoxLayout(self._sections_host)
        self._sections_layout.setContentsMargins(4, 0, 4, 4)
        self._sections_layout.setSpacing(1)
        content_layout.addWidget(self._sections_host, 1)

        # Quick tiles, favourites, the hidden-tools toggle and the sections
        # share one vertical viewport. At short/high-DPI window sizes the page
        # scrolls instead of clipping controls above a sections-only scrollbar.
        content.setMinimumWidth(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setWidget(content)
        self._scroll_viewport = self._scroll.viewport()
        self._scroll_viewport.installEventFilter(self)

        # ── Search results page ─────────────────────────────────────
        self._results = QListWidget()
        self._results.setObjectName("panelSearchResults")
        self._results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._results.itemClicked.connect(self._on_result_clicked)
        self._results.itemActivated.connect(self._on_result_clicked)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._scroll)
        self._stack.addWidget(self._results)

        self._footer = PanelFooter()
        self._footer.metrics_changed.connect(self._on_metrics_changed)
        self._footer.auto_play_changed.connect(self._on_auto_play_changed)
        self._footer.report_requested.connect(self.results_requested.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(context_row)
        layout.addLayout(mode_row)
        layout.addLayout(search_row)
        layout.addWidget(self._stack, 1)
        layout.addWidget(self._footer)
        self._apply_style()

    def _group_box(self, title_key: str) -> QWidget:
        from echo_personal_tool.infrastructure.i18n import tr

        box = QWidget()
        box.setObjectName("panelGroup")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 2, 0, 0)
        box_layout.setSpacing(2)
        label = QLabel(tr(title_key))
        label.setObjectName("panelGroupTitle")
        box_layout.addWidget(label)
        return box

    def _apply_style(self) -> None:
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"""
            #toolPanelV2 {{
                background: {tokens["surface.1"]};
            }}
            #toolPanelV2 QLabel {{
                color: {tokens["text.2"]};
            }}
            #panelContextButton {{
                min-height: 24px;
                padding: 2px {_CHIP_HORIZONTAL_PADDING}px;
                border: {_CHIP_BORDER_WIDTH}px solid {tokens["line.2"]};
                border-radius: 4px;
                background: {tokens["surface.2"]};
                color: {tokens["text.2"]};
            }}
            #panelContextButton:hover {{
                background: {tokens["surface.3"]};
            }}
            #panelContextButton:checked {{
                /* The fill of a chosen chip is the deep selection of the
                   mockup, not the full accent: the accent is the push button
                   and the focus ring, and a chip filled with it shouted
                   louder than the one control that submits. */
                background: {tokens["accent.selected"]};
                color: {tokens["text.1"]};
                border-color: {tokens["accent.selected"]};
            }}
            #panelModeCombo, #panelSearch {{
                min-height: 24px;
                border: 1px solid {tokens["line.2"]};
                border-radius: 4px;
                background: {tokens["surface.2"]};
                color: {tokens["text.1"]};
                padding: 1px 4px;
            }}
            #panelSearch:focus {{
                border-color: {tokens["focus.ring"]};
            }}
            #panelSearchHint {{
                color: {tokens["text.3"]};
                border: 1px solid {tokens["line.1"]};
                border-radius: 3px;
            }}
            #panelGroupTitle {{
                color: {tokens["text.3"]};
                padding: 0 6px;
            }}
            #panelHiddenLabel {{
                color: {tokens["text.3"]};
            }}
            #panelHiddenToggle {{
                color: {tokens["accent.text"]};
                border: none;
                padding: 0 2px;
            }}
            #panelNormsCheck {{
                color: {tokens["text.2"]};
            }}
            #panelSearchResults {{
                border: none;
                background: {tokens["surface.1"]};
                color: {tokens["text.1"]};
            }}
            #panelSearchResults::item {{
                padding: 4px;
            }}
            #panelSearchResults::item:selected {{
                background: {tokens["surface.3"]};
                color: {tokens["text.1"]};
            }}
            #panelTileButton, #panelFavoriteButton {{
                min-height: 26px;
                padding: 2px {_CHIP_HORIZONTAL_PADDING}px;
                border: {_CHIP_BORDER_WIDTH}px solid {tokens["line.1"]};
                border-radius: 4px;
                background: {tokens["surface.2"]};
                color: {tokens["text.1"]};
                text-align: left;
            }}
            #panelTileButton:hover, #panelFavoriteButton:hover {{
                background: {tokens["surface.3"]};
                border-color: {tokens["line.2"]};
            }}
            #panelTileButton:disabled, #panelFavoriteButton:disabled {{
                color: {tokens["text.disabled"]};
            }}
            """
        )
        self.refresh_norm_colors()

    # ── Layout document ────────────────────────────────────────────

    @staticmethod
    def _load_layout(preferences: Any | None) -> Layout:
        raw = getattr(preferences, "tool_layout_v3_json", "") if preferences is not None else ""
        layout = decode_layout(raw)
        if layout is not None:
            return layout
        # A user who customized the panel before TP-0 PR-2 has only the
        # version-2 key; migrate it here instead of showing the defaults.
        from echo_personal_tool.presentation.measures_menu import decode_tool_layout

        legacy = getattr(preferences, "tool_panel_layout_json", "") if preferences is not None else ""
        sections = decode_tool_layout(legacy)
        if sections:
            return migrate_sections(sections)
        return default_layout()

    def set_preferences(self, preferences: Any | None) -> None:
        """Adopt a new preference object (settings applied, language changed)."""
        self._preferences = preferences
        self._layout_v3 = self._load_layout(preferences)
        self._auto_play = bool(getattr(preferences, "auto_play", False))
        self._apply_style()
        self._footer._apply_style()
        self._footer.set_auto_play(self._auto_play)
        self._rebuild()

    def rebuild_with_preferences(self, preferences: Any | None) -> None:
        self.set_preferences(preferences)

    # ── State ──────────────────────────────────────────────────────

    def preferences(self) -> Any | None:
        return self._preferences

    def _ai_available(self) -> bool:
        from echo_personal_tool.application.profile_settings import get_profile_capabilities

        return get_profile_capabilities().ai_segmentation

    def effective_context(self) -> str:
        return self._manual_context or self._auto_context

    def context(self) -> str:
        return self.effective_context()

    def set_view_context(self, context: str | None, doppler_mode: str | None = None) -> None:
        """Feed the viewer's context; a manual segment keeps its choice."""
        normalized = normalize_panel_context(context)
        changed = normalized != self._auto_context
        self._auto_context = normalized
        mode = normalize_doppler_mode(doppler_mode)
        mode_changed = mode != self._doppler_mode
        self._doppler_mode = mode
        if mode_changed:
            self._sync_mode_combo()
        if changed or mode_changed:
            self._rebuild()
        else:
            self._sync_controls()

    def reset_context_override(self) -> None:
        """Back to «Авто» — called when the clip changes (§4.2)."""
        if self._manual_context is None:
            return
        self._manual_context = None
        self._rebuild()

    def set_doppler_mode(self, mode: str | None) -> None:
        """Reflect the resolved mode of the viewer without emitting it back."""
        normalized = normalize_doppler_mode(mode)
        if normalized == self._doppler_mode:
            return
        self._doppler_mode = normalized
        self._sync_mode_combo()
        self._rebuild()

    def doppler_mode(self) -> str:
        return self._doppler_mode

    def show_hidden_tools(self) -> bool:
        return self._show_hidden

    def _on_context_clicked(self, context: str) -> None:
        if context == "auto":
            self._manual_context = None
        else:
            self._manual_context = normalize_panel_context(context)
        self._rebuild()

    def _on_mode_changed(self) -> None:
        if self._syncing_mode:
            return
        mode = str(self._mode_combo.currentData() or "")
        self.doppler_mode_changed.emit(mode)
        self._doppler_mode = normalize_doppler_mode(mode)
        self._rebuild()

    def _sync_mode_combo(self) -> None:
        self._syncing_mode = True
        try:
            index = self._mode_combo.findData(self._doppler_mode.upper())
            self._mode_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self._syncing_mode = False

    def _sync_controls(self) -> None:
        """Update selection/source without rebuilding the sections."""
        self._syncing_context = True
        try:
            effective = self.effective_context()
            for context, button in self._context_buttons.items():
                button.setEnabled(True)
                button.setChecked(context == ("auto" if self._manual_context is None else effective))
        finally:
            self._syncing_context = False
        self._mode_combo.setEnabled(self.effective_context() == PANEL_CONTEXT_DOPPLER)
        self._mode_label.setEnabled(self.effective_context() == PANEL_CONTEXT_DOPPLER)
        self._source_label.setText(self._source_text())

    def _source_text(self) -> str:
        from echo_personal_tool.infrastructure.i18n import tr

        if self._manual_context is not None:
            return tr("panel.context_source_manual")
        if self.effective_context() != PANEL_CONTEXT_DOPPLER:
            return tr("panel.context_source_auto")
        mode = self._doppler_mode.upper()
        if not mode:
            return tr("panel.context_source_auto")
        return tr("panel.context_source_dicom", mode=mode)

    def _context_title(self, context: str) -> str:
        from echo_personal_tool.infrastructure.i18n import tr

        return tr(_CONTEXT_KEYS.get(context, "panel.context_2d"))

    def _toggle_hidden(self) -> None:
        self._show_hidden = not self._show_hidden
        self._rebuild()

    # ── Building the view ──────────────────────────────────────────

    def _rebuild(self) -> None:
        from echo_personal_tool.infrastructure.i18n import get_language

        language = get_language()
        view = panel_view(
            self._layout_v3,
            self.effective_context(),
            doppler_mode=self._doppler_mode,
            language=language,
            preferences=self._preferences,
            ai_available=self._ai_available(),
            show_hidden=self._show_hidden,
        )
        self._view = view
        self._rows = {}
        self._row_sections = {}
        self._tile_buttons = {}
        self._quick_buttons = []
        self._favorite_buttons = []
        self._quick_ids = []
        self._favorite_ids = []
        self._favorite_columns = 0
        self._section_widgets = []

        self._rebuild_quick(view, language)
        self._rebuild_favorites(view, language)
        self._rebuild_hidden_line(view)
        self._rebuild_sections(view, language)
        self._sync_controls()
        self._apply_availability()
        self._restore_highlight()
        self.hide_reference_card()
        if self._last_statuses:
            # Rows are new: values, norm dots and states come back from the
            # statuses the protocol session pushed last (a rebuild is not a
            # new study).
            self.set_tool_statuses(self._last_statuses)
        if self._last_query:
            self._run_search(self._last_query)
        self._schedule_chip_reflow()

    def _rebuild_quick(self, view: PanelView, language: str) -> None:
        _clear_layout(self._quick_grid)
        if not view.quick:
            self._quick_box.setVisible(False)
            return
        self._quick_box.setVisible(True)
        for index, tool in enumerate(view.quick):
            label = tool.label(language)
            display_text = self._tile_text(tool, language, tool.default_key)
            button = QPushButton(display_text)
            button.setObjectName("panelTileButton")
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setProperty("_panel_full_text", display_text)
            button.setToolTip(self._tooltip(tool, language))
            button.setAccessibleName(f"{label.full} ({tool.default_key})" if tool.default_key else label.full)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, tool_id=tool.id: self._on_quick_tile_clicked(tool_id))
            HoverButtonMixin.install(button)
            self._quick_grid.addWidget(button, index // _QUICK_COLUMNS, index % _QUICK_COLUMNS)
            self._quick_buttons.append(button)
            self._quick_ids.append(tool.id)
            self._tile_buttons[tool.id] = button
            if self._edit_mode:
                from echo_personal_tool.infrastructure.i18n import tr

                hint = tr("panel.edit_remove_quick")
                button.setToolTip(hint)
                button.setAccessibleName(hint)

    def _rebuild_favorites(self, view: PanelView, language: str) -> None:
        _clear_layout(self._favorites_grid)
        if not view.favorites:
            self._favorites_box.setVisible(False)
            return
        self._favorites_box.setVisible(True)
        for index, tool in enumerate(view.favorites[:FAVORITES_COUNT]):
            key = favorite_key(index)
            label = tool.label(language)
            display_text = self._tile_text(tool, language, key)
            button = QPushButton(display_text)
            button.setObjectName("panelFavoriteButton")
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setProperty("_panel_full_text", display_text)
            button.setToolTip(self._tooltip(tool, language))
            button.setAccessibleName(f"{label.full} ({key})" if key else label.full)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, tool_id=tool.id: self._on_favorite_tile_clicked(tool_id))
            HoverButtonMixin.install(button)
            self._favorites_grid.addWidget(button, index // _FAVORITE_MAX_COLUMNS, index % _FAVORITE_MAX_COLUMNS)
            self._favorite_buttons.append(button)
            self._favorite_ids.append(tool.id)
            self._tile_buttons[tool.id] = button
            if self._edit_mode:
                from echo_personal_tool.infrastructure.i18n import tr

                hint = tr("panel.edit_remove_favorite")
                button.setToolTip(hint)
                button.setAccessibleName(hint)

    def _rebuild_hidden_line(self, view: PanelView) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        if not view.hidden_count:
            self._hidden_row.setVisible(False)
            return
        self._hidden_row.setVisible(True)
        title = self._context_title(self.effective_context())
        self._hidden_label.setText(tr("panel.hidden_for", context=title, count=view.hidden_count))
        toggle_text = tr("panel.hide_hidden") if self._show_hidden else tr("panel.show_hidden")
        self._hidden_toggle.setText(toggle_text)
        self._hidden_toggle.setToolTip(toggle_text)
        self._hidden_toggle.setAccessibleName(toggle_text)

    def _schedule_chip_reflow(self) -> None:
        """Reflow header chips after the panel has received its new geometry/font."""
        if not hasattr(self, "_chip_reflow_scheduled") or self._chip_reflow_scheduled:
            return
        self._chip_reflow_scheduled = True
        self._chip_reflow_timer.start(0)

    def _grid_available_width(self, layout: QGridLayout) -> int:
        width = layout.geometry().width()
        if width <= 0:
            parent = layout.parentWidget()
            width = parent.width() if parent is not None else self.width()
        margins = layout.contentsMargins()
        return max(0, width - margins.left() - margins.right())

    def _columns_for_texts(
        self,
        texts: list[str],
        *,
        available_width: int,
        max_columns: int,
        spacing: int,
    ) -> int:
        if not texts:
            return 0
        if available_width <= 0:
            return max_columns
        metrics = QFontMetrics(self.font())
        minimum_cell_width = max(metrics.horizontalAdvance(text) + _CHIP_TEXT_INSETS for text in texts)
        for columns in range(max_columns, 0, -1):
            if columns * minimum_cell_width + (columns - 1) * spacing <= available_width:
                return columns
        return 1

    @staticmethod
    def _place_grid_widgets(layout: QGridLayout, widgets: list[QPushButton], columns: int, current: int) -> int:
        if not widgets or columns <= 0 or columns == current:
            return current
        for button in widgets:
            layout.removeWidget(button)
        for index, button in enumerate(widgets):
            layout.addWidget(button, index // columns, index % columns)
        return columns

    def _elide_grid_buttons(
        self,
        buttons: list[QPushButton],
        *,
        columns: int,
        available_width: int,
        spacing: int,
    ) -> None:
        if not buttons or columns <= 0 or available_width <= 0:
            return
        cell_width = max(0, (available_width - spacing * (columns - 1)) // columns)
        text_width = max(0, cell_width - _CHIP_TEXT_INSETS)
        for button in buttons:
            full_text = button.property("_panel_full_text")
            if not isinstance(full_text, str):
                continue
            display_text = button.fontMetrics().elidedText(full_text, Qt.TextElideMode.ElideRight, text_width)
            if button.text() != display_text:
                button.setText(display_text)

    def _reflow_panel_chips(self) -> None:
        """Use fewer columns at narrow/high-DPI widths; retain full labels accessibly."""
        self._chip_reflow_scheduled = False
        if not hasattr(self, "_context_grid") or not hasattr(self, "_favorites_grid"):
            return
        try:
            self._apply_chip_reflow()
        except RuntimeError:
            # The zero-timer callback can outlive the widget tree: Python
            # wrappers survive their C++ grids/chips, so touching the deleted
            # objects raises. There is nothing left to reflow.
            return

    def _apply_chip_reflow(self) -> None:
        context_buttons = list(self._context_buttons.values())
        context_width = self._grid_available_width(self._context_grid)
        context_labels = [str(button.property("_panel_full_text") or button.text()) for button in context_buttons]
        self._context_columns = self._place_grid_widgets(
            self._context_grid,
            context_buttons,
            self._columns_for_texts(
                context_labels,
                available_width=context_width,
                max_columns=_CONTEXT_MAX_COLUMNS,
                spacing=_CONTEXT_GRID_SPACING,
            ),
            self._context_columns,
        )
        self._elide_grid_buttons(
            context_buttons,
            columns=self._context_columns,
            available_width=context_width,
            spacing=_CONTEXT_GRID_SPACING,
        )

        quick_width = self._grid_available_width(self._quick_grid)
        self._elide_grid_buttons(
            self._quick_buttons,
            columns=_QUICK_COLUMNS,
            available_width=quick_width,
            spacing=_CHIP_GRID_SPACING,
        )

        favorite_width = self._grid_available_width(self._favorites_grid)
        favorite_labels = [
            str(button.property("_panel_full_text") or button.text()) for button in self._favorite_buttons
        ]
        self._favorite_columns = self._place_grid_widgets(
            self._favorites_grid,
            self._favorite_buttons,
            self._columns_for_texts(
                favorite_labels,
                available_width=favorite_width,
                max_columns=_FAVORITE_MAX_COLUMNS,
                spacing=_CHIP_GRID_SPACING,
            ),
            self._favorite_columns,
        )
        self._elide_grid_buttons(
            self._favorite_buttons,
            columns=self._favorite_columns,
            available_width=favorite_width,
            spacing=_CHIP_GRID_SPACING,
        )

    def _rebuild_sections(self, view: PanelView, language: str) -> None:
        _clear_layout(self._sections_layout)
        if not view.sections:
            self._sections_layout.addStretch(1)
            return
        default_open = view.sections[0].key
        favorites = {tool.id for tool in view.favorites}
        for block in view.sections:
            rows: list[ToolRow] = []
            for tool in block.items:
                row = ToolRow(tool, language)
                row.activated.connect(self._activate_tool)
                row.reference_requested.connect(self._on_row_reference_requested)
                row.reference_hide_requested.connect(self._on_row_reference_hide)
                row.pointer_entered.connect(self._on_row_pointer_entered)
                row.edit_favorite_requested.connect(self._on_edit_favorite)
                row.edit_visibility_requested.connect(self._on_edit_visibility)
                row.set_norms_visible(self._norms_visible)
                row.set_edit_mode(
                    self._edit_mode,
                    favorite=tool.id in favorites,
                    visible=self._tool_visible(tool.id),
                )
                rows.append(row)
                self._rows[tool.id] = row
            expanded = block.key in self._open_sections
            if block.key not in self._open_sections and block.key == default_open and not self._open_sections:
                expanded = True
            section = ToolSection(block.key, block.title, rows, expanded=expanded or self._edit_mode)
            section.toggled.connect(lambda opened, key=block.key: self._remember_section(key, opened))
            section.tool_dropped.connect(lambda tool_id, index, key=block.key: self._on_edit_drop(tool_id, key, index))
            section.set_edit_mode(self._edit_mode)
            self._section_widgets.append(section)
            self._sections_layout.addWidget(section)
            for row in rows:
                self._row_sections[row.tool.id] = section
        self._sections_layout.addStretch(1)

    def _remember_section(self, key: str, opened: bool) -> None:
        if opened:
            self._open_sections.add(key)
        else:
            self._open_sections.discard(key)

    # ── In-place editing (TP-5) ────────────────────────────────────

    def edit_mode(self) -> bool:
        return self._edit_mode

    def set_edit_mode(self, enabled: bool) -> None:
        """Switch the panel to the same-model editing preview (spec §7)."""
        enabled = bool(enabled)
        if enabled == self._edit_mode:
            return
        self._edit_mode = enabled
        if enabled:
            self._edit_restore_hidden = self._show_hidden
            self._show_hidden = True
        else:
            self._show_hidden = self._edit_restore_hidden
        self._sync_edit_button()
        self._rebuild()

    def _on_edit_clicked(self) -> None:
        profile = self._layout_v3.profile()
        if profile is None or settings.is_builtin_profile(profile):
            self.edit_requested.emit(self.effective_context())
            return
        self.set_edit_mode(not self._edit_mode)

    def _sync_edit_button(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        text = "✓" if self._edit_mode else "✎"
        hint = tr("panel.edit_done") if self._edit_mode else tr("panel.edit_tools")
        self._edit_button.setText(text)
        self._edit_button.setToolTip(hint)
        self._edit_button.setAccessibleName(hint)

    def _tool_visible(self, tool_id: str) -> bool:
        context = resolve_layout_context(self._layout_v3, self.effective_context())
        if context is None:
            return True
        for block in context.sections:
            for item in block.items:
                if item.id == tool_id:
                    return item.visible
        return True

    def _apply_edit_layout(self, layout: Layout) -> None:
        self._layout_v3 = layout
        self._rebuild()
        self.layout_changed.emit(settings.export_layout(layout))

    def _on_edit_favorite(self, tool_id: str) -> None:
        favorites = [tool.id for tool in self._view.favorites] if self._view is not None else []
        if tool_id in favorites:
            favorites.remove(tool_id)
        elif len(favorites) < FAVORITES_COUNT:
            favorites.append(tool_id)
        else:
            return
        self._apply_edit_layout(settings.set_context_favorites(self._layout_v3, self.effective_context(), favorites))

    def _on_edit_visibility(self, tool_id: str) -> None:
        visible = self._tool_visible(tool_id)
        layout = settings.set_tool_visible(self._layout_v3, self.effective_context(), tool_id, not visible)
        if visible:
            layout = self._remove_from_tiles(layout, tool_id)
        self._apply_edit_layout(layout)

    def _remove_from_tiles(self, layout: Layout, tool_id: str) -> Layout:
        context = self.effective_context()
        if tool_id in self._quick_ids:
            quick = [item for item in self._quick_ids if item != tool_id]
            layout = settings.set_context_quick(layout, context, quick)
        if tool_id in self._favorite_ids:
            favorites = [item for item in self._favorite_ids if item != tool_id]
            layout = settings.set_context_favorites(layout, context, favorites)
        return layout

    def _on_edit_drop(self, tool_id: str, section_key: str, index: int) -> None:
        self._apply_edit_layout(
            settings.move_tool(self._layout_v3, self.effective_context(), tool_id, section_key, index=index)
        )

    def _on_quick_tile_clicked(self, tool_id: str) -> None:
        if not self._edit_mode:
            self._activate_tool(tool_id)
            return
        quick = [item for item in self._quick_ids if item != tool_id]
        self._apply_edit_layout(settings.set_context_quick(self._layout_v3, self.effective_context(), quick))

    def _on_favorite_tile_clicked(self, tool_id: str) -> None:
        if not self._edit_mode:
            self._activate_tool(tool_id)
            return
        favorites = [item for item in self._favorite_ids if item != tool_id]
        self._apply_edit_layout(settings.set_context_favorites(self._layout_v3, self.effective_context(), favorites))

    def _on_edit_quick_drop(self, tool_id: str) -> None:
        if tool_id in self._quick_ids or len(self._quick_ids) >= 4:
            return
        quick = [*self._quick_ids, tool_id]
        self._apply_edit_layout(settings.set_context_quick(self._layout_v3, self.effective_context(), quick))

    def _on_edit_favorite_drop(self, tool_id: str) -> None:
        if tool_id in self._favorite_ids or len(self._favorite_ids) >= FAVORITES_COUNT:
            return
        favorites = [*self._favorite_ids, tool_id]
        self._apply_edit_layout(settings.set_context_favorites(self._layout_v3, self.effective_context(), favorites))

    def _tile_text(self, tool: ToolSpec, language: str, badge: str) -> str:
        label = tool.label(language).short
        return f"{label}  ·  {badge}" if badge else label

    def _tooltip(self, tool: ToolSpec, language: str) -> str:
        label = tool.label(language)
        return label.full

    # ── Availability ───────────────────────────────────────────────

    def set_doppler_tool_availability(self, *, time_ok: bool, vessel_ok: bool = False) -> None:
        """Disable the tools the current clip cannot run (same gates as today)."""
        self._time_ok = bool(time_ok)
        self._vessel_ok = bool(vessel_ok)
        self._apply_availability()

    def _tool_available(self, tool: ToolSpec) -> bool:
        if is_vessel_tool(tool):
            return self._vessel_ok
        if needs_doppler_time(tool):
            return self._time_ok
        return True

    def _apply_availability(self) -> None:
        for tool_id, row in self._rows.items():
            tool = CATALOG.get(tool_id)
            row.set_available(True if tool is None else self._tool_available(tool))
        for tool_id, button in self._tile_buttons.items():
            tool = CATALOG.get(tool_id)
            button.setEnabled(True if tool is None else self._tool_available(tool))

    # ── Activation and highlight ───────────────────────────────────

    def activate_tool(self, tool_id: str) -> None:
        """Activate a tool by id (the protocol step drives this, TP-3 PR-3)."""
        self._activate_tool(tool_id)

    def _activate_tool(self, tool_id: str) -> None:
        from echo_personal_tool.presentation.measurement_action import MeasurementAction

        tool = CATALOG.get(tool_id)
        if tool is None or not self._tool_available(tool):
            return
        emitted = emitted_action(tool)
        try:
            action = MeasurementAction(emitted.action)
        except ValueError:
            return
        self.action_requested.emit(action, emitted.view, emitted.phase, emitted.extra)

    def _activate_first_match(self) -> None:
        item = self._results.item(0)
        if item is None:
            return
        tool_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(tool_id, str) and tool_id:
            self._activate_tool(tool_id)
            self._clear_search()

    def highlight_action(self, action, *, view: str = "A4C", phase: str = "ED") -> None:
        """Mark the tool of the next step — a static marker, not the old blink."""
        self.clear_action_highlight()
        tools = [row.tool for row in self._rows.values()]
        target = find_tool_for_action(tools, str(action), view=view, phase=phase)
        if target is None:
            return
        self._highlight_id = target.id
        row = self._rows.get(target.id)
        if row is None:
            return
        row.set_active(True)
        section = self._row_sections.get(target.id)
        if section is not None and not section.is_expanded():
            section.set_expanded(True)
        self._scroll_to_row(row)

    def highlight_tool(self, tool_id: str) -> None:
        """Mark the row of an armed protocol step by its catalogue id (TP-3 PR-3).

        The protocol step knows the tool directly, so it does not go through the
        action lookup the menu uses.
        """
        self.clear_action_highlight()
        row = self._rows.get(tool_id)
        if row is None:
            return
        self._highlight_id = tool_id
        row.set_active(True)
        section = self._row_sections.get(tool_id)
        if section is not None and not section.is_expanded():
            section.set_expanded(True)
        self._scroll_to_row(row)

    def clear_action_highlight(self) -> None:
        if self._highlight_id is not None:
            row = self._rows.get(self._highlight_id)
            if row is not None:
                row.set_active(False)
        self._highlight_id = None

    def _restore_highlight(self) -> None:
        if self._highlight_id is None:
            return
        row = self._rows.get(self._highlight_id)
        if row is not None:
            row.set_active(True)

    def _scroll_to_row(self, row: ToolRow) -> None:
        from PySide6.QtCore import QTimer

        def scroll() -> None:
            self._scroll.ensureWidgetVisible(row, 0, 8)

        QTimer.singleShot(0, scroll)

    # ── Search ─────────────────────────────────────────────────────

    def _on_search_text_changed(self, text: str) -> None:
        query = text.strip()
        self._last_query = query
        if not query:
            self._stack.setCurrentIndex(0)
            return
        self._run_search(query)

    def _run_search(self, query: str) -> None:
        from echo_personal_tool.infrastructure.i18n import get_language, tr

        language = get_language()
        matches = search_tools(
            query,
            self._layout_v3,
            self.effective_context(),
            doppler_mode=self._doppler_mode,
            language=language,
            preferences=self._preferences,
            ai_available=self._ai_available(),
        )
        self._matches = {match.tool.id: match for match in matches}
        self._results.clear()
        if not matches:
            item = QListWidgetItem(tr("panel.search_no_results"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._results.addItem(item)
        else:
            for match in matches:
                item = QListWidgetItem(match.label)
                item.setData(Qt.ItemDataRole.UserRole, match.tool.id)
                item.setToolTip(self._tooltip(match.tool, language))
                self._results.addItem(item)
        self._stack.setCurrentWidget(self._results)

    def _on_result_clicked(self, item: QListWidgetItem) -> None:
        tool_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(tool_id, str) or not tool_id:
            return
        self._activate_tool(tool_id)
        self._clear_search()

    def _clear_search(self) -> None:
        self._last_query = ""
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._stack.setCurrentIndex(0)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj in (self._quick_box, self._favorites_box) and self._edit_mode:
            if isinstance(event, (QDragEnterEvent, QDragMoveEvent)) and event.mimeData().hasFormat(TOOL_MIME):
                event.acceptProposedAction()
                return True
            if isinstance(event, QDropEvent) and event.mimeData().hasFormat(TOOL_MIME):
                tool_id = bytes(event.mimeData().data(TOOL_MIME)).decode("utf-8")
                if obj is self._quick_box:
                    self._on_edit_quick_drop(tool_id)
                else:
                    self._on_edit_favorite_drop(tool_id)
                event.acceptProposedAction()
                return True
        if obj is getattr(self, "_scroll_viewport", None) and event.type() == QEvent.Type.Resize:
            self._schedule_chip_reflow()
        if obj is self._search and event.type() == QEvent.Type.KeyPress:
            key_event = event if isinstance(event, QKeyEvent) else None
            if key_event is not None:
                if key_event.key() == Qt.Key.Key_Down and self._results.count():
                    self._results.setFocus(Qt.FocusReason.ShortcutFocusReason)
                    self._results.setCurrentRow(0)
                    return True
                if key_event.key() == Qt.Key.Key_Escape:
                    self._clear_search()
                    return True
        return super().eventFilter(obj, event)

    # ── Keyboard (A-03: 1–9; A-13: arrow traversal) ────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if not self._search.hasFocus():
            key = event.key()
            if Qt.Key.Key_1 <= key <= Qt.Key.Key_9 and self._activate_favorite(key - Qt.Key.Key_1):
                event.accept()
                return
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move_row_focus(1 if key == Qt.Key.Key_Down else -1)
                event.accept()
                return
        super().keyPressEvent(event)

    def activate_favorite(self, index: int) -> bool:
        """Activate the one-based favourites slot ``index`` (zero-based API).

        Returns ``False`` when the current context has no favourite at that
        position or its tool is unavailable. The main-window digit shortcuts
        use this entry point while the viewer, rather than the panel, has focus.
        """
        view = self._view
        if view is None or not 0 <= index < len(view.favorites):
            return False
        tool = view.favorites[index]
        if not self._tool_available(tool):
            return False
        self._activate_tool(tool.id)
        return True

    def _activate_favorite(self, index: int) -> bool:
        """Compatibility wrapper for the panel's own digit key handler."""
        return self.activate_favorite(index)

    def _move_row_focus(self, delta: int) -> None:
        """Focus the previous/next row of the expanded sections (wrapping)."""
        order: list[ToolRow] = []
        for section in self._section_widgets:
            if section.is_expanded():
                order.extend(section.rows())
        if not order:
            return
        current = QApplication.focusWidget()
        index = next(
            (position for position, row in enumerate(order) if row is current),
            -1,
        )
        target = order[(index + delta) % len(order)] if index >= 0 else order[0 if delta > 0 else -1]
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        self._scroll_to_row(target)

    # ── Footer forwarding ──────────────────────────────────────────

    def set_patient_metrics(
        self,
        height_cm: float | None,
        weight_kg: float | None,
        bsa_basis: object = None,
    ) -> None:
        self._patient_metrics = (height_cm, weight_kg, bsa_basis)
        self._footer.set_patient_metrics(height_cm, weight_kg, bsa_basis)

    def set_auto_play(self, enabled: bool) -> None:
        self._auto_play = bool(enabled)
        self._footer.set_auto_play(self._auto_play)

    def auto_play(self) -> bool:
        return self._footer.auto_play()

    def _on_metrics_changed(self, height_cm: object, weight_kg: object) -> None:
        height = float(height_cm) if height_cm is not None else None
        weight = float(weight_kg) if weight_kg is not None else None
        self._patient_metrics = (height, weight, None)
        self.patient_metrics_changed.emit(height_cm, weight_kg)

    def _on_auto_play_changed(self, enabled: bool) -> None:
        self._auto_play = bool(enabled)
        self.auto_play_changed.emit(self._auto_play)

    def set_measurement_count(self, count: int | None) -> None:
        """Reserved for «Отчёт · N измерений» (TP-2 PR-2 wires the count)."""
        self._footer.set_measurement_count(count)

    # ── Protocol card (TP-3 PR-3) ──────────────────────────────────

    def set_protocols(self, protocols: Iterable[Any]) -> None:
        """Fill the card chooser with the protocols of the catalogue."""
        self._protocol_card.set_labels(self._protocol_labels())
        self._protocol_card.set_protocols(protocols)

    def set_protocol_progress(self, progress: Any | None) -> None:
        """Show the progress of the running protocol; ``None`` collapses."""
        self._protocol_card.set_progress(progress)

    def set_protocol_auto_advance(self, protocol_id: str, enabled: bool) -> None:
        """Push the stored per-protocol «Авто-переход» flag into the footer."""
        self._protocol_card.set_auto_advance(protocol_id, enabled)

    def radial_sectors(self, context: str) -> tuple[str, ...]:
        """Tool ids of the radial menu for a viewer context (TP-6, §4.4).

        The active profile's ``radial`` map wins; an unset context falls back
        to :func:`default_radial`, so the wheel works before an editor exists.
        """
        from echo_personal_tool.domain.tool_panel_view import default_radial, normalize_panel_context

        normalized = normalize_panel_context(context)
        profile = self._layout_v3.profile()
        configured = profile.radial.get(normalized) if profile is not None else None
        return tuple(configured) if configured else default_radial(normalized)

    def set_tool_statuses(self, statuses: Iterable[Any]) -> None:
        """Apply provider states to the matching rows (§8.5).

        UI-5: each row also keeps the measured number, its unit and the
        projection key (the S2 card reads them) and the gradation of the norm
        dot (UD-14) — the same domain model the card shows.
        """
        from echo_personal_tool.application.tool_status import ToolState

        statuses = tuple(statuses)
        self._last_statuses = statuses

        glyphs = {
            ToolState.NONE: STATE_NOT_STARTED,
            ToolState.DONE: STATE_DONE,
            ToolState.STALE: STATE_STALE,
            ToolState.QC: STATE_WARNING,
            ToolState.LOCKED: STATE_LOCKED,
        }
        for status in statuses:
            row = self._rows.get(status.tool_id)
            if row is None:
                continue
            row.set_value(status.text, value=status.value, unit=status.unit, key=status.key)
            row.set_norm_grade(self._norm_grade_of(status))
            if status.state is not ToolState.NONE:
                row.set_status(glyphs[status.state], status.reason)

    # ── S2 norm card and norm dots (UI-5) ──────────────────────────

    def row(self, tool_id: str) -> ToolRow | None:
        """The row of a tool; ``None`` when the context has no such row."""
        return self._rows.get(tool_id)

    def set_reference_sex_provider(self, provider: Callable[[], str]) -> None:
        """The sex of the patient («male» / «female» / \"\") for the card norms."""
        self._reference_sex_provider = provider or (lambda: "")

    def _reference_sex(self) -> str:
        try:
            return str(self._reference_sex_provider() or "")
        except Exception:  # noqa: BLE001 — a broken header must not break the card
            return ""

    def _norm_grade_of(self, status: Any) -> str:
        """Gradation name of the row value («Норма» …); \"\" — no dot (UD-14)."""
        if getattr(status, "value", None) is None:
            return ""
        model = self._card_model_for(
            getattr(status, "key", ""),
            value=status.value,
            unit=getattr(status, "unit", ""),
            label=None,
            full_name=None,
        )
        return model.grade.name if model.grade is not None else ""

    def _card_model_for(self, key: str, *, value, unit: str, label: str | None, full_name: str | None):
        from echo_personal_tool.infrastructure.i18n import get_language
        from echo_personal_tool.presentation.reference_card import card_for_row

        return card_for_row(
            key,
            value=value,
            unit=unit,
            sex=self._reference_sex(),
            language=get_language(),
            label=label,
            full_name=full_name,
        )

    def _on_row_reference_requested(self, tool_id: str) -> None:
        """400 ms of hover or the registry key: show the S2 card of the row."""
        from echo_personal_tool.presentation.reference_card import show_reference_card

        row = self._rows.get(tool_id)
        if row is None:
            return
        self._card_hide_timer.stop()
        from echo_personal_tool.infrastructure.i18n import get_language

        label = row.tool.label(get_language())
        model = self._card_model_for(
            row.measurement_key or tool_id,
            value=row.measurement_value,
            unit=row.measurement_unit,
            label=label.short,
            full_name=label.full,
        )
        if not model.has_norm:
            # General tools (caliper, area, volume, comparisons, etc.) have
            # no reference range; do not show an empty «no norms» popup.
            self.hide_reference_card()
            return
        card = show_reference_card(
            model,
            row.anchor_rect().topLeft(),
            parent=self,
            anchor=row.anchor_rect(),
        )
        if not self._card_open_connected:
            card.reference_requested.connect(self.open_reference_requested.emit)
            self._card_open_connected = True
        self._suppress_row_tooltips(tool_id)

    def _on_row_reference_hide(self, _tool_id: str) -> None:
        """The pointer left the row: hide the card after the travel grace."""
        self._card_hide_timer.start()

    def _on_row_pointer_entered(self, _tool_id: str) -> None:
        """Another row is under the pointer: the card waits for its own model."""
        self._card_hide_timer.stop()

    def _suppress_row_tooltips(self, shown_tool_id: str | None) -> None:
        """Silence the tooltip of the row whose reference card is on screen.

        Both popups are anchored to the same row; the card is the useful one
        (ТЗ 2026-10-23, п. 3), and a tooltip painted over it hides the norm.
        """
        for tool_id, row in self._rows.items():
            row.set_reference_tooltip_suppressed(tool_id == shown_tool_id)

    def _hide_card_if_idle(self) -> None:
        from echo_personal_tool.presentation.reference_card import ReferenceCard

        card = self.findChild(ReferenceCard, "referenceCard")
        if card is None or not card.isVisible():
            return
        if card.underMouse() or any(row.underMouse() for row in self._rows.values()):
            # The pointer is travelling into the card («Открыть в справочнике»).
            self._card_hide_timer.start()
            return
        card.hide()
        self._suppress_row_tooltips(None)

    def hide_reference_card(self) -> None:
        """Close the S2 card now (study change, panel rebuild, Esc)."""
        from echo_personal_tool.presentation.reference_card import ReferenceCard

        self._card_hide_timer.stop()
        card = self.findChild(ReferenceCard, "referenceCard")
        if card is not None:
            card.hide()
        self._suppress_row_tooltips(None)

    def _on_norms_toggled(self, checked: bool) -> None:
        self._norms_visible = bool(checked)
        for row in self._rows.values():
            row.set_norms_visible(self._norms_visible)
        self.norms_toggled.emit(self._norms_visible)

    def norms_visible(self) -> bool:
        return self._norms_visible

    def set_norms_visible(self, visible: bool) -> None:
        """Adopt the remembered «Нормы» switch without emitting back."""
        self._norms_check.blockSignals(True)
        self._norms_check.setChecked(bool(visible))
        self._norms_check.blockSignals(False)
        self._norms_visible = bool(visible)
        for row in self._rows.values():
            row.set_norms_visible(self._norms_visible)

    def refresh_norm_colors(self) -> None:
        """Re-paint the dots after a theme switch (the palette differs)."""
        for row in self._rows.values():
            row.set_norm_grade(row.norm_grade)

    def _protocol_labels(self) -> dict[str, str]:
        from echo_personal_tool.infrastructure.i18n import tr

        return {
            "title": tr("panel.protocol_title"),
            "none": tr("panel.protocol_none"),
            "stop": tr("panel.protocol_stop"),
            "derived": tr("panel.protocol_derived"),
            "skipped": tr("panel.protocol_skipped"),
            "stale": tr("panel.protocol_stale"),
            "lock_mode": tr("panel.protocol_lock_mode"),
            "lock_view": tr("panel.protocol_lock_view"),
            "lock_req": tr("panel.protocol_lock_req"),
            "auto_advance": tr("panel.auto_advance"),
            "skip": tr("panel.protocol_skip"),
        }

    def _language(self) -> str:
        from echo_personal_tool.infrastructure.i18n import get_language

        return get_language()

    # ── Lifecycle ──────────────────────────────────────────────────

    def reset_doppler_mode(self) -> None:
        """Back to «Авто» in the mode chip (emits, so the viewer follows)."""
        if self._mode_combo.currentIndex() == 0:
            return
        self._mode_combo.setCurrentIndex(0)

    def vessel_preset(self) -> str:
        """The vessel preset lives in the old panel only; keep the API stable."""
        return "normal"

    def has_search_focus(self) -> bool:
        return self._search.hasFocus()

    def focus_search(self) -> None:
        self._search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search.selectAll()

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize

        hint = super().sizeHint()
        return hint.expandedTo(self.minimumSizeHint()).expandedTo(QSize(PANEL_WIDTH, 640))

    def minimumSizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize

        return super().minimumSizeHint().expandedTo(QSize(PANEL_MIN_WIDTH, 320))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_chip_reflow()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.ApplicationFontChange, QEvent.Type.StyleChange):
            self._schedule_chip_reflow()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._sync_controls()
        self._schedule_chip_reflow()

    def reload_text(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        for context, button in self._context_buttons.items():
            text = tr(_CONTEXT_KEYS[context])
            button.setText(text)
            button.setProperty("_panel_full_text", text)
            button.setToolTip(text)
            button.setAccessibleName(text)
        self._mode_label.setText(tr("panel.mode"))
        for index, data in enumerate(("", "PW", "CW", "TDI")):
            self._mode_combo.setItemText(index, tr(_MODE_LABELS[data]))
        self._search.setPlaceholderText(tr("panel.search_placeholder"))
        self._norms_check.setText(tr("panel.norms"))
        self._norms_check.setToolTip(tr("panel.norms_hint"))
        self._apply_style()
        self._footer._apply_style()
        self._footer.reload_text()
        # Group titles are rebuilt with the sections.
        for label in self._quick_box.findChildren(QLabel, "panelGroupTitle"):
            label.setText(tr("panel.quick"))
        for label in self._favorites_box.findChildren(QLabel, "panelGroupTitle"):
            label.setText(tr("panel.favorites"))
        self._protocol_card.set_labels(self._protocol_labels())
        self._rebuild()
