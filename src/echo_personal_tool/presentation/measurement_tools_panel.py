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

from echo_personal_tool.infrastructure.i18n import tr

_VIEW_MAP = {"4C": "A4C", "2C": "A2C"}


class MeasurementToolsPanel(QWidget):
    """Grouped buttons for Simpson, 2D linear, LA, RA, and RV measurements."""

    manual_simpson_requested = Signal(str, str)
    mbs_simpson_requested = Signal(str, str)
    calibration_requested = Signal()
    caliper_requested = Signal()
    reset_measurements_requested = Signal()
    lv2d_all_diastole_requested = Signal()
    lv2d_es_requested = Signal()
    la_diameter_requested = Signal()
    lav_4c_requested = Signal()
    lav_bi_requested = Signal()
    ra_diameter_requested = Signal()
    ra_area_requested = Signal()
    rav_volume_requested = Signal()
    rv_basal_requested = Signal()
    rv_tapse_requested = Signal()
    rv_s_prime_requested = Signal()

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

        layout.addWidget(self._build_setup_group())
        layout.addWidget(self._build_manual_group())
        layout.addWidget(self._build_mbs_group())
        layout.addWidget(self._build_lv2d_group())
        layout.addWidget(self._build_la_group())
        layout.addWidget(self._build_ra_group())
        layout.addWidget(self._build_rv_group())
        layout.addStretch(1)

    def reload_text(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr
        for (view, phase), btn in self._manual_buttons.items():
            if phase == "ED":
                btn.setText(tr(f"menu.{view.lower()}_ed"))
            else:
                btn.setText(tr(f"menu.{view.lower()}_es"))

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
        btn_ed.clicked.connect(lambda _checked=False, v=view: signal.emit(_VIEW_MAP[v], "ED"))
        registry[(view, "ED")] = btn_ed
        col.addWidget(btn_ed)
        btn_es = QPushButton(es_label)
        btn_es.clicked.connect(lambda _checked=False, v=view: signal.emit(_VIEW_MAP[v], "ES"))
        registry[(view, "ES")] = btn_es
        col.addWidget(btn_es)
        return col

    def _build_manual_group(self) -> QGroupBox:
        group = QGroupBox(tr("tools.manual"))
        row = QHBoxLayout(group)
        row.addLayout(
            self._build_view_column(
                "4C",
                tr("tools.ed"),
                tr("tools.es"),
                registry=self._manual_buttons,
                signal=self.manual_simpson_requested,
            )
        )
        row.addLayout(
            self._build_view_column(
                "2C",
                tr("tools.ed"),
                tr("tools.es"),
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
                tr("tools.ed_auto"),
                tr("tools.es_auto"),
                registry=self._mbs_buttons,
                signal=self.mbs_simpson_requested,
            )
        )
        row.addLayout(
            self._build_view_column(
                "2C",
                tr("tools.ed_auto"),
                tr("tools.es_auto"),
                registry=self._mbs_buttons,
                signal=self.mbs_simpson_requested,
            )
        )
        return group

    def _build_setup_group(self) -> QGroupBox:
        group = QGroupBox(tr("tools.setup"))
        row = QHBoxLayout(group)
        btn_cal = QPushButton(tr("tools.calibrate"))
        btn_cal.setToolTip(tr("tools.calibrate_tip"))
        btn_cal.clicked.connect(self.calibration_requested.emit)
        row.addWidget(btn_cal)
        btn_caliper = QPushButton(tr("tools.caliper"))
        btn_caliper.setToolTip(tr("tools.caliper_tip"))
        btn_caliper.clicked.connect(self.caliper_requested.emit)
        row.addWidget(btn_caliper)
        btn_reset = QPushButton(tr("tools.reset"))
        btn_reset.setToolTip(tr("tools.reset_tip"))
        btn_reset.clicked.connect(self.reset_measurements_requested.emit)
        row.addWidget(btn_reset)
        row.addStretch(1)
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
        group = QGroupBox(tr("tools.lv2d"))
        row = QHBoxLayout(group)
        btn_all_ed = QPushButton(tr("tools.lv2d_all_diastole"))
        btn_all_ed.setToolTip(tr("tools.lv2d_all_diastole_tip"))
        btn_all_ed.clicked.connect(self.lv2d_all_diastole_requested.emit)
        row.addWidget(btn_all_ed)
        btn_esd = QPushButton(tr("tools.lv2d_es"))
        btn_esd.setToolTip(tr("tools.lv2d_es_tip"))
        btn_esd.clicked.connect(self.lv2d_es_requested.emit)
        row.addWidget(btn_esd)
        return group

    def _build_la_group(self) -> QGroupBox:
        group = QGroupBox(tr("tools.la"))
        row = QHBoxLayout(group)
        btn_ap = QPushButton(tr("tools.la_diameter"))
        btn_ap.setToolTip(tr("tools.la_diameter_tip"))
        btn_ap.clicked.connect(self.la_diameter_requested.emit)
        row.addWidget(btn_ap)
        btn_lav_4c = QPushButton(tr("tools.lav_4c"))
        btn_lav_4c.setToolTip(tr("tools.lav_4c_tip"))
        btn_lav_4c.clicked.connect(self.lav_4c_requested.emit)
        row.addWidget(btn_lav_4c)
        btn_lav_bi = QPushButton(tr("tools.lav_2c"))
        btn_lav_bi.setToolTip(tr("tools.lav_2c_tip"))
        btn_lav_bi.clicked.connect(self.lav_bi_requested.emit)
        row.addWidget(btn_lav_bi)
        return group

    def _build_ra_group(self) -> QGroupBox:
        group = QGroupBox(tr("tools.ra"))
        row = QHBoxLayout(group)
        btn_ra = QPushButton(tr("tools.ra_diameter"))
        btn_ra.setToolTip(tr("tools.ra_diameter_tip"))
        btn_ra.clicked.connect(self.ra_diameter_requested.emit)
        row.addWidget(btn_ra)
        btn_area = QPushButton(tr("tools.ra_area"))
        btn_area.setToolTip(tr("tools.ra_area_tip"))
        btn_area.clicked.connect(self.ra_area_requested.emit)
        row.addWidget(btn_area)
        btn_rav = QPushButton(tr("tools.rav"))
        btn_rav.setToolTip(tr("tools.rav_tip"))
        btn_rav.clicked.connect(self.rav_volume_requested.emit)
        row.addWidget(btn_rav)
        return group

    def _build_rv_group(self) -> QGroupBox:
        group = QGroupBox(tr("tools.rv"))
        row = QHBoxLayout(group)
        btn_tapse = QPushButton("TAPSE")
        btn_tapse.clicked.connect(self.rv_tapse_requested.emit)
        row.addWidget(btn_tapse)
        btn_basal = QPushButton(tr("tools.rv_basal"))
        btn_basal.clicked.connect(self.rv_basal_requested.emit)
        row.addWidget(btn_basal)
        btn_s_prime = QPushButton("s'")
        btn_s_prime.setToolTip(tr("tools.rv_s_prime_tip"))
        btn_s_prime.setEnabled(False)
        btn_s_prime.clicked.connect(self.rv_s_prime_requested.emit)
        row.addWidget(btn_s_prime)
        return group
