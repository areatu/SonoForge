"""Non-modal popup dialog for STE (speckle tracking) results."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel
from echo_personal_tool.presentation.strain_curve_widget import StrainCurveWidget


class SteResultsDialog(QDialog):
    """Floating window showing strain curves and segment quality table."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.ste_results.title"))
        self.setFixedSize(950, 520)
        self.setWindowFlags(Qt.WindowType.Window)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Warning label for quality gate
        self._warning_label = QLabel()
        self._warning_label.setStyleSheet(
            "QLabel { color: #ff9800; background-color: #3d3000; "
            "padding: 4px 8px; border-radius: 4px; font-weight: bold; }"
        )
        self._warning_label.hide()
        main_layout.addWidget(self._warning_label)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)

        self._strain_curve = StrainCurveWidget()
        self._segment_quality = SegmentQualityPanel()

        content_layout.addWidget(self._strain_curve, stretch=2)
        content_layout.addWidget(self._segment_quality, stretch=1)

        main_layout.addLayout(content_layout)

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
        kernels_accepted: int = 0,
        kernels_rejected: int = 0,
        kernels_total: int = 0,
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

        # Update warning label
        if kernels_total > 0 and kernels_rejected > 0:
            accepted_pct = (kernels_accepted / kernels_total) * 100.0
            self._warning_label.setText(
                f"Quality Gate: {kernels_accepted}/{kernels_total} kernels accepted ({accepted_pct:.0f}%) "
                f"— {kernels_rejected} rejected (NCC < threshold)"
            )
            self._warning_label.show()
        else:
            self._warning_label.hide()

        if not self.isVisible():
            self.show()

    def clear(self) -> None:
        self._strain_curve.clear()
        self._segment_quality.update_results({}, {})
