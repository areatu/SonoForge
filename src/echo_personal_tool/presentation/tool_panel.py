"""Right-side tool panel with Measures / Controls tabs."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.presentation.measurement_action import MeasurementAction
from echo_personal_tool.presentation.dicom_tag_inspector_widget import DicomTagInspectorWidget
from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider
from echo_personal_tool.presentation.measures_menu import MeasuresMenuWidget


class _PatientMetricsRow(QWidget):
    """Height / weight inputs (0 = empty, whole cm/kg)."""

    _LABEL_STYLE = "font-size: 14px; font-weight: 600;"

    metrics_changed = Signal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        height_label = QLabel("Рост")
        height_label.setStyleSheet(self._LABEL_STYLE)
        layout.addWidget(height_label)
        self._height_spin = QSpinBox()
        self._height_spin.setRange(0, 250)
        self._height_spin.setSpecialValueText("")
        self._height_spin.valueChanged.connect(self._emit_metrics)
        layout.addWidget(self._height_spin)
        weight_label = QLabel("Вес")
        weight_label.setStyleSheet(self._LABEL_STYLE)
        layout.addWidget(weight_label)
        self._weight_spin = QSpinBox()
        self._weight_spin.setRange(0, 300)
        self._weight_spin.setSpecialValueText("")
        self._weight_spin.valueChanged.connect(self._emit_metrics)
        layout.addWidget(self._weight_spin)
        layout.addStretch(1)

    def _emit_metrics(self) -> None:
        height = self._height_spin.value()
        weight = self._weight_spin.value()
        self.metrics_changed.emit(
            float(height) if height > 0 else None,
            float(weight) if weight > 0 else None,
        )

    def set_metrics(self, height_cm: float | None, weight_kg: float | None) -> None:
        self._height_spin.blockSignals(True)
        self._weight_spin.blockSignals(True)
        self._height_spin.setValue(int(round(height_cm)) if height_cm else 0)
        self._weight_spin.setValue(int(round(weight_kg)) if weight_kg else 0)
        self._height_spin.blockSignals(False)
        self._weight_spin.blockSignals(False)


class ControlsTab(QWidget):
    """Window / Level / DR sliders (GE Controls)."""

    magnetic_snap_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.window_slider = TopLabeledSlider("Window", minimum=1, maximum=400, value=100)
        self.level_slider = TopLabeledSlider("Level", minimum=0, maximum=100, value=50)
        self.dr_slider = TopLabeledSlider("DR", minimum=0, maximum=100, value=50)
        self.dr_slider.slider().setToolTip(
            "Dynamic range: center = full range; left = clip dark (typical for US)"
        )
        self._magnetic_snap_check = QCheckBox("Магнит к стенке")
        self._magnetic_snap_check.setChecked(True)
        self._magnetic_snap_check.setToolTip(
            "При отпускании узла — мягкое прилипание к границе по градиенту"
        )
        self._magnetic_snap_check.toggled.connect(self.magnetic_snap_changed.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(10)
        layout.addWidget(self.window_slider)
        layout.addWidget(self.level_slider)
        layout.addWidget(self.dr_slider)
        layout.addWidget(self._magnetic_snap_check)
        layout.addStretch(1)


class MeasureTab(QWidget):
    """Measurement tools only (results shown on-image overlay)."""

    action_requested = Signal(object, str, str, str)
    patient_metrics_changed = Signal(object, object)
    results_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._menu = MeasuresMenuWidget()
        self._menu.action_requested.connect(self.action_requested.emit)
        self._patient_metrics = _PatientMetricsRow()
        self._patient_metrics.metrics_changed.connect(self.patient_metrics_changed.emit)

        self._results_button = QPushButton("Результаты")
        self._results_button.setMinimumHeight(32)
        self._results_button.clicked.connect(self.results_requested.emit)
        results_wrap = QWidget()
        results_layout = QHBoxLayout(results_wrap)
        results_layout.setContentsMargins(8, 0, 8, 8)
        results_layout.addWidget(self._results_button)

        self._metrics_results_gap = QWidget()
        self._metrics_results_gap.setFixedHeight(0)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self._menu, stretch=1)
        self._layout.addWidget(self._patient_metrics, stretch=0)
        self._layout.addWidget(self._metrics_results_gap, stretch=0)
        self._layout.addWidget(results_wrap, stretch=0)

    def _sync_patient_metrics_lift(self) -> None:
        window = self.window()
        if window is None or window.height() <= 0:
            return
        self._metrics_results_gap.setFixedHeight(int(window.height() * 0.10))

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._sync_patient_metrics_lift()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_patient_metrics_lift()

    def set_patient_metrics(self, height_cm: float | None, weight_kg: float | None) -> None:
        self._patient_metrics.set_metrics(height_cm, weight_kg)

    def set_doppler_tool_availability(self, *, time_ok: bool) -> None:
        self._menu.set_doppler_tool_availability(time_ok=time_ok)

    def highlight_action(
        self,
        action: MeasurementAction,
        *,
        view: str = "A4C",
        phase: str = "ED",
    ) -> None:
        self._menu.highlight_action(action, view=view, phase=phase)

    def clear_action_highlight(self) -> None:
        self._menu.clear_highlight()


class ToolPanel(QWidget):
    """EchoPac-style right tool menu."""

    action_requested = Signal(object, str, str, str)
    patient_metrics_changed = Signal(object, object)
    results_requested = Signal()
    magnetic_snap_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolPanel")
        self.setFixedWidth(280)

        self._tabs = QTabWidget()
        self.measure = MeasureTab()
        self.controls = ControlsTab()
        self.dicom_inspector = DicomTagInspectorWidget()

        self._tabs.addTab(self.measure, "Measures")
        self._tabs.addTab(self.controls, "Controls")
        self._dicom_tab_index = self._tabs.addTab(self.dicom_inspector, "DICOM")

        self.measure.action_requested.connect(self.action_requested.emit)
        self.measure.patient_metrics_changed.connect(self.patient_metrics_changed.emit)
        self.measure.results_requested.connect(self.results_requested.emit)
        self.controls.magnetic_snap_changed.connect(self.magnetic_snap_changed.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)

    def set_patient_metrics(self, height_cm: float | None, weight_kg: float | None) -> None:
        self.measure.set_patient_metrics(height_cm, weight_kg)

    def set_dicom_inspector_visible(self, visible: bool) -> None:
        self._tabs.setTabVisible(self._dicom_tab_index, visible)

    def load_dicom_inspector(self, path) -> None:
        from pathlib import Path

        if path is None:
            self.dicom_inspector.load_instance(None)
            return
        self.dicom_inspector.load_instance(Path(path) if not isinstance(path, Path) else path)

    def set_doppler_tool_availability(self, *, time_ok: bool) -> None:
        self.measure.set_doppler_tool_availability(time_ok=time_ok)
