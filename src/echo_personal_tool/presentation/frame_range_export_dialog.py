"""Dialog asking whether an export covers the whole clip or a frame range.

Exporting a clip (MP4 or DICOM) first asks this question: the whole file, or
consecutive frames «from … to …» (1-based, inclusive).  ``frame_range()``
returns ``None`` for the whole file or a 0-based inclusive ``(start, end)``
range the export workers slice with.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.presentation.styled_dialogs import localize_dialog_button_box


class FrameRangeExportDialog(QDialog):
    """«Whole file or consecutive frames?» before an MP4/DICOM export."""

    def __init__(self, parent: QWidget | None = None, *, total_frames: int) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("export_range.title"))
        self._total = max(1, int(total_frames))

        self._whole_radio = QRadioButton(tr("export_range.whole"), self)
        self._range_radio = QRadioButton(tr("export_range.range"), self)
        self._whole_radio.setChecked(True)

        self._from_spin = QSpinBox(self)
        self._from_spin.setRange(1, self._total)
        self._from_spin.setValue(1)
        self._to_spin = QSpinBox(self)
        self._to_spin.setRange(1, self._total)
        self._to_spin.setValue(self._total)
        self._from_spin.valueChanged.connect(self._keep_range_ordered)
        self._to_spin.valueChanged.connect(self._keep_range_ordered)

        range_form = QFormLayout()
        range_form.addRow(tr("export_range.from"), self._from_spin)
        range_form.addRow(tr("export_range.to"), self._to_spin)

        header = QLabel(tr("export_range.header", total=self._total), self)
        header.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        localize_dialog_button_box(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(header)
        layout.addWidget(self._whole_radio)
        layout.addWidget(self._range_radio)
        range_row = QHBoxLayout()
        range_row.addLayout(range_form)
        layout.addLayout(range_row)
        layout.addWidget(buttons)

        self._range_radio.toggled.connect(self._update_enabled)
        self._update_enabled()

    def _keep_range_ordered(self) -> None:
        if self._from_spin.value() > self._to_spin.value():
            self._to_spin.setValue(self._from_spin.value())

    def _update_enabled(self) -> None:
        enabled = self._range_radio.isChecked()
        self._from_spin.setEnabled(enabled)
        self._to_spin.setEnabled(enabled)

    def frame_range(self) -> tuple[int, int] | None:
        """0-based inclusive frame range, or ``None`` for the whole file."""
        if not self._range_radio.isChecked():
            return None
        start = max(0, self._from_spin.value() - 1)
        end = min(self._total - 1, self._to_spin.value() - 1)
        return (start, end)
