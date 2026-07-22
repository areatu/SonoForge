"""Dialog for speckle tracking configuration presets."""

from __future__ import annotations

import dataclasses

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.models.speckle import SpeckleConfig
from echo_personal_tool.infrastructure.i18n import tr


class SpeckleSettingsDialog(QDialog):
    """Select speckle preset and override key parameters."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        current_frame: int = 0,
        manual_ed: int | None = None,
        manual_es: int | None = None,
        n_frames: int = 0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.speckle_settings.title"))

        self._preset_combo = QComboBox(self)
        self._preset_combo.addItem("Standard", "standard")
        self._preset_combo.addItem("Research", "research")
        self._preset_combo.addItem("Debug", "debug")

        self._drift_compensation_check = QCheckBox(self)
        self._drift_compensation_check.setChecked(True)

        self._wall_thickness_spin = QDoubleSpinBox(self)
        self._wall_thickness_spin.setRange(6.0, 12.0)
        self._wall_thickness_spin.setSingleStep(0.5)
        self._wall_thickness_spin.setDecimals(1)
        self._wall_thickness_spin.setSuffix(" mm")
        self._wall_thickness_spin.setValue(8.0)

        self._ed_spin = QSpinBox(self)
        self._ed_spin.setRange(0, max(0, n_frames - 1))
        self._ed_spin.setSuffix(f" / {n_frames - 1}" if n_frames > 0 else "")
        self._ed_spin.setValue(manual_ed if manual_ed is not None else current_frame)
        self._ed_auto_check = QCheckBox("Auto-detect ED")
        self._ed_auto_check.setChecked(manual_ed is None)
        self._ed_spin.setEnabled(manual_ed is not None)

        self._es_spin = QSpinBox(self)
        self._es_spin.setRange(0, max(0, n_frames - 1))
        self._es_spin.setSuffix(f" / {n_frames - 1}" if n_frames > 0 else "")
        self._es_spin.setValue(manual_es if manual_es is not None else current_frame)
        self._es_auto_check = QCheckBox("Auto-detect ES")
        self._es_auto_check.setChecked(manual_es is None)
        self._es_spin.setEnabled(manual_es is not None)

        self._ed_auto_check.toggled.connect(lambda checked: self._ed_spin.setEnabled(not checked))
        self._es_auto_check.toggled.connect(lambda checked: self._es_spin.setEnabled(not checked))

        form = QFormLayout()
        form.addRow("Preset:", self._preset_combo)
        form.addRow("Drift compensation:", self._drift_compensation_check)
        form.addRow("Wall thickness:", self._wall_thickness_spin)
        form.addRow(self._ed_auto_check)
        form.addRow("ED frame:", self._ed_spin)
        form.addRow(self._es_auto_check)
        form.addRow("ES frame:", self._es_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def selected_preset_name(self) -> str:
        return str(self._preset_combo.currentData())

    @property
    def manual_ed(self) -> int | None:
        if self._ed_auto_check.isChecked():
            return None
        return self._ed_spin.value()

    @property
    def manual_es(self) -> int | None:
        if self._es_auto_check.isChecked():
            return None
        return self._es_spin.value()

    def get_config(self) -> SpeckleConfig:
        """Build SpeckleConfig from selected preset and UI overrides."""
        preset_name = self.selected_preset_name()
        if preset_name == "research":
            base = SpeckleConfig.preset_research()
        elif preset_name == "debug":
            base = SpeckleConfig.preset_debug()
        else:
            base = SpeckleConfig.preset_standard()

        return dataclasses.replace(
            base,
            drift_compensation=self._drift_compensation_check.isChecked(),
            wall_thickness_mm=float(self._wall_thickness_spin.value()),
        )
