"""EchoPac-style Measures tab menu (from Measures-block.md)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.presentation.measurement_action import MeasurementAction

_MENU_BUTTON_HEIGHT_PX = 18
_ACCORDION_ANIM_MS = 180


@dataclass(frozen=True)
class _MenuButton:
    label: str
    action: MeasurementAction | None = None
    view: str = "A4C"
    phase: str = "ED"
    caliper_label: str = ""
    doppler_peak: str = ""
    doppler_interval: str = ""
    doppler_trace: str = ""
    enabled: bool = True


def _btn(
    label: str,
    action: MeasurementAction | None = None,
    *,
    view: str = "A4C",
    phase: str = "ED",
    caliper_label: str = "",
    doppler_peak: str = "",
    doppler_interval: str = "",
    doppler_trace: str = "",
    enabled: bool = True,
) -> _MenuButton:
    return _MenuButton(
        label=label,
        action=action,
        view=view,
        phase=phase,
        caliper_label=caliper_label,
        doppler_peak=doppler_peak,
        doppler_interval=doppler_interval,
        doppler_trace=doppler_trace,
        enabled=enabled,
    )


_MENU: tuple[tuple[str, tuple[_MenuButton, ...]], ...] = (
    (
        "Общие",
        (
            _btn("Калипер", MeasurementAction.CALIPER),
            _btn("Площадь", MeasurementAction.SPLINE_AREA),
            _btn("Объём", MeasurementAction.SPLINE_VOLUME),
        ),
    ),
    (
        "Left Ventricle",
        (
            _btn("All Diastole", MeasurementAction.LV2D_ALL_DIASTOLE),
            _btn("ES Diameter", MeasurementAction.LV2D_ES),
            _btn("LVEF Simpson EDV", MeasurementAction.MANUAL_SIMPSON, view="A4C", phase="ED"),
            _btn("LVEF Simpson ESV", MeasurementAction.MANUAL_SIMPSON, view="A4C", phase="ES"),
            _btn("Simpson Biplane EDV", MeasurementAction.MANUAL_SIMPSON, view="A2C", phase="ED"),
            _btn("Simpson Biplane ESV", MeasurementAction.MANUAL_SIMPSON, view="A2C", phase="ES"),
        ),
    ),
    (
        "LV Auto",
        (
            _btn("LVEF Simpson EDV", MeasurementAction.MBS_SIMPSON, view="A4C", phase="ED"),
            _btn("LVEF Simpson ESV", MeasurementAction.MBS_SIMPSON, view="A4C", phase="ES"),
        ),
    ),
    (
        "Aorta",
        (
            _btn("AV", caliper_label="AV"),
            _btn("Annulus", caliper_label="Annulus"),
            _btn("Ao Sinus", caliper_label="Ao Sinus"),
            _btn("Ao Junction", caliper_label="Ao Junction"),
            _btn("Prox Ao", caliper_label="Prox Ao"),
        ),
    ),
    (
        "Left Atrium",
        (
            _btn("A-P LA", MeasurementAction.LA_DIAMETER),
            _btn("LAV 4C", MeasurementAction.LAV_4C),
            _btn("LAV 2C", MeasurementAction.LAV_BI),
        ),
    ),
    (
        "Right Atrium",
        (
            _btn("RA", MeasurementAction.RA_DIAMETER),
            _btn("RAV 4C", MeasurementAction.RAV_VOLUME),
        ),
    ),
    (
        "Right Ventricle",
        (
            _btn("RVOT", caliper_label="RVOT"),
            _btn("RV basal", MeasurementAction.RV_BASAL),
            _btn("RV mid", caliper_label="RV mid"),
            _btn("TAPSE", MeasurementAction.RV_TAPSE),
            _btn("s' RV", MeasurementAction.RV_S_PRIME),
            _btn("FAC", MeasurementAction.RV_FAC, view="A4C"),
        ),
    ),
    (
        "Diastology",
        (
            _btn("Peak E/DT/A", MeasurementAction.DOPPLER_MITRAL_INFLOW),
            _btn("Peak E", doppler_peak="E"),
            _btn("Peak A", doppler_peak="A"),
            _btn("DT", doppler_interval="DT"),
            _btn("e'septal", doppler_peak="e_sept"),
            _btn("e'lateral", doppler_peak="e_lat"),
            _btn("IVRT", doppler_interval="IVRT"),
        ),
    ),
    (
        "MV/AV",
        (
            _btn("Trace MV", doppler_trace="VTI MV"),
            _btn("Trace MR", doppler_trace="VTI MR"),
            _btn("Vpeak MV", doppler_peak="Vmax"),
            _btn("Trace AV", MeasurementAction.DOPPLER_TRACE),
            _btn("Trace AR", doppler_trace="VTI AR"),
            _btn("Vpeak AV", doppler_peak="Vmax"),
            _btn("LVOTd", caliper_label="LVOTd"),
            _btn("MVd", caliper_label="MVd"),
        ),
    ),
    (
        "TV/PV",
        (
            _btn("TRpeak", doppler_peak="TR Vmax"),
            _btn("Trace TR", doppler_trace="VTI TR"),
            _btn("Trace PR", doppler_trace="VTI PR"),
        ),
    ),
    (
        "Strain",
        (
            _btn("Speckle Tracking", MeasurementAction.SPECKLE_TRACKING, view="A4C"),
        ),
    ),
)


def style_menu_button(button: QPushButton) -> None:
    button.setFixedHeight(_MENU_BUTTON_HEIGHT_PX)
    button.setCursor(Qt.CursorShape.PointingHandCursor)


class MeasuresAccordionSection(QWidget):
    """Clickable section header; items expand downward with animation."""

    clicked = Signal(object)

    def __init__(
        self,
        title: str,
        buttons: tuple[_MenuButton, ...],
        emit_handler: Callable[[_MenuButton], Callable[[], None]],
        *,
        button_registry: list[tuple[QPushButton, _MenuButton]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("measuresSection")
        self._expanded = False
        self._content_height = 0

        self._header = QPushButton(title)
        self._header.setObjectName("measuresSectionTitle")
        self._header.setFlat(True)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.clicked.connect(self._on_header_clicked)

        self._body = QWidget()
        self._body.setObjectName("measuresSectionBody")
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(8, 0, 4, 4)
        body_layout.setSpacing(4)
        for spec in buttons:
            button = QPushButton(spec.label)
            button.setEnabled(spec.enabled)
            style_menu_button(button)
            if not spec.enabled:
                button.setToolTip("A2C auto — в следующей версии")
            if spec.enabled:
                button.clicked.connect(emit_handler(spec))
            body_layout.addWidget(button)
            if button_registry is not None:
                button_registry.append((button, spec))

        self._animation = QPropertyAnimation(self._body, b"maximumHeight", self)
        self._animation.setDuration(_ACCORDION_ANIM_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._body)
        self._body.setMaximumHeight(0)

    def is_expanded(self) -> bool:
        return self._expanded

    def expand(self, *, animated: bool = True) -> None:
        self._content_height = self._body.sizeHint().height()
        self._expanded = True
        self._header.setProperty("expanded", True)
        self._header.style().unpolish(self._header)
        self._header.style().polish(self._header)
        if animated:
            self._animation.stop()
            self._animation.setStartValue(self._body.maximumHeight())
            self._animation.setEndValue(self._content_height)
            self._animation.start()
        else:
            self._body.setMaximumHeight(self._content_height)

    def collapse(self, *, animated: bool = True) -> None:
        self._expanded = False
        self._header.setProperty("expanded", False)
        self._header.style().unpolish(self._header)
        self._header.style().polish(self._header)
        if animated:
            self._animation.stop()
            self._animation.setStartValue(self._body.maximumHeight())
            self._animation.setEndValue(0)
            self._animation.start()
        else:
            self._body.setMaximumHeight(0)

    def contains_button(self, button: QPushButton) -> bool:
        return button in self._body.findChildren(QPushButton)

    def _on_header_clicked(self) -> None:
        self.clicked.emit(self)


class MeasuresMenuWidget(QWidget):
    """Grouped measurement actions for the Measures tab."""

    action_requested = Signal(object, str, str, str)

    _BLINK_STYLE = "background-color: #fff59d; color: #1a2430; font-weight: bold;"
    _NORMAL_STYLE = ""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._sections: list[MeasuresAccordionSection] = []
        self._tool_buttons: list[tuple[QPushButton, _MenuButton]] = []
        self._blink_target: QPushButton | None = None
        self._blink_on = False
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_blink)

        for group_title, buttons in _MENU:
            section = MeasuresAccordionSection(
                group_title,
                buttons,
                self._make_handler,
                button_registry=self._tool_buttons,
                parent=inner,
            )
            section.clicked.connect(self._on_section_clicked)
            self._sections.append(section)
            layout.addWidget(section)

        layout.addStretch(1)
        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def set_doppler_tool_availability(
        self,
        *,
        time_ok: bool,
    ) -> None:
        for button, spec in self._tool_buttons:
            needs_time = bool(
                spec.doppler_interval
                or spec.doppler_trace
                or spec.action == MeasurementAction.DOPPLER_MITRAL_INFLOW
                or spec.action == MeasurementAction.DOPPLER_TRACE
            )
            if not needs_time:
                continue
            button.setEnabled(time_ok)

    def highlight_action(
        self,
        action: MeasurementAction,
        *,
        view: str = "A4C",
        phase: str = "ED",
    ) -> None:
        self.clear_highlight()
        for button, spec in self._tool_buttons:
            if not spec.enabled or spec.action != action:
                continue
            if action == MeasurementAction.RV_FAC:
                if spec.view == view:
                    self._blink_target = button
                    self._blink_timer.start()
                    self._ensure_section_visible(button)
                    return
                continue
            if spec.view == view and spec.phase == phase:
                self._blink_target = button
                self._blink_timer.start()
                self._ensure_section_visible(button)
                return

    def clear_highlight(self) -> None:
        self._blink_timer.stop()
        if self._blink_target is not None:
            self._blink_target.setStyleSheet(self._NORMAL_STYLE)
        self._blink_target = None
        self._blink_on = False

    def _toggle_blink(self) -> None:
        if self._blink_target is None:
            return
        self._blink_on = not self._blink_on
        self._blink_target.setStyleSheet(
            self._BLINK_STYLE if self._blink_on else self._NORMAL_STYLE
        )

    def _ensure_section_visible(self, button: QPushButton) -> None:
        for section in self._sections:
            if section.contains_button(button) and not section.is_expanded():
                for other in self._sections:
                    if other is not section and other.is_expanded():
                        other.collapse()
                section.expand()
                break

    def _on_section_clicked(self, section: MeasuresAccordionSection) -> None:
        if section.is_expanded():
            section.collapse()
            return
        for other in self._sections:
            if other is not section and other.is_expanded():
                other.collapse()
        section.expand()

    def _make_handler(self, spec: _MenuButton) -> Callable[[], None]:
        def emit() -> None:
            self.clear_highlight()
            action = spec.action
            extra = ""
            if spec.doppler_peak:
                action = MeasurementAction.DOPPLER_PEAK
                extra = spec.doppler_peak
            elif spec.doppler_interval:
                action = MeasurementAction.DOPPLER_INTERVAL
                extra = spec.doppler_interval
            elif spec.doppler_trace:
                action = MeasurementAction.DOPPLER_TRACE
                extra = spec.doppler_trace
            elif spec.caliper_label:
                action = MeasurementAction.CALIPER
                extra = spec.caliper_label
            elif action is None:
                action = MeasurementAction.CALIPER
            self.action_requested.emit(action, spec.view, spec.phase, extra)

        return emit
