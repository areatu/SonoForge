"""Automatic derivative Doppler chains (Этап 2 backlog).

Shows the computed derivative values (SV, CO, AVA, DVI, MR RVol, MR RF, …)
as soon as the prerequisite Doppler measurements are available.  The panel
listens to CalculationsSnapshot updates and displays only the chains
whose inputs are all present — no user action required beyond measuring.

Clinical chains:

    LVOTd + LVOT VTI -> LVOT Area -> SV -> SVi -> CO -> CI
    LVOT VTI + AV VTI  -> AVA (VTI) -> AVAi -> DVI
    MR VTI + LVOT VTI  -> MR RVol -> MR RF
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.calculators.models import CalculationsSnapshot
from echo_personal_tool.presentation.theme.palettes import OVERLAY_LABEL


def _fmt(value: float | None, unit: str, decimals: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f} {unit}"


class _DerivativeRow(QWidget):
    """One chain step: label + value + unit."""

    def __init__(self, label_key: str, unit: str, decimals: int = 1, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._decimals = decimals
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._label = QLabel(tr(label_key))
        self._label.setWordWrap(True)
        self._label.setStyleSheet(f"color: {OVERLAY_LABEL}; font-size: 11px;")
        self._value = QLabel("—")
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._value.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self._label)
        layout.addWidget(self._value)

    def set_value(self, value: float | None, unit: str, decimals: int | None = None) -> None:
        self._value.setText(_fmt(value, unit, self._decimals if decimals is None else decimals))
        self._value.setToolTip(unit)


class DopplerDerivativePanel(QWidget):
    """Compact panel showing automatically computed Doppler derivative chains."""

    #: Emitted when the set of computable chains changes.
    chains_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dopplerDerivativePanel")
        self.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # ── Stroke volume chain ──────────────────────────────────────
        self._lvot_area = _DerivativeRow("calc.output.lvot_area", "cm²", 2)
        self._sv = _DerivativeRow("calc.output.sv", "mL", 1)
        self._svi = _DerivativeRow("calc.output.svi", "mL/m²", 1)
        self._co = _DerivativeRow("calc.output.co", "L/min", 2)
        self._ci = _DerivativeRow("calc.output.ci", "L/min/m²", 2)

        sv_group = QFrame()
        sv_group.setObjectName("dopplerDerivativeSvGroup")
        sv_layout = QGridLayout(sv_group)
        sv_layout.setContentsMargins(4, 4, 4, 4)
        sv_layout.setSpacing(4)
        sv_layout.addWidget(self._lvot_area, 0, 0)
        sv_layout.addWidget(QLabel("→"), 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        sv_layout.addWidget(self._sv, 0, 2)
        sv_layout.addWidget(self._svi, 1, 2)
        sv_layout.addWidget(self._co, 2, 2)
        sv_layout.addWidget(self._ci, 3, 2)
        sv_layout.setColumnStretch(2, 1)
        layout.addWidget(sv_group)

        # ── Aortic valve chain ───────────────────────────────────────
        self._ava = _DerivativeRow("calc.output.ava_vti", "cm²", 2)
        self._avai = _DerivativeRow("calc.output.avai", "cm²/m²", 2)
        self._dvi = _DerivativeRow("calc.output.dvi_vti", "", 2)

        ava_group = QFrame()
        ava_group.setObjectName("dopplerDerivativeAvaGroup")
        ava_layout = QGridLayout(ava_group)
        ava_layout.setContentsMargins(4, 4, 4, 4)
        ava_layout.setSpacing(4)
        ava_layout.addWidget(self._ava, 0, 0)
        ava_layout.addWidget(QLabel("→"), 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        ava_layout.addWidget(self._avai, 0, 2)
        ava_layout.addWidget(self._dvi, 1, 2)
        ava_layout.setColumnStretch(2, 1)
        layout.addWidget(ava_group)

        # ── Mitral regurgitation chain ───────────────────────────────
        self._rvol_mr = _DerivativeRow("calc.output.rvol_mr", "mL", 1)
        self._rf_mr = _DerivativeRow("calc.output.rf_mr", "%", 0)

        mr_group = QFrame()
        mr_group.setObjectName("dopplerDerivativeMrGroup")
        mr_layout = QGridLayout(mr_group)
        mr_layout.setContentsMargins(4, 4, 4, 4)
        mr_layout.setSpacing(4)
        mr_layout.addWidget(self._rvol_mr, 0, 0)
        mr_layout.addWidget(QLabel("→"), 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        mr_layout.addWidget(self._rf_mr, 0, 2)
        mr_layout.setColumnStretch(2, 1)
        layout.addWidget(mr_group)

        layout.addStretch(1)

        self._groups: list[QFrame] = [sv_group, ava_group, mr_group]
        self._rows: list[_DerivativeRow] = [
            self._lvot_area,
            self._sv,
            self._svi,
            self._co,
            self._ci,
            self._ava,
            self._avai,
            self._dvi,
            self._rvol_mr,
            self._rf_mr,
        ]

    def set_calculations(self, snapshot: CalculationsSnapshot | None) -> None:
        """Update all derivative rows from the latest calculations snapshot."""
        if snapshot is None:
            self._set_visible(False)
            return

        results = {r.calculator_id: r for r in snapshot.results}

        # ── Stroke volume chain ──────────────────────────────────────
        sv_result = results.get("stroke_volume")
        sv_outputs = {o.id: o for o in sv_result.outputs} if sv_result else {}

        self._set_row(self._lvot_area, sv_outputs.get("lvot_area"), 2)
        self._set_row(self._sv, sv_outputs.get("sv"), 1)
        self._set_row(self._svi, sv_outputs.get("svi"), 1)
        self._set_row(self._co, sv_outputs.get("co"), 2)
        self._set_row(self._ci, sv_outputs.get("ci"), 2)

        # ── Aortic valve chain ───────────────────────────────────────
        ava_result = results.get("aortic_valve_area")
        ava_outputs = {o.id: o for o in ava_result.outputs} if ava_result else {}

        self._set_row(self._ava, ava_outputs.get("ava_vti"), 2)
        self._set_row(self._avai, ava_outputs.get("avai"), 2)
        self._set_row(self._dvi, ava_outputs.get("dvi_vti"), 2)

        # ── Mitral regurgitation chain ───────────────────────────────
        pisa_result = results.get("pisa_mr")
        pisa_outputs = {o.id: o for o in pisa_result.outputs} if pisa_result else {}

        self._set_row(self._rvol_mr, pisa_outputs.get("rvol_mr"), 1)
        self._set_row(self._rf_mr, pisa_outputs.get("rf_mr"), 0)

        # Show panel only if at least one chain has a computed value
        has_any = any(
            r is not None and r.value is not None
            for r in [
                sv_outputs.get("lvot_area"),
                sv_outputs.get("sv"),
                ava_outputs.get("ava_vti"),
                pisa_outputs.get("rvol_mr"),
            ]
        )
        self._set_visible(has_any)

    def _set_row(self, row: _DerivativeRow, output, decimals: int) -> None:
        if output is not None and output.value is not None:
            row.set_value(output.value, output.unit, decimals)
            row.setVisible(True)
        else:
            row.setVisible(False)

    def _set_visible(self, visible: bool) -> None:
        if self.isVisible() != visible:
            self.setVisible(visible)
            self.chains_changed.emit(visible)
