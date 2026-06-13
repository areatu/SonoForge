"""Right-panel measurement workflow buttons (replaces keyboard shortcuts)."""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_VIEW_MAP = {"4C": "A4C", "2C": "A2C"}


class MeasurementToolsPanel(QWidget):
    """Grouped buttons for Simpson, 2D linear, LA, and RV measurements."""

    manual_simpson_requested = Signal(str, str)
    mbs_simpson_requested = Signal(str, str)
    lv2d_all_diastole_requested = Signal()
    lv2d_es_requested = Signal()
    la_diameter_requested = Signal()
    la_volume_requested = Signal()
    rv_basal_requested = Signal()
    rv_tapse_requested = Signal()

    _BLINK_STYLE = "background-color: #fff59d; font-weight: bold;"
    _NORMAL_STYLE = ""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manual_buttons: dict[tuple[str, str], QPushButton] = {}
        self._mbs_buttons: dict[tuple[str, str], QPushButton] = {}
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_blink)
        self._blink_target: QPushButton | None = None
        self._blink_on = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self._build_manual_group())
        layout.addWidget(self._build_mbs_group())
        layout.addWidget(self._build_lv2d_group())
        layout.addWidget(self._build_la_group())
        layout.addWidget(self._build_rv_group())
        layout.addStretch(1)

    def _build_view_column(
        self,
        view: str,
        ed_label: str,
        es_label: str,
        *,
        registry: dict[tuple[str, str], QPushButton],
        signal: Signal,
    ) -> QVBoxLayout:
        col = QVBoxLayout()
        col.addWidget(QLabel(view))
        btn_ed = QPushButton(ed_label)
        btn_ed.clicked.connect(
            lambda _checked=False, v=view: signal.emit(_VIEW_MAP[v], "ED")
        )
        registry[(view, "ED")] = btn_ed
        col.addWidget(btn_ed)
        btn_es = QPushButton(es_label)
        btn_es.clicked.connect(
            lambda _checked=False, v=view: signal.emit(_VIEW_MAP[v], "ES")
        )
        registry[(view, "ES")] = btn_es
        col.addWidget(btn_es)
        return col

    def _build_manual_group(self) -> QGroupBox:
        group = QGroupBox("Manual")
        row = QHBoxLayout(group)
        row.addLayout(
            self._build_view_column(
                "4C",
                "Diastole",
                "Systole",
                registry=self._manual_buttons,
                signal=self.manual_simpson_requested,
            )
        )
        row.addLayout(
            self._build_view_column(
                "2C",
                "Diastole",
                "Systole",
                registry=self._manual_buttons,
                signal=self.manual_simpson_requested,
            )
        )
        return group

    def _build_mbs_group(self) -> QGroupBox:
        group = QGroupBox("MBS")
        row = QHBoxLayout(group)
        row.addLayout(
            self._build_view_column(
                "4C",
                "EDV Auto",
                "ESV Auto",
                registry=self._mbs_buttons,
                signal=self.mbs_simpson_requested,
            )
        )
        row.addLayout(
            self._build_view_column(
                "2C",
                "EDV Auto",
                "ESV Auto",
                registry=self._mbs_buttons,
                signal=self.mbs_simpson_requested,
            )
        )
        return group

    def start_es_prompt(self, mode: Literal["manual", "mbs"], view: str) -> None:
        self.stop_es_prompt()
        registry = self._manual_buttons if mode == "manual" else self._mbs_buttons
        self._blink_target = registry.get((view, "ES"))
        if self._blink_target is not None:
            self._blink_timer.start()

    def stop_es_prompt(self) -> None:
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

    def _build_lv2d_group(self) -> QGroupBox:
        group = QGroupBox("LV-2D")
        row = QHBoxLayout(group)
        btn_all_ed = QPushButton("All Diastole")
        btn_all_ed.setToolTip("IVSd → LVEDD → LVPWd (МЖП, КДР, ЗСЛЖ)")
        btn_all_ed.clicked.connect(self.lv2d_all_diastole_requested.emit)
        row.addWidget(btn_all_ed)
        btn_esd = QPushButton("ESD Systole")
        btn_esd.setToolTip("LVESD (КСР)")
        btn_esd.clicked.connect(self.lv2d_es_requested.emit)
        row.addWidget(btn_esd)
        return group

    def _build_la_group(self) -> QGroupBox:
        group = QGroupBox("Left atrium")
        row = QHBoxLayout(group)
        btn_la = QPushButton("LA AP")
        btn_la.setToolTip("Линейное измерение ЛП (ПЗР)")
        btn_la.clicked.connect(self.la_diameter_requested.emit)
        row.addWidget(btn_la)
        btn_lav = QPushButton("LAV")
        btn_lav.setToolTip("Объём ЛП 4C, метод площадь–длина")
        btn_lav.clicked.connect(self.la_volume_requested.emit)
        row.addWidget(btn_lav)
        return group

    def _build_rv_group(self) -> QGroupBox:
        group = QGroupBox("Right ventricle")
        row = QHBoxLayout(group)
        btn_basal = QPushButton("RV basal")
        btn_basal.clicked.connect(self.rv_basal_requested.emit)
        row.addWidget(btn_basal)
        btn_tapse = QPushButton("TAPSE")
        btn_tapse.clicked.connect(self.rv_tapse_requested.emit)
        row.addWidget(btn_tapse)
        return group
