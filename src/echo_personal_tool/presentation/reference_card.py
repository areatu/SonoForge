"""UI-5 PR-1 — карточка нормы S2 (спека UI §4.7, решения UD-06 и UD-14).

Карточка открывается у строки измерения: значение, градация, норма для пола
пациента, шкала градаций, «как измерять», источник и действие «Открыть в
справочнике». **Рисунков в карточке нет**: текст на прикреплённых схемах
справочника слишком мелкий для всплывающего окна, схемы остаются в окне S1.
Поэтому в модуле нет ни одной загрузки изображения: шкала и маркер значения
рисуются на :class:`_GradeScale`, чип градации — рамка с фоном, а не картинка.

Градацию, норму и пороги считает домен
(:mod:`echo_personal_tool.domain.services.reference_card`): виджет получает
готовую :class:`ReferenceCardModel` и только показывает её (§8.5).

Окно — подсказка (``Qt.ToolTip``) без активации: карточка не крадёт фокус у
строки, к которой привязана, и не мешает продолжать ввод. Показ, задержку
400 мс и скрытие держит хост строки; :func:`show_reference_card` — его вход.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from echo_personal_tool.domain.services.reference_card import GradeCut, ReferenceCardModel, build_reference_card
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.reference_grades import grade_colors

#: §6 — the card is a hover card: it appears after 400 ms over a row and is
#: never shown on a plain mouse pass.
HOVER_DELAY_MS = 400

#: §5.2 — the grid is 4 px; the card is a card, so it sits on ``surface.2``.
_MARGIN = 12
_GAP = 8
_SMALL_GAP = 4
_CARD_MIN_WIDTH = 280
_CARD_MAX_WIDTH = 360

#: The method of a norm is a sentence in the handbook; the card keeps this much.
_METHOD_MAX = 32

#: Geometry of the scale: the bar, the marker above it and the segment gap.
_BAR_HEIGHT = 8
_BAR_RADIUS = 4
_SEGMENT_GAP = 2
_MARKER_HEIGHT = 7
_LEGEND_DOT = 8


def _tokens() -> dict[str, str]:
    return get_theme_tokens()


class _GradeScale(QWidget):
    """The scale of the gradations: one segment per grade, a marker for the value.

    The segments are of equal width: the gradations are ordinal (normal → mild
    → moderate → severe) and their ranges differ by orders of magnitude, so a
    proportional scale would squeeze «норма 36–51 мм» next to «тяжёлое ≥ 62 мм»
    into a sliver. Inside its segment the marker is placed proportionally, so
    the reading stays quantitative where the range is closed.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("gradeScale")
        self._cuts: tuple[GradeCut, ...] = ()
        self._value: float | None = None
        self._grade_name = ""
        self.setMinimumWidth(200)
        self.setFixedHeight(_BAR_HEIGHT + _MARKER_HEIGHT + 2)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_model(self, cuts: tuple[GradeCut, ...], value: float | None, grade: GradeCut | None) -> None:
        self._cuts = cuts
        self._value = value
        self._grade_name = grade.name if grade is not None else ""
        self.update()

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(240, _BAR_HEIGHT + _MARKER_HEIGHT + 2)

    # ── painting ───────────────────────────────────────────────────
    def _segments(self) -> list[tuple[float, float, QColor, bool]]:
        """``(x, width, colour, is_grade)`` of every segment, left to right."""
        count = len(self._cuts)
        if not count:
            return []
        total = max(self.width() - (count - 1) * _SEGMENT_GAP, count)
        width = total / count
        result: list[tuple[float, float, QColor, bool]] = []
        for index, cut in enumerate(self._cuts):
            colors = grade_colors(cut.name)
            colour = QColor(colors[0]) if colors else QColor(_tokens()["line.2"])
            result.append((index * (width + _SEGMENT_GAP), width, colour, cut.name == self._grade_name))
        return result

    def _marker_x(self, segments) -> float | None:
        """X of the value marker, or ``None`` when the value is off the scale."""
        if self._value is None or not self._cuts:
            return None
        value = self._value
        for index, cut in enumerate(self._cuts):
            if not cut.contains(value):
                continue
            x, width, _colour, _active = segments[index]
            if cut.low is not None and cut.high is not None and cut.high > cut.low:
                ratio = (value - cut.low) / (cut.high - cut.low)
            elif cut.low is not None:
                # Open upwards («≥ 211 г»): the marker slides right from the
                # threshold and stops at the end of the segment.
                span = max(abs(cut.low), 1.0)
                ratio = 0.5 + 0.5 * min(1.0, max(0.0, (value - cut.low) / span))
            elif cut.high is not None:
                span = max(abs(cut.high), 1.0)
                ratio = 0.5 * min(1.0, max(0.0, value / span))
            else:
                ratio = 0.5
            return x + width * min(1.0, max(0.0, ratio))
        # Below the first threshold or above the last one: the marker sits on
        # the edge of the scale, so the reading is visibly off the grades.
        first = self._cuts[0]
        last = self._cuts[-1]
        if first.low is not None and value < first.low:
            return 0.0
        if last.high is not None and value > last.high:
            return float(self.width())
        return None

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        tokens = _tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar_top = _MARKER_HEIGHT + 2
        segments = self._segments()
        if not segments:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens["line.2"]))
            painter.drawRoundedRect(0, bar_top, self.width(), _BAR_HEIGHT, _BAR_RADIUS, _BAR_RADIUS)
            painter.end()
            return

        for x, width, colour, active in segments:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawRoundedRect(int(x), bar_top, int(width), _BAR_HEIGHT, _BAR_RADIUS, _BAR_RADIUS)
            if active:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QColor(tokens["text.1"]))
                path = QPainterPath()
                path.addRoundedRect(x, bar_top, width, _BAR_HEIGHT, _BAR_RADIUS, _BAR_RADIUS)
                painter.drawPath(path)

        marker_x = self._marker_x(segments)
        if marker_x is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens["text.1"]))
            x = int(round(marker_x)) - 3
            triangle = QPainterPath()
            triangle.moveTo(x, bar_top - 1)
            triangle.lineTo(x + 7, bar_top - 1)
            triangle.lineTo(x + 3.5, bar_top - _MARKER_HEIGHT)
            triangle.closeSubpath()
            painter.drawPath(triangle)
            painter.setPen(QColor(tokens["text.1"]))
            painter.drawLine(int(round(marker_x)), bar_top, int(round(marker_x)), bar_top + _BAR_HEIGHT)
        painter.end()


class _GradeChip(QLabel):
    """The gradation of the value: a filled pill, not an icon."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("gradeChip")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()

    def set_grade(self, grade: GradeCut | None) -> None:
        if grade is None:
            self.hide()
            self.setText("")
            self.setStyleSheet("")
            return
        colors = grade_colors(grade.name)
        fill, text = colors if colors else (_tokens()["surface.3"], _tokens()["text.1"])
        self.setText(grade.name)
        self.setStyleSheet(
            "QLabel#gradeChip {"
            f" background: {fill}; color: {text};"
            f" border: 1px solid {text}; border-radius: 10px;"
            " padding: 1px 8px; font-weight: 600;"
            " }"
        )
        self.show()


class ReferenceCard(QFrame):
    """The S2 card of one measured parameter (§4.7).

    The card owns no data: :meth:`set_model` takes a
    :class:`ReferenceCardModel` built by the domain. «Открыть в справочнике»
    emits :attr:`reference_requested` with the parameter id — the host decides
    what «справочник» is today (the reference window, and S1 after UI-5 PR-2).
    """

    #: The host opens the reference window on this parameter (§4.7).
    reference_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("referenceCard")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumWidth(_CARD_MIN_WIDTH)
        self.setMaximumWidth(_CARD_MAX_WIDTH)

        self._model: ReferenceCardModel | None = None
        self._stylesheet = ""
        self._applying_theme = False
        self._title = QLabel(self)
        self._title.setObjectName("referenceCardTitle")
        self._title.setWordWrap(True)
        title_font = QFont(self._title.font())
        title_font.setWeight(QFont.Weight.DemiBold)
        self._title.setFont(title_font)

        self._full = QLabel(self)
        self._full.setObjectName("referenceCardFullName")
        self._full.setWordWrap(True)
        self._full.hide()

        value_row = QWidget(self)
        value_layout = QHBoxLayout(value_row)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(_SMALL_GAP)
        self._value = QLabel(value_row)
        self._value.setObjectName("referenceCardValue")
        self._chip = _GradeChip(value_row)
        value_layout.addWidget(self._value)
        value_layout.addWidget(self._chip)
        value_layout.addStretch(1)

        self._norm = QLabel(self)
        self._norm.setObjectName("referenceCardNorm")
        self._norm.setWordWrap(True)

        self._scale = _GradeScale(self)
        self._legend = QWidget(self)
        self._legend_layout = QHBoxLayout(self._legend)
        self._legend_layout.setContentsMargins(0, 0, 0, 0)
        self._legend_layout.setSpacing(_SMALL_GAP)

        self._how_to_title = QLabel(tr("ref_card.how_to"), self)
        self._how_to_title.setObjectName("referenceCardHowToTitle")
        self._how_to = QLabel(self)
        self._how_to.setObjectName("referenceCardHowTo")
        self._how_to.setWordWrap(True)
        self._how_to.hide()
        self._how_to_title.hide()

        self._source = QLabel(self)
        self._source.setObjectName("referenceCardSource")
        self._source.setWordWrap(True)
        self._source.hide()

        self._open = QPushButton(tr("ref_card.open"), self)
        self._open.setObjectName("referenceCardOpen")
        self._open.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._open.clicked.connect(self._on_open_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        layout.setSpacing(_GAP)
        layout.addWidget(self._title)
        layout.addWidget(self._full)
        layout.addWidget(value_row)
        layout.addWidget(self._norm)
        layout.addWidget(self._scale)
        layout.addWidget(self._legend)
        layout.addWidget(self._how_to_title)
        layout.addWidget(self._how_to)
        layout.addWidget(self._source)
        layout.addWidget(self._open, 0, Qt.AlignmentFlag.AlignLeft)
        self.apply_theme()

    # ── data ───────────────────────────────────────────────────────
    @property
    def model(self) -> ReferenceCardModel | None:
        return self._model

    def set_model(self, model: ReferenceCardModel | None) -> None:
        """Fill the card; ``None`` hides everything but the header."""
        self._model = model
        if model is None:
            self._title.setText("")
            self._full.hide()
            self._value.setText("")
            self._chip.set_grade(None)
            self._norm.setText("")
            self._scale.set_model((), None, None)
            self._clear_legend()
            self._how_to.hide()
            self._how_to_title.hide()
            self._source.hide()
            self._open.hide()
            return

        self._title.setText(model.label or model.param_id)
        self._full.setText(model.full_name)
        self._full.setVisible(bool(model.full_name))

        if model.value is None:
            self._value.setText(tr("ref_card.not_measured"))
        else:
            self._value.setText(model.value_text or f"{model.value}")
        self._chip.set_grade(model.grade)

        norm_line = self._norm_line(model)
        self._norm.setText(norm_line)
        self._norm.setToolTip(model.method if model.method else norm_line)
        self._scale.set_model(model.cuts, model.value, model.grade)
        self._fill_legend(model)
        self._fill_how_to(model)

        source = model.source.strip()
        self._source.setText(f"{tr('ref_card.source')}: {source}" if source else "")
        self._source.setVisible(bool(source))
        # The button leads somewhere only when the handbook has the parameter.
        self._open.setVisible(model.known)
        self.apply_theme()
        self.adjustSize()

    @staticmethod
    def _norm_line(model: ReferenceCardModel) -> str:
        """«женщины · 36–51 мм · М-режим» or the honest «нормы нет»."""
        if not model.has_norm:
            return tr("ref_card.no_norm")
        parts: list[str] = []
        if model.sex_label:
            parts.append(model.sex_label)
        parts.append(f"{model.norm_text} {model.unit}".strip())
        if model.method:
            # The method is a long sentence in the handbook («Линейный метод
            # (М-режим), кубическая формула ASE»); the card shortens it and the
            # tooltip carries the whole line.
            method = model.method.strip()
            parts.append(method if len(method) <= _METHOD_MAX else method[: _METHOD_MAX - 1].rstrip() + "…")
        return " · ".join(parts)

    def _clear_legend(self) -> None:
        while self._legend_layout.count():
            item = self._legend_layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            # ``deleteLater`` alone leaves the row in the tree until the event
            # loop runs, and a legend row that is still a child is still
            # painted — on top of the card at (0, 0). Detach first.
            widget.setParent(None)
            widget.deleteLater()

    def _fill_legend(self, model: ReferenceCardModel) -> None:
        self._clear_legend()
        tokens = _tokens()
        for cut in model.cuts:
            colors = grade_colors(cut.name)
            dot = QLabel(self._legend)
            dot.setObjectName("gradeLegendDot")
            dot.setFixedSize(_LEGEND_DOT, _LEGEND_DOT)
            fill = colors[0] if colors else tokens["line.2"]
            dot.setStyleSheet(
                f"QLabel#gradeLegendDot {{ background: {fill};"
                f" border: 1px solid {colors[1] if colors else tokens['line.2']};"
                f" border-radius: 4px; }}"
            )
            text = QLabel(f"{cut.name} {cut.range_text()}".strip(), self._legend)
            text.setObjectName("gradeLegendText")
            text.setStyleSheet(f"QLabel#gradeLegendText {{ color: {tokens['text.2']}; }}")
            row = QWidget(self._legend)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, _SMALL_GAP, 0)
            row_layout.setSpacing(_SMALL_GAP)
            row_layout.addWidget(dot)
            row_layout.addWidget(text)
            self._legend_layout.addWidget(row)
        self._legend_layout.addStretch(1)
        self._legend.setVisible(bool(model.cuts))

    def _fill_how_to(self, model: ReferenceCardModel) -> None:
        steps = [step for step in model.how_to if step]
        if not steps:
            self._how_to.hide()
            self._how_to_title.hide()
            return
        self._how_to.setText("\n".join(f"• {step}" for step in steps))
        self._how_to.show()
        self._how_to_title.show()

    # ── look ───────────────────────────────────────────────────────
    def apply_theme(self) -> None:
        """Repaint the card from the tokens of the active theme (§5.3).

        ``setStyleSheet`` itself sends a change event, so the guard is what
        keeps «theme changed → repaint» from becoming an endless loop.
        """
        if self._applying_theme:
            return
        self._applying_theme = True
        try:
            tokens = _tokens()
            sheet = (
                f"QFrame#referenceCard {{ background: {tokens['surface.2']};"
                f" border: 1px solid {tokens['line.1']}; border-radius: 8px; }}"
                f" QLabel#referenceCardTitle {{ color: {tokens['text.1']}; }}"
                f" QLabel#referenceCardFullName {{ color: {tokens['text.2']}; }}"
                f" QLabel#referenceCardValue {{ color: {tokens['text.1']}; font-size: 15px; }}"
                f" QLabel#referenceCardNorm {{ color: {tokens['text.2']}; }}"
                f" QLabel#referenceCardHowToTitle {{ color: {tokens['text.2']}; font-weight: 600; }}"
                f" QLabel#referenceCardHowTo {{ color: {tokens['text.2']}; }}"
                f" QLabel#referenceCardSource {{ color: {tokens['text.3']}; }}"
                f" QPushButton#referenceCardOpen {{ color: {tokens['accent.text']};"
                f" background: transparent; border: none; padding: 0; text-align: left; }}"
                f" QPushButton#referenceCardOpen:hover {{ color: {tokens['accent']}; }}"
            )
            if sheet != self._stylesheet:
                self._stylesheet = sheet
                self.setStyleSheet(sheet)
            if self._model is not None:
                self._fill_legend(self._model)
            self.update()
        finally:
            self._applying_theme = False

    def changeEvent(self, event: QEvent) -> None:  # type: ignore[override]
        """Follow a theme switch (UD-09: colours come from tokens only)."""
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.apply_theme()
        super().changeEvent(event)

    # ── placement ──────────────────────────────────────────────────
    def popup_at(self, global_pos: QPoint, anchor: QRect | None = None) -> None:
        """Show the card at *global_pos*, kept inside the screen.

        ``anchor`` is the rectangle of the row the card belongs to: when the
        card would cover it, the card is placed below instead of above, so the
        row the physician reads stays visible.
        """
        self.adjustSize()
        screen = self.screen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)
        x = min(max(global_pos.x(), area.left() + 4), max(area.left() + 4, area.right() - self.width() - 4))
        y = global_pos.y()
        if anchor is not None and y < anchor.bottom() and anchor.top() < y + self.height():
            y = anchor.bottom() + 4  # below the row, so the row stays readable
        if y + self.height() > area.bottom() - 4:
            # Above the row when that fits, otherwise flush with the bottom.
            above = (anchor.top() if anchor is not None else global_pos.y()) - self.height() - 4
            fits = above >= area.top() + 4 and above + self.height() <= area.bottom() - 4
            y = above if fits else area.bottom() - 4 - self.height()
        self.move(x, max(y, area.top() + 4))
        self.show()
        self.raise_()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        """Esc closes the card (§4.7); a tooltip window gets no key otherwise."""
        if event.key() in (Qt.Key.Key_Escape,):
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_open_clicked(self) -> None:
        if self._model is not None and self._model.param_id:
            self.reference_requested.emit(self._model.param_id)


def show_reference_card(
    model: ReferenceCardModel,
    global_pos: QPoint,
    *,
    parent: QWidget | None = None,
    anchor: QRect | None = None,
) -> ReferenceCard:
    """Show (or reuse) the S2 card of *model* at *global_pos*.

    The host of a measurement row calls this after the 400 ms hover delay and
    hides the card when the pointer leaves the row. One card per ``parent`` is
    reused, so a row that is hovered twice does not stack windows.
    """
    card = parent.findChild(ReferenceCard, "referenceCard") if parent is not None else None
    if card is None:
        card = ReferenceCard(parent)
    card.set_model(model)
    card.popup_at(global_pos, anchor)
    return card


def card_for_measurement(
    param_id: str,
    *,
    value: float | None = None,
    unit: str = "",
    sex: str = "",
    language: str | None = None,
    label: str | None = None,
    full_name: str | None = None,
    value_text: str | None = None,
    decimals: int | None = None,
    scale: float | None = None,
) -> ReferenceCardModel:
    """The model of one handbook parameter (thin wrapper over the domain).

    Kept here so a host imports the card and its data from one place; the rules
    themselves live in :mod:`echo_personal_tool.domain.services.reference_card`.
    """
    return build_reference_card(
        param_id,
        value=value,
        unit=unit,
        sex=sex,
        language=language,
        label=label,
        full_name=full_name,
        value_text=value_text,
        decimals=decimals,
        scale=scale,
    )


def card_for_row(
    key: str,
    *,
    value: float | None = None,
    unit: str = "",
    sex: str = "",
    language: str | None = None,
    label: str | None = None,
    full_name: str | None = None,
    value_text: str | None = None,
    decimals: int | None = None,
) -> ReferenceCardModel:
    """The S2 model of one measurement row of the panel (UI-5, §4.7).

    ``key`` is the projection key of the study (``lv.lvedd``, TP-3 PR-2b); the
    translation to the handbook id is the same table the S1 window reads
    (:data:`PROJECTION_TO_HANDBOOK`).  A row the handbook has no binding for
    keeps its honest answer — «Нормы нет в справочнике» — instead of a guess;
    the label and the measured value still show.

    The value reads in the displayed ``unit`` (the row may show cm under the
    ASE switch or cm/s under PW): the domain converts the handbook ranges to
    that unit.
    """
    from echo_personal_tool.domain.services.reference_topics import PROJECTION_TO_HANDBOOK

    param_id = PROJECTION_TO_HANDBOOK.get(key, "")
    return build_reference_card(
        param_id,
        value=value,
        unit=unit,
        sex=sex,
        language=language,
        label=label,
        full_name=full_name,
        value_text=value_text,
        decimals=decimals,
    )
