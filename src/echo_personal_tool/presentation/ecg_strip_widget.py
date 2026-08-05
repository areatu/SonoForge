"""ECG strip widget with R-peak markers and active cycle highlighting."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from echo_personal_tool.domain.models.ecg import EcgWaveform
from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle
from echo_personal_tool.domain.services.ecg_rpeak_detector import detect_r_peaks_from_waveform


class EcgStripWidget(QWidget):
    """Thin ECG strip with R-peak markers and optional active cycle highlight."""

    cycle_clicked = Signal(CardiacCycle)  # emitted when user clicks a cycle

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plot = pg.PlotWidget()
        self._plot.setBackground("black")
        self._plot.hideAxis("left")
        self._plot.hideAxis("bottom")
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.setMenuEnabled(False)
        self._plot.setMaximumHeight(60)
        self._plot.setMinimumHeight(40)

        self._signal_item: pg.PlotDataItem | None = None
        self._rpeak_items: list[pg.InfiniteLine] = []
        self._cycle_highlight: pg.LinearRegionItem | None = None
        self._cycles: list[CardiacCycle] = []
        self._r_peaks: np.ndarray | None = None
        self._r_peak_times: np.ndarray | None = None
        self._ecg_duration_ms: float = 0.0

        # Cap the strip's own height so the parent layout does not stretch it
        # (the inner plot's sizeHint is ~480px even with a max height set).
        self.setMaximumHeight(60)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._plot)

        # Connect click on the plot to detect cycle clicks
        self._plot.scene().sigMouseClicked.connect(self._on_mouse_click)

    def set_ecg(self, ecg: EcgWaveform | None) -> None:
        """Load and display ECG waveform with detected R-peaks."""
        self._clear()

        if ecg is None:
            return

        signal = self._extract_primary_lead(ecg)
        if signal is None:
            return

        voltage, fs = signal
        self._ecg_duration_ms = (voltage.size / fs) * 1000.0
        time_ms = np.arange(voltage.size) / fs * 1000.0

        # Draw waveform
        pen = pg.mkPen("#00ff88", width=1)
        self._signal_item = pg.PlotDataItem(time_ms, voltage, pen=pen)
        self._signal_item.setZValue(10)
        self._plot.addItem(self._signal_item)

        # Detect R-peaks
        r_peak_result = detect_r_peaks_from_waveform(ecg)
        if r_peak_result is not None and len(r_peak_result.r_peak_indices) > 0:
            self._r_peaks = r_peak_result.r_peak_indices
            self._r_peak_times = r_peak_result.r_peak_times_ms
            self._draw_r_peak_markers(r_peak_result.r_peak_times_ms)

        self._plot.setXRange(0, self._ecg_duration_ms, padding=0)
        self._plot.setYRange(float(np.min(voltage)) - 0.1, float(np.max(voltage)) + 0.1, padding=0)

    def set_cardiac_cycles(self, cycles: Sequence[CardiacCycle]) -> None:
        """Set the cardiac cycles (from CardiacCycleService) for cycle highlighting."""
        self._cycles = list(cycles)
        self._update_cycle_highlight()

    def highlight_cycle(self, cycle_index: int | None) -> None:
        """Highlight a specific cycle by index, or clear highlight if None."""
        if self._cycle_highlight is not None:
            self._plot.removeItem(self._cycle_highlight)
            self._cycle_highlight = None

        if cycle_index is not None and 0 <= cycle_index < len(self._cycles):
            cycle = self._cycles[cycle_index]
            self._cycle_highlight = pg.LinearRegionItem(
                [cycle.start_ms, cycle.end_ms],
                brush=pg.mkBrush(pg.mkColor(0, 255, 136, 100)),
                pen=pg.mkPen("#00ff88", width=1, style=Qt.PenStyle.DashLine),
                movable=False,
            )
            self._cycle_highlight.setZValue(5)
            self._plot.addItem(self._cycle_highlight)

    def clear(self) -> None:
        """Clear all displayed data."""
        self._clear()
        self._cycles = []
        self._r_peaks = None
        self._r_peak_times = None
        self._ecg_duration_ms = 0.0

    def _clear(self) -> None:
        if self._signal_item is not None:
            self._plot.removeItem(self._signal_item)
            self._signal_item = None
        for item in self._rpeak_items:
            self._plot.removeItem(item)
        self._rpeak_items.clear()
        if self._cycle_highlight is not None:
            self._plot.removeItem(self._cycle_highlight)
            self._cycle_highlight = None

    def _extract_primary_lead(self, ecg: EcgWaveform) -> tuple[np.ndarray, float] | None:
        """Extract primary lead voltage and sampling frequency."""
        lead = ecg.primary_lead
        if lead is None or lead.sampling_frequency <= 0:
            return None
        try:
            lead_index = ecg.leads.index(lead)
        except ValueError:
            lead_index = 0
        voltage = ecg.as_voltage_mv(lead_index)
        if voltage.ndim != 1 or voltage.size < 10:
            return None
        return voltage, float(lead.sampling_frequency)

    def _draw_r_peak_markers(self, r_peak_times: np.ndarray) -> None:
        """Draw vertical lines at R-peak positions."""
        for t in r_peak_times:
            line = pg.InfiniteLine(
                pos=t,
                angle=90,
                pen=pg.mkPen("#ff6f00", width=1, style=Qt.PenStyle.DashLine),
            )
            line.setZValue(15)
            self._plot.addItem(line)
            self._rpeak_items.append(line)

    def _update_cycle_highlight(self) -> None:
        """No default highlight; use highlight_cycle() to show one."""
        pass

    def _on_mouse_click(self, event) -> None:
        """Handle mouse click on the ECG strip to emit cycle_clicked."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._signal_item is None:
            return
        vb = self._plot.getViewBox()
        scene_pos = event.scenePos()
        if not self._signal_item.sceneBoundingRect().contains(scene_pos):
            return
        mouse_point = vb.mapSceneToView(scene_pos)
        t = float(mouse_point.x())
        # Find which cycle contains this time
        for i, cycle in enumerate(self._cycles):
            if cycle.start_ms <= t <= cycle.end_ms:
                self.cycle_clicked.emit(cycle)
                return