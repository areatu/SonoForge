"""Dedicated LA/RV strain results window (plan А.6/А.7, user feedback).

The arc strains used to surface only as rows and curve overlays inside the
combined strain window — a physician measuring only the LA or the RV had to
read past the LV machinery. This window shows the arc results on their own:
the LA reservoir/conduit/booster triple, the RV free-wall GLS, the tracking
qualities and the two curves, and it opens by itself when an analysis
produced arc evidence (the combined strain window still shows its overlays).

Honesty carries over unchanged: a phase the run could not measure shows
«--» / a gap note — never a fabricated number.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.speckle import StrainResult
from echo_personal_tool.ui.strain_curves_view import _OK_COLOR, _PLOT_BACKGROUND, _TITLE_COLOR, _VALUE_COLOR

_ED_ES_SOURCE_LABELS = {
    "manual": "manual",
    "manual_ed+auto": "manual ED + auto ES",
    "manual_es+auto": "manual ES + auto ED",
    "ecg": "ECG",
    "simpson": "Simpson",
    "image": "image",
    "image_fallback": "image",
}


class ArcStrainWindow(QWidget):
    """The LA/RV arc-strain results of the last analysis, on their own."""

    closed = Signal()

    def __init__(self) -> None:
        super().__init__(None)  # top-level: raised above the maximized main window
        self.setObjectName("arcStrainWindow")
        self.setWindowTitle(tr("arc_strain.window_title"))
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        self._meta_label = QLabel()
        self._meta_label.setWordWrap(True)
        self._meta_label.setStyleSheet(f"color: {_TITLE_COLOR}; font-size: 12px; font-weight: 600;")
        layout.addWidget(self._meta_label)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self._values: dict[str, QLabel] = {}
        for key in ("la_lasr", "la_lascd", "la_lasct", "rv_gls"):
            label = QLabel("--")
            label.setStyleSheet(f"color: {_VALUE_COLOR}; font-weight: bold;")
            label.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._values[key] = label
            form.addRow(tr(f"strain.{key}_row"), label)
        layout.addLayout(form)
        self._absent_label = QLabel()
        self._absent_label.setWordWrap(True)
        layout.addWidget(self._absent_label)
        self._plot = pg.PlotWidget(background=_PLOT_BACKGROUND)
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.addLegend(offset=(8, 8))
        self._plot.setLabel("bottom", tr("strain.unit_ms"))
        self._plot.setLabel("left", "%")
        layout.addWidget(self._plot, 1)
        self._la_item: pg.PlotDataItem | None = None
        self._rv_item: pg.PlotDataItem | None = None

    # ── Results ─────────────────────────────────────────────────────────

    def show_result(self, result: StrainResult) -> None:
        """Show one analysis result; the window opens/raises itself."""
        self._update_meta(result)
        self._update_la(result)
        self._update_rv(result)
        self._update_absent_note(result)
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def _update_meta(self, result: StrainResult) -> None:
        source = _ED_ES_SOURCE_LABELS.get(result.ed_es_source, result.ed_es_source)
        parts = [f"ED/ES {result.ed_index}/{result.es_index} ({source})"]
        quality = result.la_tracking_quality
        if quality is not None:
            parts.append(f"{tr('arc_strain.la_quality')}: {quality * 100.0:.0f}%")
        quality = result.rv_tracking_quality
        if quality is not None:
            parts.append(f"{tr('arc_strain.rv_quality')}: {quality * 100.0:.0f}%")
        self._meta_label.setText("   |   ".join(parts))

    def _update_la(self, result: StrainResult) -> None:
        la = result.la_strain
        values = {
            "la_lasr": None if la is None else la.reservoir_pct,
            "la_lascd": None if la is None else la.conduit_pct,
            "la_lasct": None if la is None else la.booster_pct,
        }
        for key, value in values.items():
            self._values[key].setText("--" if value is None else f"{value:.1f}%")
        self._la_item = self._set_curve(
            self._la_item, result.la_strain_curve, result.frame_time_ms, _VALUE_COLOR, "strain.la_curve_label"
        )

    def _update_rv(self, result: StrainResult) -> None:
        rv = result.rv_strain
        self._values["rv_gls"].setText("--" if rv is None else f"{rv.gls_pct:.1f}%")
        self._rv_item = self._set_curve(
            self._rv_item, result.rv_strain_curve, result.frame_time_ms, _OK_COLOR, "strain.rv_curve_label"
        )

    def _set_curve(
        self,
        item: pg.PlotDataItem | None,
        curve: np.ndarray | None,
        frame_time_ms: float,
        colour: str,
        label_key: str,
    ) -> pg.PlotDataItem | None:
        """Plot one arc curve over the cycle, or drop it when absent."""
        usable = curve is not None and len(curve) >= 2 and bool(np.isfinite(np.asarray(curve)).any())
        if not usable:
            if item is not None:
                self._plot.removeItem(item)
            return None
        data = np.asarray(curve, dtype=np.float64)
        x = np.arange(len(data)) * float(frame_time_ms)
        pen = pg.mkPen(colour, width=2, style=Qt.PenStyle.DashLine)
        if item is None:
            # ``plot()`` creates the item AND adds it — a second ``addItem``
            # would only warn.
            item = self._plot.plot(x, data, pen=pen, name=tr(label_key))
        else:
            item.setData(x, data)
        return item

    def _update_absent_note(self, result: StrainResult) -> None:
        notes: list[str] = []
        if result.la_strain is None:
            notes.append(tr("arc_strain.la_absent"))
        if result.rv_strain is None:
            notes.append(tr("arc_strain.rv_absent"))
        self._absent_label.setText("\n".join(notes))

    # ── Window lifecycle ────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        self.closed.emit()
        super().closeEvent(event)
