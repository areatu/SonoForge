"""Growth charts (plan А.12, issue 650) — percentile curves + the patient.

The classic paediatric growth chart: percentile curves of one parameter
against body size (BSA, children) or gestational age (fetal), with the
patient's measurement marked on the chart.  Curves come straight from the
norm table (:mod:`pediatric_norms`) — including its honesty rules: nothing
is drawn outside the anchored range, and the table's source string is shown
so a seed table cannot pass for a verified reference.

The dialog is fed from the report document: the Z-score rows carry the
computed Z (``+0.8 (P79)``) and the patient header carries the BSA or the
gestational age, so the widget needs no snapshot plumbing.
"""

from __future__ import annotations

import re

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.measurement_catalog import MEASUREMENTS
from echo_personal_tool.domain.services.pediatric_norms import PediatricNorms, cached_norms
from echo_personal_tool.domain.services.report_document import ReportDocument
from echo_personal_tool.domain.services.report_zscore import CHART_PERCENTILES
from echo_personal_tool.domain.services.zscore import BsaBandModel, percentile_curve, percentile_to_z, z_to_percentile
from echo_personal_tool.domain.translation import get_language

_Z_RE = re.compile(r"^[+-]?\d+\.?\d*")

#: Chart colours (the ui layer keeps its own small palette, like
#: ``strain_curves_view``): the percentile band is one calm blue, the median
#: and the patient's point carry the accent red.  The chart sits on the
#: always-light A4 paper, so these do not follow the theme.
_CURVE_COLOR = "#1f77b4"
_MEDIAN_COLOR = "#d62728"


class _ChartEntry:
    """One chartable parameter: the model, the computed Z and the axis input."""

    __slots__ = ("axis", "model", "parameter_id", "source", "title", "z")

    def __init__(self, title: str, parameter_id: str, model: BsaBandModel, z: float, axis: float, source: str) -> None:
        self.title = title
        self.parameter_id = parameter_id
        self.model = model
        self.z = z
        self.axis = axis
        self.source = source


def _parameter_title(measurement_id: str) -> str:
    spec = MEASUREMENTS.get(measurement_id)
    if spec is None:
        return measurement_id
    return spec.label(get_language() or "ru").short


def _chart_entries(document: ReportDocument, norms: PediatricNorms) -> list[_ChartEntry]:
    """Every parameter of the document that has a Z row and a usable axis."""
    axis: float | None = None
    if document.patient.gestational_weeks is not None:
        axis = document.patient.gestational_weeks
    elif document.patient.bsa_m2 and document.patient.bsa_m2 > 0:
        axis = document.patient.bsa_m2
    entries: list[_ChartEntry] = []
    if axis is None:
        return entries
    for group in document.groups:
        for value in group.values:
            model = norms.model_for(value.parameter_id)
            if not isinstance(model, BsaBandModel):
                continue
            match = _Z_RE.match(value.value)
            if match is None:
                continue
            entries.append(
                _ChartEntry(
                    title=_parameter_title(value.parameter_id),
                    parameter_id=value.parameter_id,
                    model=model,
                    z=float(match.group(0)),
                    axis=axis,
                    source=value.norm,
                )
            )
    return entries


class GrowthChartWidget(QWidget):
    """Percentile curves of one parameter plus the patient's point."""

    def __init__(self, entries: list[_ChartEntry], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries = entries
        layout = QVBoxLayout(self)
        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel(tr("growth_chart.pick_parameter")))
        self._picker = QComboBox()
        for index, entry in enumerate(entries):
            self._picker.addItem(entry.title, index)
        self._picker.currentIndexChanged.connect(self._draw_current)
        picker_row.addWidget(self._picker, 1)
        layout.addLayout(picker_row)
        self._source_label = QLabel()
        self._source_label.setWordWrap(True)
        layout.addWidget(self._source_label)
        self._plot = pg.PlotWidget(background="w")
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        layout.addWidget(self._plot, 1)
        if entries:
            self._draw_current()

    def _draw_current(self) -> None:
        index = self._picker.currentData()
        if index is None:
            return
        entry = self._entries[index]
        self._source_label.setText(f"{tr('growth_chart.norm_source')}: {entry.source}")
        plot = self._plot
        plot.clear()
        plot.setLabel("bottom", tr("growth_chart.axis_bsa"))
        plot.setLabel("left", entry.title)
        for percentile in CHART_PERCENTILES:
            points = percentile_curve(entry.model, percentile_to_z(percentile))
            if not points:
                continue
            median = percentile == 50.0
            plot.plot(
                [point[0] for point in points],
                [point[1] for point in points],
                pen=pg.mkPen(
                    _MEDIAN_COLOR if median else _CURVE_COLOR,
                    width=2 if median else 1,
                    style=Qt.PenStyle.SolidLine if median else Qt.PenStyle.DashLine,
                ),
                name=f"P{percentile:g}",
            )
        raw = entry.model.value_at_z(entry.z, entry.axis)
        if raw is not None:
            plot.addItem(pg.ScatterPlotItem([entry.axis], [raw], size=12, brush=pg.mkBrush(_MEDIAN_COLOR)))
            tag = pg.TextItem(
                f"Z {entry.z:+.2f} ({tr('growth_chart.p_tag')}{round(z_to_percentile(entry.z))})",
                color=_MEDIAN_COLOR,
            )
            tag.setPos(entry.axis, raw)
            plot.addItem(tag)


def show_growth_chart_dialog(document: ReportDocument, parent: QWidget | None = None) -> bool:
    """Open the growth charts of a document; ``True`` when there was anything to show.

    A document without Z-score rows (adult profile, no BSA, no gestational
    age) opens nothing — a chart with an invented axis would be worse than
    no chart.
    """
    entries = _chart_entries(document, cached_norms())
    if not entries:
        return False
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr("growth_chart.dialog_title"))
    layout = QVBoxLayout(dialog)
    axis_text = (
        tr("growth_chart.axis_ga") if document.patient.gestational_weeks is not None else tr("growth_chart.axis_bsa")
    )
    layout.addWidget(QLabel(f"{tr('growth_chart.axis_input')}: {axis_text}"))
    layout.addWidget(GrowthChartWidget(entries, dialog))
    dialog.resize(760, 560)
    dialog.exec()
    return True
