"""EchoPac-style hierarchical measurement worksheet."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.presentation.measurement_action import MeasurementAction

RowState = Literal["pending", "in_progress", "done"]


class _ItemRole:
    ACTION = Qt.ItemDataRole.UserRole
    PARAM_KEY = Qt.ItemDataRole.UserRole + 1


@dataclass(frozen=True)
class WorksheetRow:
    action: MeasurementAction | None
    label: str
    param_key: str | None = None
    view: str | None = None
    phase: str | None = None
    children: tuple[WorksheetRow, ...] = ()


_WORKSHEET_TREE: tuple[WorksheetRow, ...] = (
    WorksheetRow(None, "Setup", children=(
        WorksheetRow(MeasurementAction.CALIBRATION, "Калибровка"),
        WorksheetRow(MeasurementAction.CALIPER, "Caliper"),
        WorksheetRow(MeasurementAction.RESET, "Сброс"),
    )),
    WorksheetRow(None, "LV — Simpson", children=(
        WorksheetRow(MeasurementAction.MANUAL_SIMPSON, "A4C ED", "lv_a4c_ed", "A4C", "ED"),
        WorksheetRow(MeasurementAction.MANUAL_SIMPSON, "A4C ES", "lv_a4c_es", "A4C", "ES"),
        WorksheetRow(MeasurementAction.MANUAL_SIMPSON, "A2C ED", "lv_a2c_ed", "A2C", "ED"),
        WorksheetRow(MeasurementAction.MANUAL_SIMPSON, "A2C ES", "lv_a2c_es", "A2C", "ES"),
        WorksheetRow(MeasurementAction.MBS_SIMPSON, "MBS A4C ED", "mbs_a4c_ed", "A4C", "ED"),
        WorksheetRow(MeasurementAction.MBS_SIMPSON, "MBS A4C ES", "mbs_a4c_es", "A4C", "ES"),
        WorksheetRow(MeasurementAction.MBS_SIMPSON, "MBS A2C ED", "mbs_a2c_ed", "A2C", "ED"),
        WorksheetRow(MeasurementAction.MBS_SIMPSON, "MBS A2C ES", "mbs_a2c_es", "A2C", "ES"),
        WorksheetRow(None, "LVEF Bi", "lvef_bi"),
    )),
    WorksheetRow(None, "LV — 2D", children=(
        WorksheetRow(MeasurementAction.LV2D_ALL_DIASTOLE, "All Diastole", "lv2d_ed"),
        WorksheetRow(MeasurementAction.LV2D_ES, "ESD Systole", "lvesd"),
        WorksheetRow(None, "LVM", "lvm"),
    )),
    WorksheetRow(None, "LA / RA", children=(
        WorksheetRow(MeasurementAction.LA_DIAMETER, "ЛП ПЗР", "la_dim"),
        WorksheetRow(MeasurementAction.LAV_4C, "LAV 4C", "lav_4c"),
        WorksheetRow(MeasurementAction.LAV_BI, "LAV Bi", "lav_bi"),
        WorksheetRow(MeasurementAction.RA_DIAMETER, "ПП", "ra_dim"),
        WorksheetRow(MeasurementAction.RA_AREA, "S ПП", "ra_area"),
        WorksheetRow(MeasurementAction.RAV_VOLUME, "RAV", "rav"),
    )),
    WorksheetRow(None, "RV", children=(
        WorksheetRow(MeasurementAction.RV_TAPSE, "TAPSE", "tapse"),
        WorksheetRow(MeasurementAction.RV_BASAL, "RV Base", "rv_basal"),
        WorksheetRow(MeasurementAction.RV_S_PRIME, "s' (TDI)", "rv_s_prime"),
        WorksheetRow(MeasurementAction.RV_FAC_ED, "FAC ED area", "rv_fac_ed"),
        WorksheetRow(MeasurementAction.RV_FAC_ES, "FAC ES area", "rv_fac_es"),
        WorksheetRow(None, "FAC %", "rv_fac"),
    )),
    WorksheetRow(None, "Doppler — Diastology", children=(
        WorksheetRow(MeasurementAction.DOPPLER_PEAK, "Peak markers (E, A, e')", "dop_peak"),
        WorksheetRow(MeasurementAction.DOPPLER_INTERVAL, "Intervals (DT, IVRT, AT)", "dop_int"),
        WorksheetRow(None, "E", "dop_e"),
        WorksheetRow(None, "A", "dop_a"),
        WorksheetRow(None, "E/A", "dop_ea"),
        WorksheetRow(None, "e' sept", "dop_ep_sept"),
        WorksheetRow(None, "e' lat", "dop_ep_lat"),
        WorksheetRow(None, "E/e' avg", "dop_ee"),
        WorksheetRow(None, "E/e' sept", "dop_ee_sept"),
        WorksheetRow(None, "E/e' lat", "dop_ee_lat"),
        WorksheetRow(None, "e'/a'", "dop_epa"),
        WorksheetRow(None, "DT", "dop_dt"),
        WorksheetRow(None, "IVRT", "dop_ivrt"),
        WorksheetRow(None, "Diastolic grade", "diast_grade"),
    )),
    WorksheetRow(None, "Doppler — CW / Regurg", children=(
        WorksheetRow(MeasurementAction.DOPPLER_TRACE, "VTI trace", "dop_vti"),
        WorksheetRow(None, "Vmax / TR Vmax", "dop_vmax"),
        WorksheetRow(None, "VTI", "dop_vti_val"),
        WorksheetRow(None, "PGpeak", "dop_pgpeak"),
        WorksheetRow(None, "PGmean", "dop_pgmean"),
    )),
    WorksheetRow(None, "Indexed (BSA)", children=(
        WorksheetRow(None, "BSA", "bsa"),
        WorksheetRow(None, "EDVi Simpson", "edvi"),
        WorksheetRow(None, "ESVi Simpson", "esvi"),
    )),
)


class MeasurementWorksheet(QWidget):
    """Multi-level measurement list with pending/done states."""

    action_requested = Signal(object, str, str)  # MeasurementAction, view, phase

    _BLINK_BG = QColor("#fff59d")
    _DONE_BG = QColor("#e8f5e9")
    _PENDING_BG = QColor("#ffffff")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Measurement", "Value"])
        self._tree.setColumnWidth(0, 180)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._rows_by_key: dict[str, QTreeWidgetItem] = {}
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_blink)
        self._blink_item: QTreeWidgetItem | None = None
        self._blink_on = False
        self._build_tree()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree)

    def _build_tree(self) -> None:
        self._tree.clear()
        self._rows_by_key.clear()
        for root_row in _WORKSHEET_TREE:
            self._append_row(None, root_row)

    def _append_row(self, parent: QTreeWidgetItem | None, row: WorksheetRow) -> QTreeWidgetItem:
        if parent is None:
            item = QTreeWidgetItem([row.label, ""])
        else:
            item = QTreeWidgetItem(parent, [row.label, ""])
        if row.action is not None:
            item.setData(0, _ItemRole.ACTION, row.action.value)
        if row.param_key:
            item.setData(0, _ItemRole.PARAM_KEY, row.param_key)
            self._rows_by_key[row.param_key] = item
        if row.view:
            item.setData(0, Qt.ItemDataRole.UserRole + 2, row.view)
        if row.phase:
            item.setData(0, Qt.ItemDataRole.UserRole + 3, row.phase)
        item.setExpanded(True)
        for child in row.children:
            self._append_row(item, child)
        if parent is None:
            self._tree.addTopLevelItem(item)
        return item

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        action_value = item.data(0, _ItemRole.ACTION)
        if not action_value:
            return
        action = MeasurementAction(action_value)
        view = item.data(0, Qt.ItemDataRole.UserRole + 2) or "A4C"
        phase = item.data(0, Qt.ItemDataRole.UserRole + 3) or "ED"
        self.action_requested.emit(action, str(view), str(phase))

    def update_from_snapshot(
        self,
        snapshot: MeasurementSnapshot | None,
        contours: tuple[Contour, ...] = (),
    ) -> None:
        for item in self._rows_by_key.values():
            item.setText(1, "")
            item.setBackground(0, self._PENDING_BG)

        if snapshot is None:
            return

        self._set_value("lvef_bi", snapshot.lvef.lvef_percent if snapshot.lvef else None, "%")
        self._set_value("lvesd", self._linear(snapshot, "LVESD"), "mm")
        self._set_value("la_dim", self._linear(snapshot, "LA"), "mm")

        dop = snapshot.doppler
        if dop:
            self._set_value("dop_e", dop.e_cm_s, "cm/s")
            self._set_value("dop_a", dop.a_cm_s, "cm/s")
            self._set_value("dop_ea", dop.e_a_ratio, "")
            self._set_value("dop_ep_sept", dop.e_prime_sept_cm_s, "cm/s")
            self._set_value("dop_ep_lat", dop.e_prime_lat_cm_s, "cm/s")
            self._set_value("dop_ee", dop.e_over_e_prime, "")
            self._set_value("dop_ee_sept", dop.e_over_e_prime_sept, "")
            self._set_value("dop_ee_lat", dop.e_over_e_prime_lat, "")
            self._set_value("dop_epa", dop.e_prime_over_a_prime, "")
            self._set_value("dop_dt", dop.dt_ms, "ms")
            self._set_value("dop_ivrt", dop.ivrt_ms, "ms")
            self._set_value("dop_vmax", dop.tr_vmax_cm_s or dop.vpeak_cm_s, "cm/s")
            self._set_value("dop_vti_val", dop.vti_cm, "cm")
            self._set_value("dop_pgpeak", dop.pgpeak_mmhg, "mmHg")
            self._set_value("dop_pgmean", dop.pgmean_mmhg, "mmHg")

        if snapshot.lvef and snapshot.lvef.lvef_percent is not None:
            self._mark_done("lvef_bi")

        for key, view, phase in (
            ("lv_a4c_ed", "A4C", "ED"),
            ("lv_a4c_es", "A4C", "ES"),
            ("lv_a2c_ed", "A2C", "ED"),
            ("lv_a2c_es", "A2C", "ES"),
            ("mbs_a4c_ed", "A4C", "ED"),
            ("mbs_a4c_es", "A4C", "ES"),
            ("mbs_a2c_ed", "A2C", "ED"),
            ("mbs_a2c_es", "A2C", "ES"),
        ):
            if self._has_contour(contours, "LV", view, phase):
                self._mark_done(key)

        if snapshot.la_simpson:
            if snapshot.la_simpson.a4c:
                self._mark_done("lav_4c")
            if snapshot.la_simpson.a4c and snapshot.la_simpson.a2c:
                self._mark_done("lav_bi")

        if snapshot.la_volume and snapshot.la_volume.volume_ml is not None:
            self._set_value("lav_4c", snapshot.la_volume.volume_ml, "mL")

        if snapshot.lvm_g is not None:
            self._set_value("lvm", snapshot.lvm_g, "g")

        if snapshot.rv_fac_percent is not None:
            self._set_value("rv_fac", snapshot.rv_fac_percent, "%")
            self._mark_done("rv_fac")

        if snapshot.rv_simpson and snapshot.rv_simpson.max_volume_ml is not None:
            self._set_value("rav", snapshot.rv_simpson.max_volume_ml, "mL")

        if snapshot.diastology_grade:
            self._set_value("diast_grade", snapshot.diastology_grade, "")

        idx = snapshot.indexed
        if idx:
            self._set_value("bsa", idx.bsa_m2, "m²")
            self._set_value("edvi", idx.simpson_edvi_ml_m2, "mL/m²")
            self._set_value("esvi", idx.simpson_esvi_ml_m2, "mL/m²")

    def start_es_prompt(self, mode: Literal["manual", "mbs"], view: str) -> None:
        self.stop_es_prompt()
        view_key = "A4C" if view.upper() in {"A4C", "4C"} else "A2C"
        prefix = "mbs" if mode == "mbs" else "lv"
        short = "a4c" if view_key == "A4C" else "a2c"
        key = f"{prefix}_{short}_es"
        self._blink_item = self._rows_by_key.get(key)
        if self._blink_item is not None:
            self._blink_timer.start()

    def stop_es_prompt(self) -> None:
        self._blink_timer.stop()
        if self._blink_item is not None:
            bg = self._DONE_BG if self._blink_item.text(1) else self._PENDING_BG
            self._blink_item.setBackground(0, bg)
        self._blink_item = None
        self._blink_on = False

    def _toggle_blink(self) -> None:
        if self._blink_item is None:
            return
        self._blink_on = not self._blink_on
        self._blink_item.setBackground(0, self._BLINK_BG if self._blink_on else self._PENDING_BG)

    def _set_value(
        self,
        key: str,
        value: float | str | None,
        suffix: str,
        *,
        key_override: str | None = None,
    ) -> None:
        item = self._rows_by_key.get(key_override or key)
        if item is None or value is None:
            return
        if isinstance(value, str):
            text = value
        elif suffix == "%":
            text = f"{value:.1f}{suffix}"
        elif suffix:
            text = f"{value:.1f} {suffix}".strip()
        else:
            text = f"{value:.2f}"
        item.setText(1, text)
        self._mark_done(key_override or key)

    def _mark_done(self, key: str) -> None:
        item = self._rows_by_key.get(key)
        if item is not None and item is not self._blink_item:
            item.setBackground(0, self._DONE_BG)

    @staticmethod
    def _linear(snapshot: MeasurementSnapshot, label: str) -> float | None:
        for measurement in snapshot.linear_measurements:
            if measurement.label.upper() == label.upper():
                return measurement.millimeter_length
        return None

    @staticmethod
    def _has_contour(
        contours: tuple[Contour, ...],
        chamber: str,
        view: str,
        phase: str,
    ) -> bool:
        for contour in contours:
            if (
                contour.chamber.upper() == chamber.upper()
                and contour.view.upper() == view.upper()
                and contour.phase.upper() == phase.upper()
            ):
                return True
        return False
