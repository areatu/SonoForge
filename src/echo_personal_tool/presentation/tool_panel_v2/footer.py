"""Footer of the measurement panel 2.0: patient metrics and the report button.

Spec TP §4.2: «Пациент: рост · вес · ППТ» editable in place, and
«Отчёт · N измерений».  UD-12 of the UI redesign proposes moving height and
weight to the patient row; until that is implemented the footer keeps the
fields that used to live in the old Measures tab, so switching the
experimental panel does not remove a function.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.scroll_policy import protect_spinbox
from echo_personal_tool.presentation.theme.token_restyle import TokenRestyleMixin
from echo_personal_tool.presentation.ui_animations import HoverButtonMixin


class PanelFooter(TokenRestyleMixin, QWidget):
    """Height / weight / BSA and the report entry point."""

    metrics_changed = Signal(object, object)
    auto_play_changed = Signal(bool)
    report_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolPanelFooter")
        from echo_personal_tool.infrastructure.i18n import tr

        self._bsa_basis: object | None = None

        metrics_row = QHBoxLayout()
        metrics_row.setContentsMargins(0, 0, 0, 0)
        # A label sits 4 px from its field, the two groups are 16 px apart and
        # the derived BSA closes the strip: the row used to be one long run of
        # «Рост 0 Вес 0 ППТ …» with no grouping at all.
        metrics_row.setSpacing(4)
        self._height_label = QLabel(tr("tools.height"))
        self._height_spin = QSpinBox()
        self._height_spin.setRange(0, 250)
        self._height_spin.setSpecialValueText("")
        self._height_spin.setKeyboardTracking(False)
        self._height_spin.valueChanged.connect(self._emit_metrics)
        self._weight_label = QLabel(tr("tools.weight"))
        self._weight_spin = QSpinBox()
        self._weight_spin.setRange(0, 300)
        self._weight_spin.setSpecialValueText("")
        self._weight_spin.setKeyboardTracking(False)
        self._weight_spin.valueChanged.connect(self._emit_metrics)
        metrics_row.addWidget(self._height_label)
        metrics_row.addWidget(self._height_spin)
        metrics_row.addSpacing(12)
        metrics_row.addWidget(self._weight_label)
        metrics_row.addWidget(self._weight_spin)
        metrics_row.addSpacing(12)

        self._bsa_label = QLabel()
        self._bsa_label.setObjectName("patientBsaLabel")
        self._bsa_label.setWordWrap(True)

        self._auto_play = QCheckBox(tr("preferences.auto_play"))
        self._auto_play.toggled.connect(self.auto_play_changed.emit)

        self._report_button = QPushButton(tr("tool_panel.report"), self)
        self._report_button.setObjectName("panelReportButton")
        self._report_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._report_count: int | None = None
        self._report_button.clicked.connect(self.report_requested.emit)
        HoverButtonMixin.install(self._report_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(4)
        self.metrics_widget = QWidget()
        self.metrics_widget.setObjectName("patientMetricsToolbar")
        toolbar_layout = QHBoxLayout(self.metrics_widget)
        toolbar_layout.setContentsMargins(8, 2, 8, 2)
        toolbar_layout.addLayout(metrics_row)
        toolbar_layout.addWidget(self._bsa_label)
        toolbar_layout.addStretch(1)
        self._bsa_label.setWordWrap(False)
        layout.addWidget(self.metrics_widget)
        layout.addWidget(self._auto_play)
        # Report has one entry point in the main header.
        self._report_button.hide()
        for spin in (self._height_spin, self._weight_spin):
            protect_spinbox(spin)
            spin.setFixedWidth(max(76, spin.fontMetrics().horizontalAdvance("0000") + 36))
            spin.setObjectName("patientMetricEditor")
        self._apply_style()

    def _apply_style(self) -> None:
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"""
            #toolPanelFooter {{
                background: {tokens["surface.1"]};
                border-top: 1px solid {tokens["line.1"]};
            }}
            #toolPanelFooter QLabel {{
                color: {tokens["text.2"]};
            }}
            #toolPanelFooter QCheckBox {{
                color: {tokens["text.2"]};
            }}
            #panelReportButton {{
                min-height: 30px;
                border: 1px solid {tokens["line.2"]};
                border-radius: 4px;
                background: {tokens["surface.2"]};
                color: {tokens["text.1"]};
            }}
            #panelReportButton:hover {{
                background: {tokens["surface.3"]};
            }}
            """
        )

    # ── State ──────────────────────────────────────────────────────

    def set_patient_metrics(self, height_cm: float | None, weight_kg: float | None, bsa_basis: object = None) -> None:
        """Show the study's height, weight and the one BSA it resolves to."""
        self._height_spin.blockSignals(True)
        self._weight_spin.blockSignals(True)
        self._height_spin.setValue(int(round(height_cm)) if height_cm else 0)
        self._weight_spin.setValue(int(round(weight_kg)) if weight_kg else 0)
        self._height_spin.blockSignals(False)
        self._weight_spin.blockSignals(False)
        self._update_bsa(height_cm, weight_kg, bsa_basis)

    def set_auto_play(self, enabled: bool) -> None:
        self._auto_play.blockSignals(True)
        self._auto_play.setChecked(bool(enabled))
        self._auto_play.blockSignals(False)

    def auto_play(self) -> bool:
        return self._auto_play.isChecked()

    def set_measurement_count(self, count: int | None) -> None:
        """«Отчёт · N измерений»; ``None`` keeps the plain report caption."""
        self._report_count = count
        self._render_report_text()

    def _emit_metrics(self) -> None:
        height = self._height_spin.value()
        weight = self._weight_spin.value()
        self._update_bsa(float(height) if height > 0 else None, float(weight) if weight > 0 else None)
        self.metrics_changed.emit(
            float(height) if height > 0 else None,
            float(weight) if weight > 0 else None,
        )

    def _update_bsa(self, height_cm: float | None, weight_kg: float | None, bsa_basis: object = None) -> None:
        from echo_personal_tool.domain.calculations.body_surface import resolve_bsa_basis

        self._bsa_basis = (
            bsa_basis if bsa_basis is not None else resolve_bsa_basis(height_cm=height_cm, weight_kg=weight_kg)
        )
        self._render_bsa()

    def _render_bsa(self) -> None:
        from echo_personal_tool.domain.calculations.body_surface import resolve_bsa_basis
        from echo_personal_tool.domain.services.bsa_provenance import bsa_source_label
        from echo_personal_tool.infrastructure.i18n import tr

        basis = self._bsa_basis or resolve_bsa_basis()
        if basis.value is None:
            self._bsa_label.setText(tr("panel.bsa_missing"))
            self._bsa_label.setToolTip("")
            return
        # The patient line carries the figure only: «ППТ 1,77 м²». The formula
        # (Du Bois, Mosteller…) is provenance, not a headline — spelled out it
        # was the longest caption of the row and pushed the study actions away
        # from the metrics (2026-10-27 list, item 5a). It stays one hover away.
        self._bsa_label.setText(f"{tr('panel.bsa')} {basis.value:.2f} m²")
        self._bsa_label.setToolTip(bsa_source_label(basis))

    def reload_text(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        self._height_label.setText(tr("tools.height"))
        self._weight_label.setText(tr("tools.weight"))
        self._auto_play.setText(tr("preferences.auto_play"))
        self._render_report_text()
        self._render_bsa()

    def _render_report_text(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr, tr_plural

        if self._report_count is None or self._report_count <= 0:
            self._report_button.setText(tr("tool_panel.report"))
            return
        self._report_button.setText(tr_plural("panel.report_count", self._report_count))
