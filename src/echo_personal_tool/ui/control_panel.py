"""Left-side control panel for Strain Window."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.ui.strain_helpers import PALETTES


class ControlPanel(QWidget):
    """Left-side control panel for Strain Window."""

    view_toggled = Signal(str, bool)  # view_name, checked
    display_mode_changed = Signal(str)  # "contour", "curves", "sr", "peak"
    strain_metric_changed = Signal(str)  # "deformation", "strain_rate", "peak"
    qc_segment_toggled = Signal(int, bool)  # segment_id, accepted
    position_selected = Signal(str)  # "A4C" | "A2C" | "A3C"
    ttp_mode_toggled = Signal(bool)  # bull's-eye: strain vs time-to-peak
    palette_changed = Signal(str)  # bull's-eye palette i18n key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # View mode (contour vs curves)
        group_view_mode = QGroupBox(tr("strain.view_mode"))
        group_view_mode.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        view_mode_layout = QVBoxLayout()

        self._mode_contour = QRadioButton(tr("strain.mode_cine_contour"))
        self._mode_contour.setChecked(True)
        self._mode_contour.setStyleSheet("color: #e0e0e0;")
        self._mode_contour.toggled.connect(lambda c: self.display_mode_changed.emit("contour") if c else None)
        view_mode_layout.addWidget(self._mode_contour)

        self._mode_curves = QRadioButton(tr("strain.mode_curves"))
        self._mode_curves.setStyleSheet("color: #e0e0e0;")
        self._mode_curves.toggled.connect(lambda c: self.display_mode_changed.emit("curves") if c else None)
        view_mode_layout.addWidget(self._mode_curves)

        self._mode_overview = QRadioButton(tr("strain.mode_overview"))
        self._mode_overview.setStyleSheet("color: #e0e0e0;")
        self._mode_overview.toggled.connect(lambda c: self.display_mode_changed.emit("overview") if c else None)
        view_mode_layout.addWidget(self._mode_overview)

        group_view_mode.setLayout(view_mode_layout)
        layout.addWidget(group_view_mode)

        # Strain metric (Clinical-style: Deformation / SR / Peak)
        group_metric = QGroupBox(tr("strain.metric"))
        group_metric.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        metric_layout = QVBoxLayout()

        self._metric_deformation = QRadioButton(tr("strain.metric_deformation"))
        self._metric_deformation.setChecked(True)
        self._metric_deformation.setStyleSheet("color: #e0e0e0;")
        self._metric_deformation.toggled.connect(
            lambda c: self.strain_metric_changed.emit("deformation") if c else None
        )
        metric_layout.addWidget(self._metric_deformation)

        self._metric_sr = QRadioButton(tr("strain.metric_sr"))
        self._metric_sr.setStyleSheet("color: #e0e0e0;")
        self._metric_sr.toggled.connect(lambda c: self.strain_metric_changed.emit("strain_rate") if c else None)
        metric_layout.addWidget(self._metric_sr)

        self._metric_peak = QRadioButton(tr("strain.metric_peak"))
        self._metric_peak.setStyleSheet("color: #e0e0e0;")
        self._metric_peak.toggled.connect(lambda c: self.strain_metric_changed.emit("peak") if c else None)
        metric_layout.addWidget(self._metric_peak)

        group_metric.setLayout(metric_layout)
        layout.addWidget(group_metric)

        # View toggles
        group_views = QGroupBox("Views")
        group_views.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        views_layout = QVBoxLayout()

        self._cb_a4c = QCheckBox("A4C")
        self._cb_a4c.setChecked(True)
        self._cb_a4c.setStyleSheet("color: #e0e0e0;")
        self._cb_a4c.toggled.connect(lambda c: self.view_toggled.emit("A4C", c))
        views_layout.addWidget(self._cb_a4c)

        self._cb_a2c = QCheckBox("A2C")
        self._cb_a2c.setChecked(True)
        self._cb_a2c.setStyleSheet("color: #e0e0e0;")
        self._cb_a2c.toggled.connect(lambda c: self.view_toggled.emit("A2C", c))
        views_layout.addWidget(self._cb_a2c)

        self._cb_dao = QCheckBox("DAO (A3C)")
        self._cb_dao.setChecked(True)
        self._cb_dao.setStyleSheet("color: #e0e0e0;")
        self._cb_dao.toggled.connect(lambda c: self.view_toggled.emit("DAO", c))
        views_layout.addWidget(self._cb_dao)

        group_views.setLayout(views_layout)
        layout.addWidget(group_views)

        # Position (view) selection — which clip the contours came from
        group_position = QGroupBox(tr("strain.position"))
        group_position.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        position_layout = QVBoxLayout()

        self._pos_a4c = QRadioButton("A4C")
        self._pos_a4c.setChecked(True)
        self._pos_a4c.setStyleSheet("color: #e0e0e0;")
        self._pos_a4c.toggled.connect(lambda c: self.position_selected.emit("A4C") if c else None)
        position_layout.addWidget(self._pos_a4c)

        self._pos_a2c = QRadioButton("A2C")
        self._pos_a2c.setStyleSheet("color: #e0e0e0;")
        self._pos_a2c.toggled.connect(lambda c: self.position_selected.emit("A2C") if c else None)
        position_layout.addWidget(self._pos_a2c)

        self._pos_a3c = QRadioButton(tr("strain.position_a3c"))
        self._pos_a3c.setStyleSheet("color: #e0e0e0;")
        self._pos_a3c.toggled.connect(lambda c: self.position_selected.emit("A3C") if c else None)
        # Bull's-eye mode: strain (default) or time-to-peak map.
        self._cb_ttp = QCheckBox(tr("strain.bullseye_ttp"))
        self._cb_ttp.setToolTip(tr("strain.bullseye_ttp_hint"))
        self._cb_ttp.toggled.connect(self.ttp_mode_toggled.emit)
        position_layout.addWidget(self._pos_a3c)
        position_layout.addWidget(self._cb_ttp)

        # Bull's-eye palette (plan §6.5): the GE ramp is the default, the combo
        # makes the alternatives discoverable, ``C`` cycles them.
        self._cb_palette = QComboBox()
        for key, _ramp in PALETTES:
            self._cb_palette.addItem(tr(key), key)
        self._cb_palette.setToolTip(tr("strain.palette_hint"))
        self._cb_palette.currentIndexChanged.connect(
            lambda _index: self.palette_changed.emit(str(self._cb_palette.currentData()))
        )
        position_layout.addWidget(QLabel(tr("strain.palette")))
        position_layout.addWidget(self._cb_palette)

        group_position.setLayout(position_layout)
        layout.addWidget(group_position)

        # Quality info
        group_quality = QGroupBox("Quality Gate")
        group_quality.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        quality_layout = QVBoxLayout()

        self._quality_label = QLabel("-- / --")
        self._quality_label.setStyleSheet("color: #80cbc4; font-size: 11px;")
        quality_layout.addWidget(self._quality_label)

        self._rejected_label = QLabel("")
        self._rejected_label.setStyleSheet("color: #ff9800; font-size: 10px;")
        self._rejected_label.setWordWrap(True)
        quality_layout.addWidget(self._rejected_label)

        group_quality.setLayout(quality_layout)
        layout.addWidget(group_quality)

        # Quality Control (per-segment checkboxes)
        self._qc_group = QGroupBox("Quality Control")
        self._qc_group.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        self._qc_layout = QVBoxLayout()
        self._qc_layout.setSpacing(2)

        self._qc_checkboxes: dict[int, QCheckBox] = {}
        # Will be populated when results arrive
        self._qc_placeholder = QLabel(tr("strain.load_results"))
        self._qc_placeholder.setStyleSheet("color: #9e9e9e; font-size: 10px;")
        self._qc_layout.addWidget(self._qc_placeholder)

        self._qc_group.setLayout(self._qc_layout)

        # Wrap in scroll area for many checkboxes
        qc_scroll = QScrollArea()
        qc_scroll.setWidget(self._qc_group)
        qc_scroll.setWidgetResizable(True)
        qc_scroll.setMaximumHeight(150)
        qc_scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(qc_scroll)

        # Actions
        group_actions = QGroupBox(tr("strain.actions"))
        group_actions.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        actions_layout = QVBoxLayout()

        self._btn_edit_mode = QPushButton(tr("strain.btn_edit_mode"))
        self._btn_edit_mode.setCheckable(True)
        self._btn_edit_mode.toggled.connect(lambda c: self.display_mode_changed.emit("edit_mode" if c else "contour"))
        actions_layout.addWidget(self._btn_edit_mode)

        self._btn_undo = QPushButton(tr("strain.btn_undo"))
        self._btn_undo.setEnabled(False)
        actions_layout.addWidget(self._btn_undo)

        self._btn_redo = QPushButton(tr("strain.btn_redo"))
        self._btn_redo.setEnabled(False)
        actions_layout.addWidget(self._btn_redo)

        self._btn_save = QPushButton(tr("strain.btn_save_json"))
        actions_layout.addWidget(self._btn_save)

        self._btn_export_png = QPushButton(tr("strain.btn_export_png"))
        actions_layout.addWidget(self._btn_export_png)

        self._btn_export_csv = QPushButton(tr("strain.btn_export_csv"))
        actions_layout.addWidget(self._btn_export_csv)

        self._btn_close = QPushButton(tr("strain.btn_close"))
        actions_layout.addWidget(self._btn_close)

        group_actions.setLayout(actions_layout)
        layout.addWidget(group_actions)

        layout.addStretch()

    def update_quality(self, accepted: int, total: int, rejected: int) -> None:
        if total > 0:
            pct = (accepted / total) * 100.0
            self._quality_label.setText(f"{accepted} / {total} ({pct:.0f}%)")
        else:
            self._quality_label.setText("-- / --")

        if rejected > 0:
            self._rejected_label.setText(f"{rejected} kernels rejected")
        else:
            self._rejected_label.setText("")

    def set_position(self, view: str) -> None:
        """Set the selected position radio without re-emitting."""
        view = view.upper()
        radio = {"A4C": self._pos_a4c, "A2C": self._pos_a2c, "A3C": self._pos_a3c}.get(view)
        if radio is not None:
            with QSignalBlocker(radio):
                radio.setChecked(True)
