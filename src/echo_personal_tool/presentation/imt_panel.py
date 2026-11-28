"""Compact in-view IMT controls; technical settings stay out of the review path."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr


class ImtPanelPort(Protocol):
    """Controls and callbacks supplied by the editor, with no reverse import."""

    side: QComboBox
    more: QCheckBox
    angle: QDoubleSpinBox
    fields: dict[str, QLineEdit]
    metrics: dict[str, QLabel]
    status: QLabel
    calibration_status: QLabel
    use_dicom: QPushButton
    edit_boundaries: QCheckBox
    accept_button: QPushButton
    details: QScrollArea

    @property
    def panel_widget(self) -> QWidget: ...
    def run(self, callback: Callable[[], None]) -> None: ...
    def start_selection(self) -> None: ...
    def set_boundary_editing(self, enabled: bool) -> None: ...
    def accept_result(self) -> None: ...
    def reject(self) -> None: ...
    def restore_dicom_scale(self) -> None: ...
    def propose(self) -> None: ...
    def load(self) -> None: ...
    def revalidate(self) -> None: ...
    def rotate_selection(self, angle: float) -> None: ...
    def reposition(self) -> None: ...


def build_imt_panel(editor: ImtPanelPort) -> None:
    """Build controls on the child overlay, never in a second native window."""
    layout = QVBoxLayout(editor.panel_widget)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(4)
    heading = QHBoxLayout()
    heading.addWidget(QLabel(tr("imt.open")))
    heading.addStretch()
    heading.addWidget(QLabel(tr("imt.side")))
    editor.side = QComboBox()
    editor.side.addItems(["R", "L"])
    heading.addWidget(editor.side)
    editor.more = QCheckBox(tr("imt.more"))
    heading.addWidget(editor.more)
    layout.addLayout(heading)
    select = QPushButton(tr("imt.select"))
    select.clicked.connect(lambda: editor.run(editor.start_selection))
    selection_row = QHBoxLayout()
    selection_row.addWidget(select, 1)
    selection_row.addWidget(QLabel(tr("imt.angle")))
    editor.angle = QDoubleSpinBox()
    editor.angle.setRange(-45, 45)
    editor.angle.setDecimals(1)
    editor.angle.setSingleStep(1)
    editor.angle.setSuffix("°")
    editor.angle.setToolTip(tr("imt.rotate_hint"))
    editor.angle.setEnabled(False)
    editor.angle.valueChanged.connect(lambda angle: editor.run(lambda: editor.rotate_selection(angle)))
    selection_row.addWidget(editor.angle)
    reset = QPushButton("0°")
    reset.setToolTip(tr("imt.angle_reset"))
    reset.clicked.connect(lambda: editor.angle.setValue(0))
    selection_row.addWidget(reset)
    layout.addLayout(selection_row)
    metrics = QHBoxLayout()
    editor.metrics = {}
    for key in ("minimum", "mean", "maximum"):
        label = QLabel(tr(f"imt.{key}") + ": —")
        label.setToolTip(tr("imt.legend"))
        metrics.addWidget(label)
        editor.metrics[key] = label
    layout.addLayout(metrics)
    editor.status = QLabel(tr("imt.select_hint"))
    editor.status.setWordWrap(True)
    layout.addWidget(editor.status)
    editor.calibration_status = QLabel()
    editor.calibration_status.setWordWrap(True)
    layout.addWidget(editor.calibration_status)
    editor.use_dicom = QPushButton(tr("imt.use_dicom"))
    editor.use_dicom.setToolTip(tr("imt.use_dicom_tip"))
    editor.use_dicom.clicked.connect(lambda: editor.run(editor.restore_dicom_scale))
    editor.use_dicom.hide()
    layout.addWidget(editor.use_dicom)
    actions = QHBoxLayout()
    editor.edit_boundaries = QCheckBox(tr("imt.edit_boundaries"))
    editor.edit_boundaries.toggled.connect(editor.set_boundary_editing)
    actions.addWidget(editor.edit_boundaries)
    editor.accept_button = QPushButton(tr("imt.accept_report"))
    editor.accept_button.setEnabled(False)
    editor.accept_button.clicked.connect(lambda: editor.run(editor.accept_result))
    actions.addWidget(editor.accept_button)
    reject = QPushButton(tr("imt.discard"))
    reject.clicked.connect(editor.reject)
    actions.addWidget(reject)
    layout.addLayout(actions)

    editor.details = QScrollArea()
    editor.details.setWidgetResizable(True)
    editor.details.setMinimumHeight(160)
    content = QWidget()
    details_layout = QVBoxLayout(content)
    for key in ("warning", "legend"):
        label = QLabel(tr(f"imt.{key}"))
        label.setWordWrap(True)
        details_layout.addWidget(label)
    form = QFormLayout()
    editor.fields = {}
    for key, placeholder in (
        ("roi", "x0,y0,x1,y1"),
        ("guides", tr("imt.auto_guides")),
        ("policy", "min-mm,max-mm,coverage,contrast"),
    ):
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        editor.fields[key] = field
        form.addRow(tr(f"imt.{key}"), field)
    editor.fields["policy"].setText("0.2,2.0,0.7,0.03")
    details_layout.addLayout(form)
    for key, callback in (("propose", editor.propose), ("load", editor.load), ("revalidate", editor.revalidate)):
        button = QPushButton(tr(f"imt.{key}"))
        button.clicked.connect(lambda _checked=False, fn=callback: editor.run(fn))
        details_layout.addWidget(button)
    editor.details.setWidget(content)
    editor.details.hide()
    layout.addWidget(editor.details)
    editor.more.toggled.connect(editor.details.setVisible)
    editor.more.toggled.connect(lambda: QTimer.singleShot(0, editor.reposition))
