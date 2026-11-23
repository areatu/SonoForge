"""Left-side control panel for Strain Window."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
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

from echo_personal_tool.application.localization import tr
from echo_personal_tool.keyboard_shortcuts import append_shortcut_hint
from echo_personal_tool.ui.strain_helpers import PALETTES
from echo_personal_tool.ui.ui_metrics import text_width

# UI colour literals live once per module: the colour ratchet counts
# occurrences, so every repeat references the constant instead.
_TEXT_STYLE = "color: #e0e0e0;"
_GROUP_TITLE_STYLE = "QGroupBox { font-weight: bold; color: #e0e0e0; }"


class ControlPanel(QWidget):
    """Left-side control panel for Strain Window."""

    view_toggled = Signal(str, bool)  # view_name, checked
    display_mode_changed = Signal(str)  # "contour", "curves", "sr", "peak", "overview"
    strain_metric_changed = Signal(str)  # "deformation", "strain_rate", "peak"
    strain_layer_changed = Signal(str)  # "endo" | "mid" | "epi" (plan А.8)
    qc_segment_toggled = Signal(int, bool)  # segment_id, accepted
    position_selected = Signal(str)  # "A4C" | "A2C" | "A3C"
    ttp_mode_toggled = Signal(bool)  # bull's-eye: strain vs time-to-peak
    palette_changed = Signal(str)  # bull's-eye palette i18n key
    save_gold_contour = Signal()  # user asked to save ED endo as gold
    load_gold_contour = Signal()  # user asked to load an existing gold contour

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(text_width(self, tr("strain.view_mode"), padding=48, minimum=180))

        # The panel needs more vertical room than a laptop screen gives the
        # window (QC checkboxes + nine buttons); without a scroll the bottom
        # groups were pushed past the window edge and the action buttons
        # overlapped each other (user feedback: «Контроль качества» /
        # «Действия» не помещаются). Everything scrolls now; nothing is cut.
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self._init_view_mode_group(layout)
        self._init_metric_group(layout)
        self._init_layer_group(layout)
        self._init_views_group(layout)
        self._init_position_group(layout)
        self._init_quality_group(layout)
        self._init_qc_scroll(layout)
        self._init_actions_group(layout)

        layout.addStretch()

        # The scroll carries the whole body: the panel keeps its natural size
        # hint and the area grows/shrinks with the window instead of cutting
        # the bottom groups off.
        body_scroll = QScrollArea()
        body_scroll.setWidget(body)
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer_layout.addWidget(body_scroll)

    def _init_view_mode_group(self, layout: QVBoxLayout) -> None:
        """View mode (contour vs curves)."""
        group_view_mode = QGroupBox(tr("strain.view_mode"))
        group_view_mode.setStyleSheet(_GROUP_TITLE_STYLE)
        view_mode_layout = QVBoxLayout()

        self._mode_contour = QRadioButton(tr("strain.mode_cine_contour"))
        self._mode_contour.setChecked(True)
        self._mode_contour.setStyleSheet(_TEXT_STYLE)
        self._mode_contour.toggled.connect(lambda c: self.display_mode_changed.emit("contour") if c else None)
        view_mode_layout.addWidget(self._mode_contour)

        self._mode_curves = QRadioButton(tr("strain.mode_curves"))
        self._mode_curves.setStyleSheet(_TEXT_STYLE)
        self._mode_curves.toggled.connect(lambda c: self.display_mode_changed.emit("curves") if c else None)
        view_mode_layout.addWidget(self._mode_curves)

        self._mode_overview = QRadioButton(tr("strain.mode_overview"))
        self._mode_overview.setStyleSheet(_TEXT_STYLE)
        self._mode_overview.toggled.connect(lambda c: self.display_mode_changed.emit("overview") if c else None)
        view_mode_layout.addWidget(self._mode_overview)

        group_view_mode.setLayout(view_mode_layout)
        layout.addWidget(group_view_mode)

    def _init_metric_group(self, layout: QVBoxLayout) -> None:
        """Strain metric (Clinical-style: Deformation / SR / Peak)."""
        group_metric = QGroupBox(tr("strain.metric"))
        group_metric.setStyleSheet(_GROUP_TITLE_STYLE)
        metric_layout = QVBoxLayout()

        self._metric_deformation = QRadioButton(tr("strain.metric_deformation"))
        self._metric_deformation.setChecked(True)
        self._metric_deformation.setStyleSheet(_TEXT_STYLE)
        self._metric_deformation.toggled.connect(
            lambda c: self.strain_metric_changed.emit("deformation") if c else None
        )
        metric_layout.addWidget(self._metric_deformation)

        self._metric_sr = QRadioButton(tr("strain.metric_sr"))
        self._metric_sr.setStyleSheet(_TEXT_STYLE)
        self._metric_sr.toggled.connect(lambda c: self.strain_metric_changed.emit("strain_rate") if c else None)
        # SR/peak are drawn as the same strain curve with a different title
        # («GLS Rate: --»), which reads as a real measurement — disabled with
        # an honest tooltip until the domain computes them.
        self._metric_sr.setEnabled(False)
        self._metric_sr.setToolTip(tr("strain.metric_not_available"))
        metric_layout.addWidget(self._metric_sr)

        self._metric_peak = QRadioButton(tr("strain.metric_peak"))
        self._metric_peak.setStyleSheet(_TEXT_STYLE)
        self._metric_peak.toggled.connect(lambda c: self.strain_metric_changed.emit("peak") if c else None)
        self._metric_peak.setEnabled(False)
        self._metric_peak.setToolTip(tr("strain.metric_not_available"))
        metric_layout.addWidget(self._metric_peak)

        group_metric.setLayout(metric_layout)
        layout.addWidget(group_metric)

    def _init_layer_group(self, layout: QVBoxLayout) -> None:
        """Myocardial layer selection (plan А.8): which layer the curves plot."""
        group_layer = QGroupBox(tr("strain.layer_group"))
        group_layer.setStyleSheet(_GROUP_TITLE_STYLE)
        layer_layout = QVBoxLayout()

        self._layer_buttons: dict[str, QRadioButton] = {}
        for layer in ("endo", "mid", "epi"):
            button = QRadioButton(tr(f"strain.layer_{layer}"))
            button.setStyleSheet(_TEXT_STYLE)
            if layer == "endo":
                button.setChecked(True)
            button.toggled.connect(
                lambda checked, name=layer: self.strain_layer_changed.emit(name) if checked else None
            )
            layer_layout.addWidget(button)
            self._layer_buttons[layer] = button

        group_layer.setLayout(layer_layout)
        layout.addWidget(group_layer)

    def set_layer(self, layer: str) -> None:
        """Select the layer radio without re-emitting (restoring state)."""
        button = self._layer_buttons.get(layer)
        if button is not None:
            with QSignalBlocker(button):
                button.setChecked(True)

    def _init_views_group(self, layout: QVBoxLayout) -> None:
        """View toggles (which clips contribute to the study)."""
        group_views = QGroupBox(tr("strain.views"))
        group_views.setStyleSheet(_GROUP_TITLE_STYLE)
        views_layout = QVBoxLayout()

        self._cb_a4c = QCheckBox("A4C")
        self._cb_a4c.setChecked(True)
        self._cb_a4c.setStyleSheet(_TEXT_STYLE)
        self._cb_a4c.toggled.connect(lambda c: self.view_toggled.emit("A4C", c))
        views_layout.addWidget(self._cb_a4c)

        self._cb_a2c = QCheckBox("A2C")
        self._cb_a2c.setChecked(True)
        self._cb_a2c.setStyleSheet(_TEXT_STYLE)
        self._cb_a2c.toggled.connect(lambda c: self.view_toggled.emit("A2C", c))
        views_layout.addWidget(self._cb_a2c)

        self._cb_dao = QCheckBox(tr("strain.view_dao"))
        self._cb_dao.setChecked(True)
        self._cb_dao.setStyleSheet(_TEXT_STYLE)
        self._cb_dao.toggled.connect(lambda c: self.view_toggled.emit("DAO", c))
        views_layout.addWidget(self._cb_dao)

        group_views.setLayout(views_layout)
        layout.addWidget(group_views)

    def _init_position_group(self, layout: QVBoxLayout) -> None:
        """Position (view) selection — which clip the contours came from."""
        group_position = QGroupBox(tr("strain.position"))
        group_position.setStyleSheet(_GROUP_TITLE_STYLE)
        position_layout = QVBoxLayout()

        self._pos_a4c = QRadioButton("A4C")
        self._pos_a4c.setChecked(True)
        self._pos_a4c.setStyleSheet(_TEXT_STYLE)
        self._pos_a4c.toggled.connect(lambda c: self.position_selected.emit("A4C") if c else None)
        position_layout.addWidget(self._pos_a4c)

        self._pos_a2c = QRadioButton("A2C")
        self._pos_a2c.setStyleSheet(_TEXT_STYLE)
        self._pos_a2c.toggled.connect(lambda c: self.position_selected.emit("A2C") if c else None)
        position_layout.addWidget(self._pos_a2c)

        self._pos_a3c = QRadioButton(tr("strain.position_a3c"))
        self._pos_a3c.setStyleSheet(_TEXT_STYLE)
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
        self._cb_palette.setToolTip(append_shortcut_hint(tr("strain.palette_hint"), "strain_palette"))
        self._cb_palette.currentIndexChanged.connect(
            lambda _index: self.palette_changed.emit(str(self._cb_palette.currentData()))
        )
        position_layout.addWidget(QLabel(tr("strain.palette")))
        position_layout.addWidget(self._cb_palette)

        group_position.setLayout(position_layout)
        layout.addWidget(group_position)

    def _init_quality_group(self, layout: QVBoxLayout) -> None:
        """Quality info block."""
        group_quality = QGroupBox(tr("strain.quality_gate"))
        group_quality.setStyleSheet(_GROUP_TITLE_STYLE)
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

    def _init_qc_scroll(self, layout: QVBoxLayout) -> None:
        """Quality Control (per-segment checkboxes) in its own scroll."""
        self._qc_group = QGroupBox(tr("strain.quality_control"))
        self._qc_group.setStyleSheet(_GROUP_TITLE_STYLE)
        self._qc_layout = QVBoxLayout()
        self._qc_layout.setSpacing(2)

        self._qc_checkboxes: dict[int, QCheckBox] = {}
        # Will be populated when results arrive
        self._qc_placeholder: QLabel | None = QLabel(tr("strain.load_results"))
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

    def _init_actions_group(self, layout: QVBoxLayout) -> None:
        """Action buttons (undo/redo/export/gold/close)."""
        group_actions = QGroupBox(tr("strain.actions"))
        group_actions.setStyleSheet(_GROUP_TITLE_STYLE)
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

        # Gold contour save/load (plan §11.2 п.1): writes the currently-edited
        # ED endo contour to gold/ in the format used by the ONNX segmentation
        # benchmarks, so the user can iteratively mark 2-3 ground-truth clips
        # and push them for vendor-comparison (§5.3 п.1).
        self._btn_save_gold = QPushButton(tr("strain.btn_save_gold"))
        self._btn_save_gold.setToolTip(tr("strain.btn_save_gold_hint"))
        self._btn_save_gold.clicked.connect(self.save_gold_contour.emit)
        actions_layout.addWidget(self._btn_save_gold)

        self._btn_load_gold = QPushButton(tr("strain.btn_load_gold"))
        self._btn_load_gold.setToolTip(tr("strain.btn_load_gold_hint"))
        self._btn_load_gold.clicked.connect(self.load_gold_contour.emit)
        actions_layout.addWidget(self._btn_load_gold)

        self._btn_close = QPushButton(tr("strain.btn_close"))
        actions_layout.addWidget(self._btn_close)

        group_actions.setLayout(actions_layout)
        layout.addWidget(group_actions)

    def update_quality(self, accepted: int, total: int, rejected: int) -> None:
        if total > 0:
            pct = (accepted / total) * 100.0
            self._quality_label.setText(f"{accepted} / {total} ({pct:.0f}%)")
        else:
            self._quality_label.setText("-- / --")

        if rejected > 0:
            self._rejected_label.setText(tr("strain.kernels_rejected", count=rejected))
        else:
            self._rejected_label.setText("")

    def set_position(self, view: str) -> None:
        """Set the selected position radio without re-emitting."""
        view = view.upper()
        radio = {"A4C": self._pos_a4c, "A2C": self._pos_a2c, "A3C": self._pos_a3c}.get(view)
        if radio is not None:
            with QSignalBlocker(radio):
                radio.setChecked(True)
