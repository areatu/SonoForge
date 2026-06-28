"""Non-modal popup dialog for STE (speckle tracking) results."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QWidget

from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel
from echo_personal_tool.presentation.strain_curve_widget import StrainCurveWidget


class SteResultsDialog(QDialog):
    """Floating window showing strain curves and segment quality table."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("STE Results")
        self.setFixedSize(950, 500)
        self.setWindowFlags(Qt.WindowType.Window)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._strain_curve = StrainCurveWidget()
        self._segment_quality = SegmentQualityPanel()

        layout.addWidget(self._strain_curve, stretch=2)
        layout.addWidget(self._segment_quality, stretch=1)

    def update_results(
        self,
        longitudinal: np.ndarray,
        radial: np.ndarray,
        segment_strain: dict[int, float],
        segment_quality: dict[int, float],
        *,
        gls: float = 0.0,
        ed_index: int = 0,
        es_index: int = 0,
        window_start: int | None = None,
        window_end: int | None = None,
    ) -> None:
        self._strain_curve.set_strain_data(
            longitudinal,
            radial,
            ed_index=ed_index,
            es_index=es_index,
            window_start=window_start,
            window_end=window_end,
        )
        self._strain_curve.set_gls_value(gls)
        self._segment_quality.update_results(segment_strain, segment_quality)
        if not self.isVisible():
            self.show()

    def clear(self) -> None:
        self._strain_curve.clear()
        self._segment_quality.update_results({}, {})
