"""Окошко «Подписать измерение» после свободного калипера или трассы (TP-4, спека §4.4, §8.1).

Сразу после второй точки свободного калипера (``Dist1``, ``Dist2``, …) или
завершения свободной допплер-трассы (``VTI``) рядом с измерением появляется
компактная карточка:
- заголовок «Подписать измерение · 41 мм»;
- поле поиска по русским/английским подписям, кодам и неверной раскладке;
- верхние 5 подписей текущего контекста с клавишами ``1``–``5``;
- ``Tab`` — переход к следующей подписи (сохраняет цикл ``cycle_caliper_label``);
- ``Enter`` или цифра ``1``–``5`` — присвоить выбранную подпись;
- ``Esc`` или клик мимо — закрыть окошко и оставить измерение без подписи.
В активном протоколе окошко не открывается: подпись известна из шага.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import get_language, tr
from echo_personal_tool.domain.measurement_catalog import CATALOG, MEASUREMENTS, ToolSpec
from echo_personal_tool.domain.tool_panel_view import (
    normalize_panel_context as normalize_context,
)
from echo_personal_tool.domain.tool_panel_view import (
    query_variants,
)
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

#: Число быстрых строк с цифрами 1–5 (спека §4.4, макет 5).
MAX_PICKER_ROWS = 5

#: Геометрия карточки (4-px сетка спеки UI §5.2).
_CARD_MIN_WIDTH = 248
_CARD_MAX_WIDTH = 312
_MARGIN = 10
_GAP = 6
_ROW_GAP = 4
_BADGE_SIZE = 20
_ANCHOR_OFFSET_X = 14
_ANCHOR_OFFSET_Y = -12
_BOUNDS_MARGIN = 8
#: Неограниченный размер Qt (``QWIDGETSIZE_MAX``) — сброс ограничений карточки.
_UNLIMITED_SIZE = 16777215

#: Верхние 5 подписей по контекстам (спека §4.4, макет 5):
#: - 2D: МЖП, КДР ЛЖ, ЗСЛЖ, ЛП ПЗР, Синусы аорты;
#: - М-режим: МЖП, КДР ЛЖ, ЗСЛЖ, КСР ЛЖ, TAPSE;
#: - Допплер: пик E, пик A, ВИС ВТЛЖ, Vmax АК, Vmax ТР.
DEFAULT_CONTEXT_OPTION_IDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "2d": (
            "lv.ivsd",
            "lv.lvedd",
            "lv.lvpwd",
            "la.ap",
            "ao.sinus",
        ),
        "m": (
            "lv.ivsd",
            "lv.lvedd",
            "lv.lvpwd",
            "lv.lvesd",
            "rv.tapse",
        ),
        "doppler": (
            "mv.e",
            "mv.a",
            "lvot.vti",
            "av.vmax",
            "tr.vmax",
        ),
    }
)

_TOOL_ID_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "tool.ivsd": "lv.ivsd",
        "tool.lvedd": "lv.lvedd",
        "tool.lvpwd": "lv.lvpwd",
        "tool.lvesd": "lv.lvesd",
        "tool.la_ap": "la.ap",
        "tool.ao_sinus": "ao.sinus",
        "tool.tapse": "rv.tapse",
    }
)

#: Одиночные измерения из ``MEASUREMENTS``, которые в ``CATALOG`` запускаются
#: через ``action`` или цепочку (``lv.linear_ed``), но могут быть присвоены
#: одному свободному калиперу/пику напрямую.
_MEASUREMENT_CALIPER_TARGETS: tuple[tuple[str, str, str, frozenset[str], tuple[str, ...]], ...] = (
    ("lv.ivsd", "IVSd", "caliper", frozenset({"2d", "m"}), ("мжпд", "ivsd")),
    ("lv.lvedd", "LVEDD", "caliper", frozenset({"2d", "m"}), ("кдр", "lvidd", "lvedd")),
    ("lv.lvpwd", "LVPWd", "caliper", frozenset({"2d", "m"}), ("зслж", "lvpwd")),
    ("lv.lvesd", "LVESD", "caliper", frozenset({"2d", "m"}), ("кср", "lvids", "lvesd")),
    ("la.ap", "LA", "caliper", frozenset({"2d", "m"}), ("лп", "лп пзр", "la ap")),
    ("ra.d", "RA", "caliper", frozenset({"2d"}), ("пп", "ra")),
    ("rv.basal", "RV basal", "caliper", frozenset({"2d"}), ("пж базальный", "rvd1")),
    ("rv.tapse", "TAPSE", "caliper", frozenset({"m", "2d"}), ("тапсе", "tapce", "tapse")),
    ("rv.s_prime", "s_rv", "peak", frozenset({"tdi"}), ("s' пж", "rv s'")),
)

_EXTRA_SYNONYMS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "ao.sinus": ("Синусы Вальсальвы", "синусы вальсальвы", "Ao sinus"),
        "lvot.vti": ("ВИС ВТЛЖ", "вис втлж", "ВИС", "втлж"),
        "mv.e": ("Пик E", "пик e", "MV E"),
        "mv.a": ("Пик A", "пик a", "MV A"),
    }
)


@dataclass(frozen=True)
class LabelOption:
    """Одна подпись каталога, которую можно присвоить свободному измерению."""

    tool_id: str
    target_label: str
    kind: str  # "caliper" | "peak" | "interval" | "trace"
    label_ru: str
    label_en: str
    full_ru: str = ""
    full_en: str = ""
    synonyms: tuple[str, ...] = ()
    contexts: frozenset[str] = frozenset()

    def label(self, lang: str | None = None) -> str:
        """Короткая подпись на выбранном языке интерфейса."""
        target = lang if lang in ("ru", "en") else get_language()
        return self.label_en if target == "en" else self.label_ru

    def full_name(self, lang: str | None = None) -> str:
        """Полное клиническое имя на выбранном языке интерфейса."""
        target = lang if lang in ("ru", "en") else get_language()
        return self.full_en if target == "en" else self.full_ru


def _option_from_spec(spec: ToolSpec) -> LabelOption | None:
    payload = spec.payload
    ru = spec.label("ru")
    en = spec.label("en")
    label_ru = ru.short
    label_en = en.short
    full_ru = ru.full
    full_en = en.full
    synonyms = spec.synonyms + _EXTRA_SYNONYMS.get(spec.id, ())
    if payload.caliper_label:
        return LabelOption(
            tool_id=spec.id,
            target_label=payload.caliper_label,
            kind="caliper",
            label_ru=label_ru,
            label_en=label_en,
            full_ru=full_ru,
            full_en=full_en,
            synonyms=synonyms,
            contexts=spec.contexts,
        )
    if payload.doppler_peak:
        return LabelOption(
            tool_id=spec.id,
            target_label=payload.doppler_peak,
            kind="peak",
            label_ru=label_ru,
            label_en=label_en,
            full_ru=full_ru,
            full_en=full_en,
            synonyms=synonyms,
            contexts=spec.contexts,
        )
    if payload.doppler_interval:
        return LabelOption(
            tool_id=spec.id,
            target_label=payload.doppler_interval,
            kind="interval",
            label_ru=label_ru,
            label_en=label_en,
            full_ru=full_ru,
            full_en=full_en,
            synonyms=synonyms,
            contexts=spec.contexts,
        )
    if (
        payload.doppler_trace
        and payload.action != "doppler_trace_auto_region"
        and spec.id != "tool.vti_trace"
        and payload.doppler_trace.upper() != "VTI"
    ):
        return LabelOption(
            tool_id=spec.id,
            target_label=payload.doppler_trace,
            kind="trace",
            label_ru=label_ru,
            label_en=label_en,
            full_ru=full_ru,
            full_en=full_en,
            synonyms=synonyms,
            contexts=spec.contexts,
        )
    return None


def _build_catalog_options() -> tuple[tuple[LabelOption, ...], Mapping[str, LabelOption], Mapping[str, LabelOption]]:
    items: list[LabelOption] = []
    by_id: dict[str, LabelOption] = {}
    by_target: dict[str, LabelOption] = {}
    for mid, target_label, kind, contexts, extra_syn in _MEASUREMENT_CALIPER_TARGETS:
        mspec = MEASUREMENTS.get(mid)
        if mspec is None:
            continue
        ru = mspec.label("ru")
        en = mspec.label("en")
        option = LabelOption(
            tool_id=mid,
            target_label=target_label,
            kind=kind,
            label_ru=ru.short,
            label_en=en.short,
            full_ru=ru.full,
            full_en=en.full,
            synonyms=mspec.synonyms + extra_syn,
            contexts=contexts,
        )
        items.append(option)
        by_id[option.tool_id] = option
        by_target.setdefault(option.target_label, option)
    for spec in CATALOG.values():
        if spec.id in by_id:
            continue
        option = _option_from_spec(spec)
        if option is None:
            continue
        items.append(option)
        by_id[option.tool_id] = option
        by_target.setdefault(option.target_label, option)
    return tuple(items), MappingProxyType(by_id), MappingProxyType(by_target)


_ALL_OPTIONS, _OPTIONS_BY_ID, _OPTIONS_BY_TARGET = _build_catalog_options()


def all_label_options() -> tuple[LabelOption, ...]:
    """Все именованные подписи каталога для калиперов и допплера."""
    return _ALL_OPTIONS


def option_for_tool_id(tool_id: str) -> LabelOption | None:
    """Найти :class:`LabelOption` по id инструмента или измерения каталога."""
    canonical = _TOOL_ID_ALIASES.get(tool_id, tool_id)
    return _OPTIONS_BY_ID.get(canonical)


def option_for_target_label(target_label: str) -> LabelOption | None:
    """Найти :class:`LabelOption` по канонической метке (``LVEDD``, ``E``, ``LVOT VTI``)."""
    if target_label in _OPTIONS_BY_TARGET:
        return _OPTIONS_BY_TARGET[target_label]
    upper = target_label.upper()
    for key, opt in _OPTIONS_BY_TARGET.items():
        if key.upper() == upper:
            return opt
    return None


def default_label_options(context: str = "2d", *, limit: int = MAX_PICKER_ROWS) -> tuple[LabelOption, ...]:
    """Верхние 5 подписей для выбранного контекста (``2d``, ``m``, ``doppler``)."""
    ctx = normalize_context(context)
    ids = DEFAULT_CONTEXT_OPTION_IDS.get(ctx, DEFAULT_CONTEXT_OPTION_IDS["2d"])
    resolved = [_OPTIONS_BY_ID[item_id] for item_id in ids if item_id in _OPTIONS_BY_ID]
    return tuple(resolved[: max(0, limit)])


def _score_candidate(text: str, needle: str, *, exact_weight: int, prefix_weight: int, sub_weight: int) -> int:
    lowered = text.lower()
    if not lowered:
        return 0
    if lowered == needle:
        return exact_weight
    if lowered.startswith(needle):
        return prefix_weight
    for token in lowered.replace(".", " ").replace("/", " ").replace("-", " ").split():
        if token == needle:
            return prefix_weight - 5
        if token.startswith(needle):
            return prefix_weight - 15
    if needle in lowered:
        return sub_weight
    return 0


def _score_option(option: LabelOption, variants: tuple[str, ...], context: str) -> int:
    best = 0
    for variant in variants:
        best = max(
            best,
            _score_candidate(option.label_ru, variant, exact_weight=1000, prefix_weight=850, sub_weight=620),
            _score_candidate(option.label_en, variant, exact_weight=980, prefix_weight=830, sub_weight=600),
            _score_candidate(option.target_label, variant, exact_weight=970, prefix_weight=820, sub_weight=590),
            _score_candidate(option.tool_id, variant, exact_weight=900, prefix_weight=750, sub_weight=520),
            _score_candidate(option.full_ru, variant, exact_weight=700, prefix_weight=560, sub_weight=420),
            _score_candidate(option.full_en, variant, exact_weight=680, prefix_weight=540, sub_weight=400),
        )
        for synonym in option.synonyms:
            best = max(
                best,
                _score_candidate(synonym, variant, exact_weight=950, prefix_weight=800, sub_weight=580),
            )
    if best > 0 and context in option.contexts:
        best += 25
    return best


def search_label_options(
    query: str,
    *,
    context: str = "2d",
    limit: int = MAX_PICKER_ROWS,
) -> tuple[LabelOption, ...]:
    """Подобрать до ``limit`` подписей по поисковому запросу или контексту.

    Пустой запрос возвращает верхние 5 подписей текущего контекста. Непустой
    запрос ищет по русским и английским названиям, каноническим кодам,
    синонимам и транслитерации неверной раскладки (``rlh`` → ``КДР ЛЖ``).
    """
    ctx = normalize_context(context)
    variants = query_variants(query)
    if not variants:
        return default_label_options(ctx, limit=limit)
    scored: list[tuple[int, int, LabelOption]] = []
    for order, option in enumerate(_ALL_OPTIONS):
        score = _score_option(option, variants, ctx)
        if score > 0:
            scored.append((score, -order, option))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return tuple(item[2] for item in scored[: max(0, limit)])


class _LabelOptionRow(QFrame):
    """Одна нумерованная строка выбора подписи (``[1] МЖП … [Enter]``)."""

    clicked = Signal(int)

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self._option: LabelOption | None = None
        self._selected = False
        self.setObjectName("labelPickerRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self._badge = QLabel(str(index + 1), self)
        self._badge.setObjectName("labelPickerBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFixedSize(_BADGE_SIZE, _BADGE_SIZE)

        self._label = QLabel(self)
        self._label.setObjectName("labelPickerRowLabel")

        self._enter_badge = QLabel(tr("label_picker.enter_hint"), self)
        self._enter_badge.setObjectName("labelPickerEnterBadge")
        self._enter_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._enter_badge.hide()

        layout.addWidget(self._badge)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._enter_badge)

    @property
    def option(self) -> LabelOption | None:
        return self._option

    @property
    def is_selected(self) -> bool:
        return self._selected

    def set_option(self, option: LabelOption | None, *, selected: bool = False) -> None:
        self._option = option
        self._selected = bool(selected and option is not None)
        if option is None:
            self._label.setText("")
            self.setToolTip("")
            self._enter_badge.hide()
            self.hide()
            return
        self._badge.setText(str(self._index + 1))
        self._label.setText(option.label())
        self.setToolTip(option.full_name() or option.label())
        self._enter_badge.setText(tr("label_picker.enter_hint"))
        self._enter_badge.setVisible(self._selected)
        self.show()

    def apply_row_theme(self, tokens: Mapping[str, str]) -> None:
        bg = tokens["accent.selected"] if self._selected else "transparent"
        border = tokens["accent"] if self._selected else "transparent"
        label_fg = tokens["text.selected"] if self._selected else tokens["text.1"]
        hover = bg if self._selected else tokens["surface.hover"]
        badge_border = tokens["accent"] if self._selected else tokens["line.1"]
        badge_fg = tokens["text.1"] if self._selected else tokens["text.2"]
        self.setStyleSheet(
            f"QFrame#labelPickerRow {{ background: {bg}; border: 1px solid {border}; border-radius: 4px; }}"
            f" QFrame#labelPickerRow:hover {{ background: {hover}; }}"
            f" QLabel#labelPickerBadge {{ background: {tokens['surface.3']}; color: {badge_fg};"
            f" border: 1px solid {badge_border}; border-radius: 4px; font-size: 11px; font-weight: 600; }}"
            f" QLabel#labelPickerRowLabel {{ color: {label_fg}; background: transparent; border: none; }}"
            f" QLabel#labelPickerEnterBadge {{ background: {tokens['surface.3']}; color: {tokens['text.2']};"
            f" border: 1px solid {tokens['line.1']}; border-radius: 4px; padding: 1px 6px; font-size: 10px; }}"
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._option is not None:
            self.clicked.emit(self._index)
            event.accept()
            return
        super().mousePressEvent(event)


class LabelPicker(QFrame):
    """Всплывающее окошко «Подписать измерение» во вьюере (TP-4, спека §4.4)."""

    #: Выбрана подпись (:class:`LabelOption`).
    label_selected = Signal(object)
    #: Нажат ``Tab`` — пролистать к следующей подписи.
    tab_cycled = Signal()
    #: Окошко закрыто без выбора (``Esc`` или клик мимо).
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("labelPicker")
        self.setMinimumWidth(_CARD_MIN_WIDTH)
        self.setMaximumWidth(_CARD_MAX_WIDTH)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._context: str = "2d"
        self._value_text: str = ""
        self._options: tuple[LabelOption, ...] = ()
        self._selected_index: int = 0
        self._applying_theme: bool = False
        self._stylesheet: str = ""

        self._title = QLabel(self)
        self._title.setObjectName("labelPickerTitle")
        self._title.setWordWrap(True)
        title_font = QFont(self._title.font())
        title_font.setWeight(QFont.Weight.DemiBold)
        self._title.setFont(title_font)

        self._search = QLineEdit(self)
        self._search.setObjectName("labelPickerSearch")
        self._search.setPlaceholderText(tr("label_picker.search_placeholder"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_text_changed)
        self._search.installEventFilter(self)

        self._rows_container = QWidget()
        self._rows_container.setObjectName("labelPickerRows")
        rows_layout = QVBoxLayout(self._rows_container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(_ROW_GAP)
        self._rows: list[_LabelOptionRow] = []
        for idx in range(MAX_PICKER_ROWS):
            row = _LabelOptionRow(idx, self._rows_container)
            row.clicked.connect(self._on_row_clicked)
            rows_layout.addWidget(row)
            self._rows.append(row)

        # Список вариантов живёт в прокручиваемой области: если карточку
        # пришлось сжать под размер вьюера, строки прокручиваются, а не срезаются.
        self._rows_scroll = QScrollArea(self)
        self._rows_scroll.setObjectName("labelPickerScroll")
        self._rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rows_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rows_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._rows_scroll.setWidgetResizable(True)
        self._rows_scroll.setWidget(self._rows_container)

        self._footer = QLabel(tr("label_picker.footer_hint"), self)
        self._footer.setObjectName("labelPickerFooter")
        self._footer.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        layout.setSpacing(_GAP)
        layout.addWidget(self._title)
        layout.addWidget(self._search)
        layout.addWidget(self._rows_scroll)
        layout.addWidget(self._footer)

        self.hide()
        self.apply_theme()
        self._refresh_options()

    # ── Состояние и данные ─────────────────────────────────────────

    def context(self) -> str:
        return self._context

    def value_text(self) -> str:
        return self._value_text

    def title_text(self) -> str:
        return self._title.text()

    def search_query(self) -> str:
        return self._search.text()

    def options(self) -> tuple[LabelOption, ...]:
        return self._options

    def selected_index(self) -> int:
        return self._selected_index

    def selected_option(self) -> LabelOption | None:
        if 0 <= self._selected_index < len(self._options):
            return self._options[self._selected_index]
        return None

    def set_context(self, context: str) -> None:
        self._context = normalize_context(context)
        self._refresh_options()

    def set_value_text(self, value_text: str) -> None:
        self._value_text = value_text.strip()
        self._update_header_text()

    def set_search_query(self, query: str) -> None:
        self._search.setText(query)

    def open_for(
        self,
        *,
        value_text: str = "",
        context: str = "2d",
        anchor: QPoint | None = None,
        bounds: QRect | None = None,
    ) -> None:
        """Открыть окошко для только что завершённого свободного измерения."""
        self._context = normalize_context(context)
        self._value_text = value_text.strip()
        self.retranslate_ui()
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._selected_index = 0
        self._refresh_options()
        self.adjustSize()
        if anchor is not None:
            self.popup_near(anchor, bounds)
        else:
            self.show()
            self.raise_()
        self._search.setFocus(Qt.FocusReason.PopupFocusReason)

    def retranslate_ui(self) -> None:
        self._update_header_text()
        self._search.setPlaceholderText(tr("label_picker.search_placeholder"))
        self._footer.setText(tr("label_picker.footer_hint"))
        self._sync_rows()

    def _update_header_text(self) -> None:
        if self._value_text:
            self._title.setText(tr("label_picker.title_with_value", value=self._value_text))
        else:
            self._title.setText(tr("label_picker.title"))

    def _on_search_text_changed(self, _text: str) -> None:
        self._selected_index = 0
        self._refresh_options()

    def _refresh_options(self) -> None:
        self._options = search_label_options(
            self._search.text(),
            context=self._context,
            limit=MAX_PICKER_ROWS,
        )
        if not self._options:
            self._selected_index = -1
        elif not (0 <= self._selected_index < len(self._options)):
            self._selected_index = 0
        self._sync_rows()

    def _sync_rows(self) -> None:
        tokens = get_theme_tokens()
        for idx, row in enumerate(self._rows):
            option = self._options[idx] if idx < len(self._options) else None
            row.set_option(option, selected=(idx == self._selected_index))
            row.apply_row_theme(tokens)
        self.adjustSize()

    # ── Выбор и навигация ──────────────────────────────────────────

    def cycle_next(self, *, emit_tab: bool = True) -> LabelOption | None:
        """Перейти к следующей подписи (``Tab`` / ``Down``)."""
        if not self._options:
            return None
        self._selected_index = (self._selected_index + 1) % len(self._options)
        self._sync_rows()
        if emit_tab:
            self.tab_cycled.emit()
        return self.selected_option()

    def cycle_previous(self) -> LabelOption | None:
        """Перейти к предыдущей подписи (``Shift+Tab`` / ``Up``)."""
        if not self._options:
            return None
        self._selected_index = (self._selected_index - 1) % len(self._options)
        self._sync_rows()
        return self.selected_option()

    def select_index(self, index: int) -> bool:
        """Выбрать строку ``index`` (0..4) и закрыть окошко."""
        if not (0 <= index < len(self._options)):
            return False
        option = self._options[index]
        self._selected_index = index
        self.hide()
        self.label_selected.emit(option)
        return True

    def accept_current(self) -> bool:
        """Принять текущую выделенную подпись (``Enter``)."""
        if not (0 <= self._selected_index < len(self._options)):
            return False
        return self.select_index(self._selected_index)

    def dismiss(self) -> bool:
        """Закрыть окошко без выбора подписи (``Esc`` или клик мимо)."""
        was_visible = not self.isHidden()
        self.hide()
        if was_visible:
            self.dismissed.emit()
        return was_visible

    def _on_row_clicked(self, index: int) -> None:
        self.select_index(index)

    # ── Клавиатура и фокус ─────────────────────────────────────────

    def focusNextPrevChild(self, next_child: bool) -> bool:  # noqa: N802
        """Перехватывать Tab/Shift+Tab внутри карточки для пролистывания подписей."""
        if next_child:
            self.cycle_next(emit_tab=True)
        else:
            self.cycle_previous()
        return True

    def handle_key_press(self, event: QKeyEvent) -> bool:
        """Обработать нажатие клавиши (из поля поиска или из родительского вьюера)."""
        key = event.key()
        modifiers = event.modifiers()
        no_cmd_mods = not (
            modifiers
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)
        )

        if key == Qt.Key.Key_Escape:
            self.dismiss()
            event.accept()
            return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.accept_current():
                event.accept()
                return True
            return False

        if key == Qt.Key.Key_Tab:
            self.cycle_next(emit_tab=True)
            event.accept()
            return True

        if key == Qt.Key.Key_Backtab:
            self.cycle_previous()
            event.accept()
            return True

        if key == Qt.Key.Key_Down and no_cmd_mods:
            self.cycle_next(emit_tab=False)
            event.accept()
            return True

        if key == Qt.Key.Key_Up and no_cmd_mods:
            self.cycle_previous()
            event.accept()
            return True

        if no_cmd_mods and Qt.Key.Key_1 <= key <= Qt.Key.Key_5:
            index = int(key - Qt.Key.Key_1)
            if self.select_index(index):
                event.accept()
                return True

        # Если фокус остался на вьюере (например, в headless-тесте), перенаправляем
        # печатные символы и Backspace в поле поиска.
        if not self._search.hasFocus() and no_cmd_mods:
            if key == Qt.Key.Key_Backspace:
                current = self._search.text()
                if current:
                    self._search.setText(current[:-1])
                event.accept()
                return True
            text = event.text()
            if text and text.isprintable() and not text.isdigit():
                self._search.setText(self._search.text() + text)
                event.accept()
                return True

        return False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._search:
            if event.type() == QEvent.Type.ShortcutOverride and isinstance(event, QKeyEvent):
                if self._should_override_shortcut(event):
                    event.accept()
                    return True
            if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
                if self.handle_key_press(event):
                    return True
        return super().eventFilter(watched, event)

    def event(self, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.ShortcutOverride and isinstance(event, QKeyEvent):
            if self._should_override_shortcut(event):
                event.accept()
                return True
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if self.handle_key_press(event):
                return True
        return super().event(event)

    @staticmethod
    def _should_override_shortcut(event: QKeyEvent) -> bool:
        key = event.key()
        if key in (
            Qt.Key.Key_Escape,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Tab,
            Qt.Key.Key_Backtab,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            return True
        modifiers = event.modifiers()
        no_cmd_mods = not (
            modifiers
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)
        )
        if no_cmd_mods and Qt.Key.Key_1 <= key <= Qt.Key.Key_5:
            return True
        if no_cmd_mods and event.text() and event.text().isprintable():
            return True
        return False

    # ── Размещение и тема ──────────────────────────────────────────

    def popup_near(self, anchor: QPoint, bounds: QRect | None = None) -> None:
        """Разместить окошко рядом с точкой ``anchor`` внутри ``bounds``.

        Окошко не выходит за границы области ни при каких метриках шрифтов:
        если карточка не помещается целиком, поля сжимаются до нуля, размер
        ограничивается размером области, а список вариантов прокручивается
        внутри окошка (строки не срезаются и остаются доступными).
        """
        parent = self.parentWidget()
        area = bounds if bounds is not None else (parent.rect() if parent is not None else QRect(0, 0, 800, 600))
        if area.isEmpty():
            self.show()
            self.raise_()
            return

        # Снимаем ограничения и измеряем естественный размер: знать высоту
        # списка нужно, чтобы сжать именно его, а не карточку целиком.
        self._rows_scroll.setMaximumHeight(_UNLIMITED_SIZE)
        self.setMinimumWidth(min(_CARD_MIN_WIDTH, area.width()))
        self.setMaximumWidth(min(_CARD_MAX_WIDTH, area.width()))
        self.setMaximumHeight(_UNLIMITED_SIZE)
        self.adjustSize()
        natural_height = max(self.height(), self.sizeHint().height())
        width = min(max(self.width(), self.sizeHint().width(), _CARD_MIN_WIDTH), area.width())
        height = min(natural_height, area.height())

        # Список получает остаток высоты; карточка целиком — не выше области.
        chrome_height = natural_height - self._rows_scroll.sizeHint().height()
        self._rows_scroll.setMaximumHeight(max(0, height - chrome_height))
        self.setMaximumHeight(height)
        self.resize(width, height)

        # Поля сжимаются до нуля, если карточка занимает почти всю область.
        margin_x = min(_BOUNDS_MARGIN, max(0, (area.width() - width) // 2))
        margin_y = min(_BOUNDS_MARGIN, max(0, (area.height() - height) // 2))
        min_x = area.left() + margin_x
        min_y = area.top() + margin_y
        max_x = area.left() + area.width() - width - margin_x
        max_y = area.top() + area.height() - height - margin_y

        x = anchor.x() + _ANCHOR_OFFSET_X
        y = anchor.y() + _ANCHOR_OFFSET_Y

        if x > max_x:
            # Если справа не помещается — ставим слева от точки измерения.
            left_x = anchor.x() - width - _ANCHOR_OFFSET_X
            x = left_x if left_x >= min_x else max_x
        x = max(min_x, min(x, max_x))
        y = max(min_y, min(y, max_y))

        self.move(x, y)
        self.show()
        self.raise_()

    def apply_theme(self) -> None:
        """Перекрасить карточку строго из семантических токенов активной темы (§5.3)."""
        if self._applying_theme:
            return
        self._applying_theme = True
        try:
            tokens = get_theme_tokens()
            sheet = (
                f"QFrame#labelPicker {{ background: {tokens['surface.2']};"
                f" border: 1px solid {tokens['line.1']}; border-radius: 8px; }}"
                f" QLabel#labelPickerTitle {{ color: {tokens['text.2']}; font-size: 11px; font-weight: 600;"
                " background: transparent; border: none; }"
                f" QLineEdit#labelPickerSearch {{ background: {tokens['surface.1']}; color: {tokens['text.1']};"
                f" border: 1px solid {tokens['line.1']}; border-radius: 4px; padding: 4px 8px; }}"
                f" QLineEdit#labelPickerSearch:focus {{ border: 1px solid {tokens['accent']}; }}"
                f" QWidget#labelPickerRows {{ background: transparent; border: none; }}"
                f" QScrollArea#labelPickerScroll {{ background: transparent; border: none; }}"
                f" QScrollArea#labelPickerScroll > QWidget {{ background: transparent; border: none; }}"
                f" QLabel#labelPickerFooter {{ color: {tokens['text.3']}; font-size: 11px;"
                f" border-top: 1px solid {tokens['line.2']}; padding-top: 4px; background: transparent; }}"
            )
            if sheet != self._stylesheet:
                self._stylesheet = sheet
                self.setStyleSheet(sheet)
            for row in self._rows:
                row.apply_row_theme(tokens)
            self.update()
        finally:
            self._applying_theme = False

    def changeEvent(self, event: QEvent) -> None:  # type: ignore[override]
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.apply_theme()
        elif event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
