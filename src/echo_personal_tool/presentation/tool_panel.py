"""Right-side tool panel with Measures / Controls tabs."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.presentation.calculators_panel import CalculatorsPanel
from echo_personal_tool.presentation.dicom_tag_inspector_widget import DicomTagInspectorWidget
from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider
from echo_personal_tool.presentation.measurement_action import MeasurementAction
from echo_personal_tool.presentation.measures_menu import MeasuresMenuWidget
from echo_personal_tool.presentation.properties_panel import PropertiesPanel
from echo_personal_tool.presentation.tool_panel_v2 import (
    PANEL_MAX_WIDTH,
    PANEL_MIN_WIDTH,
    PANEL_WIDTH,
    ToolPanelV2,
)
from echo_personal_tool.presentation.ui_animations import HoverButtonMixin, _reduce_motion_enabled
from echo_personal_tool.presentation.ui_metrics import icon_button_size, widest_text_width


class _PatientMetricsRow(QWidget):
    """Height / weight inputs (0 = empty, whole cm/kg)."""

    _LABEL_STYLE = "font-size: 14px; font-weight: 600;"

    metrics_changed = Signal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from echo_personal_tool.infrastructure.i18n import tr

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self._height_label = QLabel(tr("tools.height"))
        self._height_label.setStyleSheet(self._LABEL_STYLE)
        layout.addWidget(self._height_label)
        self._height_spin = QSpinBox()
        self._height_spin.setRange(0, 250)
        self._height_spin.setSpecialValueText("")
        self._height_spin.valueChanged.connect(self._emit_metrics)
        layout.addWidget(self._height_spin)
        self._weight_label = QLabel(tr("tools.weight"))
        self._weight_label.setStyleSheet(self._LABEL_STYLE)
        layout.addWidget(self._weight_label)
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

    def reload_text(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        self._height_label.setText(tr("tools.height"))
        self._weight_label.setText(tr("tools.weight"))


class ControlsTab(QWidget):
    """Window / Level / DR sliders (Clinical controls)."""

    magnetic_snap_changed = Signal(bool)
    despeckle_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from echo_personal_tool.infrastructure.i18n import tr

        self.window_slider = TopLabeledSlider(tr("tools.window"), minimum=1, maximum=400, value=100)
        self.level_slider = TopLabeledSlider(tr("tools.level"), minimum=0, maximum=100, value=50)
        self.dr_slider = TopLabeledSlider(tr("tools.dr"), minimum=0, maximum=100, value=50)
        self.dr_slider.slider().setToolTip(tr("tools.dr_tip"))
        from echo_personal_tool.infrastructure.i18n import tr

        self._magnetic_snap_check = QCheckBox(tr("tools.magnetic_snap"))
        self._magnetic_snap_check.setChecked(True)
        self._magnetic_snap_check.setToolTip(tr("tools.magnetic_snap_tip"))
        self._magnetic_snap_check.toggled.connect(self.magnetic_snap_changed.emit)

        self._despeckle_check = QCheckBox(tr("tools.grayscale"))
        self._despeckle_check.setChecked(False)
        self._despeckle_check.setToolTip(tr("tools.grayscale_tip"))
        self._despeckle_check.toggled.connect(self.despeckle_changed.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(10)
        layout.addWidget(self.window_slider)
        layout.addWidget(self.level_slider)
        layout.addWidget(self.dr_slider)
        layout.addWidget(self._magnetic_snap_check)
        layout.addWidget(self._despeckle_check)
        layout.addStretch(1)

    def reload_text(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        self.window_slider.set_label(tr("tools.window"))
        self.level_slider.set_label(tr("tools.level"))
        self.dr_slider.set_label(tr("tools.dr"))
        self.dr_slider.slider().setToolTip(tr("tools.dr_tip"))
        self._magnetic_snap_check.setText(tr("tools.magnetic_snap"))
        self._magnetic_snap_check.setToolTip(tr("tools.magnetic_snap_tip"))
        self._despeckle_check.setText(tr("tools.grayscale"))
        self._despeckle_check.setToolTip(tr("tools.grayscale_tip"))


class MeasureTab(QWidget):
    """Measurement tools only (results shown on-image overlay)."""

    action_requested = Signal(object, str, str, str)
    patient_metrics_changed = Signal(object, object)
    auto_play_changed = Signal(bool)
    results_requested = Signal()
    doppler_mode_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._menu = MeasuresMenuWidget()
        self._menu.action_requested.connect(self.action_requested.emit)
        self._menu.doppler_mode_changed.connect(self.doppler_mode_changed.emit)
        self._patient_metrics = _PatientMetricsRow()
        self._patient_metrics.metrics_changed.connect(self.patient_metrics_changed.emit)

        self._bsa_basis = None
        self._bsa_label = QLabel()
        self._bsa_label.setStyleSheet("font-size: 14px; font-weight: 600; padding-left: 8px;")
        self._bsa_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._bsa_label.setVisible(False)
        self._patient_metrics.metrics_changed.connect(self._update_bsa)

        from echo_personal_tool.infrastructure.i18n import tr

        self._auto_play_check = QCheckBox(tr("preferences.auto_play"))
        self._auto_play_check.setToolTip(tr("preferences.auto_play"))
        self._auto_play_check.toggled.connect(self.auto_play_changed.emit)

        self._results_button = QPushButton(tr("tool_panel.report"))
        self._results_button.setMinimumHeight(32)
        self._results_button.clicked.connect(self.results_requested.emit)
        HoverButtonMixin.install(self._results_button)
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
        self._layout.addWidget(self._bsa_label, stretch=0)
        self._layout.addWidget(self._metrics_results_gap, stretch=0)
        self._layout.addWidget(self._auto_play_check, stretch=0)

        self._auto_results_spacer = QWidget()
        self._auto_results_spacer.setFixedHeight(8)
        self._layout.addWidget(self._auto_results_spacer, stretch=0)

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

    def set_patient_metrics(
        self,
        height_cm: float | None,
        weight_kg: float | None,
        bsa_basis: object = None,
    ) -> None:
        """Show one BSA for the study, and where it came from (QH-1b.2, slice 2).

        ``bsa_basis`` is the study's resolved :class:`BsaBasis` from the current
        snapshot — the manual value typed in the calculators when there is one,
        the Du Bois estimate otherwise. Passing it in keeps this label from
        computing a second body surface area of its own, which is how the panel
        and the indexed values used to disagree.
        """
        self._patient_metrics.set_metrics(height_cm, weight_kg)
        self._update_bsa(height_cm, weight_kg, bsa_basis)

    def _update_bsa(
        self,
        height_cm: float | None,
        weight_kg: float | None,
        bsa_basis: object = None,
    ) -> None:
        from echo_personal_tool.domain.calculations.body_surface import resolve_bsa_basis

        self._bsa_basis = (
            bsa_basis if bsa_basis is not None else resolve_bsa_basis(height_cm=height_cm, weight_kg=weight_kg)
        )
        self._render_bsa_label()

    def _render_bsa_label(self) -> None:
        from echo_personal_tool.domain.calculations.body_surface import resolve_bsa_basis
        from echo_personal_tool.domain.services.bsa_provenance import bsa_source_label
        from echo_personal_tool.infrastructure.i18n import tr

        basis = self._bsa_basis or resolve_bsa_basis()
        if basis.value is None:
            self._bsa_label.setText(tr("panel.bsa_missing"))
            self._bsa_label.setVisible(True)
            return
        self._bsa_label.setText(f"{tr('panel.bsa')}: {basis.value:.2f} m² ({bsa_source_label(basis)})")
        self._bsa_label.setVisible(True)

    def set_auto_play(self, enabled: bool) -> None:
        self._auto_play_check.blockSignals(True)
        self._auto_play_check.setChecked(enabled)
        self._auto_play_check.blockSignals(False)

    def reload_text(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        self._render_bsa_label()
        self._auto_play_check.setText(tr("preferences.auto_play"))
        self._auto_play_check.setToolTip(tr("preferences.auto_play"))
        self._results_button.setText(tr("tool_panel.report"))
        self._menu.reload_text()
        self._patient_metrics.reload_text()

    def set_doppler_tool_availability(self, *, time_ok: bool, vessel_ok: bool = False) -> None:
        self._menu.set_doppler_tool_availability(time_ok=time_ok, vessel_ok=vessel_ok)

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

    def reset_doppler_mode(self) -> None:
        self._menu.reset_doppler_mode()

    def rebuild_with_preferences(self, preferences) -> None:
        self._menu.rebuild_with_preferences(preferences)

    def vessel_preset(self) -> str:
        return self._menu.vessel_preset()

    #: The legacy Measures tab is not the panel 2.0 implementation.
    is_v2 = False


class ToolPanel(QWidget):
    """Clinical-style right tool menu."""

    #: How much wider the panel gets on the Calculators tab (≥1.5×).
    _CALC_WIDTH_FACTOR = 1.5
    #: Glide duration, same feel as the Measures accordion sections.
    _CALC_WIDTH_ANIM_MS = 180

    action_requested = Signal(object, str, str, str)
    patient_metrics_changed = Signal(object, object)
    auto_play_changed = Signal(bool)
    results_requested = Signal()
    magnetic_snap_changed = Signal(bool)
    despeckle_changed = Signal(bool)
    doppler_mode_changed = Signal(str)
    #: Calculators tab (Э11): study-mode override of one input (``None`` clears).
    calculator_input_changed = Signal(str, object)
    #: Protocol card hooks (TP-3 PR-3); the legacy Measures tab has none.
    protocol_selected = Signal(str)
    protocol_step_activated = Signal(int)
    protocol_stop_requested = Signal()
    #: UI-5: the S2 card of a row asks for the handbook window (S1).
    open_reference_requested = Signal(str)
    #: UI-5: the «Нормы» switch moved (norm dots, UD-14/UQ-03).
    norms_toggled = Signal(bool)
    #: TP-5: the pencil of the 2.0 panel asks for the Tools settings editor.
    edit_requested = Signal(str)
    #: TP-5: in-place editing changed the version-3 layout.
    layout_changed = Signal(str)

    def __init__(self, preferences=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from echo_personal_tool.infrastructure.profile import capabilities_for

        self._profile_capabilities = capabilities_for()
        self._preferences = preferences
        self._v2_enabled = bool(getattr(preferences, "tool_panel_v2", False))
        self._splitter_resizable = False
        self._last_metrics: tuple[object, object, object] = (None, None, None)
        self._last_auto_play = bool(getattr(preferences, "auto_play", False))
        self._last_time_ok = True
        self._last_vessel_ok = False
        self.setObjectName("toolPanel")
        self._collapsed = False
        self._saved_width = PANEL_WIDTH if self._v2_enabled else 280
        self._base_width = PANEL_WIDTH if self._v2_enabled else 280
        self._width_anim: QVariantAnimation | None = None
        self.setMinimumWidth(PANEL_MIN_WIDTH if self._v2_enabled else 280)
        if self._v2_enabled:
            self.setMaximumWidth(PANEL_MAX_WIDTH)

        self._tabs = QTabWidget()
        self._measure = self._make_measure()
        self.controls = ControlsTab()
        self._tag_inspector = DicomTagInspectorWidget()
        self._properties_panel = PropertiesPanel()
        self.calculators = CalculatorsPanel(lazy=True)

        self._tabs.addTab(self._measure, "Measures")
        if self._profile_capabilities.calculators:
            self._tabs.addTab(self.calculators, "Calculators")
            self.calculators.study_input_changed.connect(self.calculator_input_changed.emit)
        self._tabs.addTab(self.controls, "Controls")
        self._tabs.addTab(self._tag_inspector, "DICOM Tags")

        self._connect_measure()
        self.controls.magnetic_snap_changed.connect(self.magnetic_snap_changed.emit)
        self.controls.despeckle_changed.connect(self.despeckle_changed.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)

        # Slide animation for show/hide
        self._slide_anim = QPropertyAnimation(self, b"maximumWidth", self)
        self._slide_anim.setDuration(200)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Tab crossfade animation
        self._current_tab_widget = None
        self._fade_anim = None
        self._tabs.currentChanged.connect(self._on_tab_changed)

    # ── Measures tab implementation (legacy / 2.0) ─────────────────

    def _make_measure(self, preferences=None) -> QWidget:
        if self._v2_enabled:
            return ToolPanelV2(preferences if preferences is not None else self._preferences)
        return MeasureTab()

    def _connect_measure(self) -> None:
        self._measure.action_requested.connect(self.action_requested.emit)
        self._measure.patient_metrics_changed.connect(self.patient_metrics_changed.emit)
        self._measure.auto_play_changed.connect(self.auto_play_changed.emit)
        self._measure.results_requested.connect(self.results_requested.emit)
        self._measure.doppler_mode_changed.connect(self.doppler_mode_changed.emit)
        # Protocol card exists only on the 2.0 panel (TP-3 PR-3).
        if isinstance(self._measure, ToolPanelV2):
            self._measure.protocol_selected.connect(self.protocol_selected.emit)
            self._measure.protocol_step_activated.connect(self.protocol_step_activated.emit)
            self._measure.protocol_stop_requested.connect(self.protocol_stop_requested.emit)
            # UI-5: the S2 card lives at the rows of the 2.0 panel.
            self._measure.open_reference_requested.connect(self.open_reference_requested.emit)
            self._measure.norms_toggled.connect(self.norms_toggled.emit)
            self._measure.edit_requested.connect(self.edit_requested.emit)
            self._measure.layout_changed.connect(self.layout_changed.emit)

    @property
    def measure(self) -> QWidget:
        """The active Measures tab: the legacy menu or the 2.0 panel."""
        return self._measure

    @property
    def is_v2(self) -> bool:
        return self._v2_enabled

    @property
    def preferred_width(self) -> int:
        """Width the panel asks for: 280 legacy, saved/default 320 for 2.0."""
        if not self._v2_enabled:
            return self._base_width
        saved = int(getattr(self._preferences, "panel_width", 0) or 0)
        if saved <= 0:
            return PANEL_WIDTH
        return max(PANEL_MIN_WIDTH, min(PANEL_MAX_WIDTH, saved))

    def set_splitter_resizable(self, resizable: bool) -> None:
        """Let the splitter control the 2.0 width (280–420), or pin it."""
        self._splitter_resizable = bool(resizable) and self._v2_enabled
        if not self._v2_enabled:
            return
        if self._splitter_resizable:
            self.setMinimumWidth(PANEL_MIN_WIDTH)
            self.setMaximumWidth(PANEL_MAX_WIDTH)
            self.resize(self.preferred_width, self.height())
        else:
            self.setMaximumWidth(16777215)
            self.setFixedWidth(self.preferred_width)

    def _replace_measure(self, preferences) -> None:
        old = self._measure
        index = max(0, self._tabs.indexOf(old))
        current = self._tabs.currentWidget()
        self._measure = self._make_measure(preferences)
        from echo_personal_tool.infrastructure.i18n import tr

        self._tabs.insertTab(index, self._measure, tr("tool_panel.measures"))
        old_index = self._tabs.indexOf(old)
        if old_index >= 0:
            self._tabs.removeTab(old_index)
        old.setParent(None)
        old.deleteLater()
        self._connect_measure()
        if current is old:
            self._tabs.setCurrentWidget(self._measure)
        self._measure.set_patient_metrics(*self._last_metrics)
        self._measure.set_auto_play(self._last_auto_play)
        if hasattr(self._measure, "set_doppler_tool_availability"):
            self._measure.set_doppler_tool_availability(time_ok=self._last_time_ok, vessel_ok=self._last_vessel_ok)
        self.sync_width(animated=False)

    def _on_tab_changed(self, index: int) -> None:
        """Crossfade animation when switching tabs."""
        widget = self._tabs.widget(index)
        if widget is None or widget == self._current_tab_widget:
            return
        previous = self._current_tab_widget
        self._current_tab_widget = widget

        if widget is self.calculators or previous is self.calculators:
            # Width glide instead of crossfade: repainting the ~350-widget
            # Calculators tab on top of an opacity fade stutters, while the
            # glide alone already signals the switch.
            self.sync_width()
            return

        if self._fade_anim is not None:
            self._fade_anim.stop()
            self._fade_anim = None
        # Stale opacity effects force offscreen composition on every later
        # paint — drop them so tab switches stay cheap.
        # paint — drop them so tab switches stay cheap.
        for stale in (previous, widget):
            if stale is not None and stale.graphicsEffect() is not None:
                stale.setGraphicsEffect(None)

        # Set new widget opacity to 0 and animate to 1
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

        effect.setOpacity(0.0)
        self._fade_anim = QPropertyAnimation(effect, b"opacity")
        self._fade_anim.setDuration(150)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _cleanup() -> None:
            if widget.graphicsEffect() is effect:
                widget.setGraphicsEffect(None)

        self._fade_anim.finished.connect(_cleanup)
        self._fade_anim.start()
        # Glide back if a previous tab left the panel widened.
        self.sync_width()

    def _target_width(self) -> int:
        """Normal width, or widened (≥1.5×) while the Calculators tab is open."""
        if self._v2_enabled:
            return self.preferred_width
        if self._tabs.currentWidget() is self.calculators:
            return int(self._base_width * self._CALC_WIDTH_FACTOR)
        return self._base_width

    def sync_width(self, *, animated: bool = True) -> None:
        """Snap or glide the panel to the width of the active tab."""
        if self._v2_enabled and self._splitter_resizable:
            # The splitter owns the width; only the bounds are the panel's.
            self.setMinimumWidth(PANEL_MIN_WIDTH)
            self.setMaximumWidth(PANEL_MAX_WIDTH)
            return
        target = self._target_width()
        if self._width_anim is not None:
            self._width_anim.stop()
            self._width_anim = None
        if not animated or not self.isVisible() or self._collapsed or _reduce_motion_enabled():
            self.calculators.set_clip_width(None)
            self.setFixedWidth(target)
            return
        start = self.width()
        if start == target:
            self.calculators.set_clip_width(None)
            self.setFixedWidth(target)
            return
        # The Calculators page keeps a pinned width, so the glide only changes
        # this outer container. The ~350 input widgets are not laid out per frame.
        if self.calculators.is_built:
            self.calculators.set_clip_width(target if target >= start else start)
        anim = QVariantAnimation(self)
        anim.setDuration(self._CALC_WIDTH_ANIM_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.valueChanged.connect(lambda value: self.setFixedWidth(int(value)))

        def _finish() -> None:
            self.setFixedWidth(target)
            self.calculators.set_clip_width(None)

        anim.finished.connect(_finish)
        self._width_anim = anim
        anim.start()

    def showAnimated(self) -> None:
        """Show panel with slide animation."""
        self.setMaximumWidth(0)
        self.show()
        self._slide_anim.stop()
        self._slide_anim.setStartValue(0)
        self._slide_anim.setEndValue(self._saved_width)
        self._slide_anim.start()

    def hideAnimated(self) -> None:
        """Hide panel with slide animation."""
        self._saved_width = self.width()
        self._slide_anim.stop()
        self._slide_anim.setStartValue(self.width())
        self._slide_anim.setEndValue(0)
        self._slide_anim.start()
        self._slide_anim.finished.connect(self._on_hide_finished)

    def _on_hide_finished(self) -> None:
        self.hide()
        self._slide_anim.finished.disconnect(self._on_hide_finished)
        self.setMaximumWidth(16777215)  # Reset to default

    def set_patient_metrics(
        self,
        height_cm: float | None,
        weight_kg: float | None,
        bsa_basis: object = None,
    ) -> None:
        self._last_metrics = (height_cm, weight_kg, bsa_basis)
        self._measure.set_patient_metrics(height_cm, weight_kg, bsa_basis)

    def set_auto_play(self, enabled: bool) -> None:
        self._last_auto_play = bool(enabled)
        self._measure.set_auto_play(enabled)

    def reload_text(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        self._measure.reload_text()
        self.controls.reload_text()
        self._tabs.setTabText(self._tabs.indexOf(self.measure), tr("tool_panel.measures"))
        if self._profile_capabilities.calculators:
            self.calculators.reload_text()
            self._tabs.setTabText(self._tabs.indexOf(self.calculators), tr("tool_panel.calculators"))
        self._tabs.setTabText(self._tabs.indexOf(self.controls), tr("tool_panel.controls"))

    def set_dicom_inspector_visible(self, visible: bool) -> None:
        """Show/hide the DICOM Tags tab."""
        from echo_personal_tool.infrastructure.i18n import tr

        idx = self._tabs.indexOf(self._tag_inspector)
        if visible and idx == -1:
            self._tabs.addTab(self._tag_inspector, tr("tool_panel.dicom_tags"))
        elif not visible and idx != -1:
            self._tabs.removeTab(idx)

    def rebuild_menu_with_preferences(self, preferences) -> None:
        """Rebuild the active Measures tab with updated preferences.

        Switching the experimental flag swaps the implementation of the tab
        in place; the other tabs (Calculators, Controls, DICOM) are untouched.
        """
        self._preferences = preferences
        enabled = bool(getattr(preferences, "tool_panel_v2", False))
        if enabled != self._v2_enabled:
            self._v2_enabled = enabled
            self._base_width = PANEL_WIDTH if enabled else 280
            if enabled:
                self.setMinimumWidth(PANEL_MIN_WIDTH)
                self.setMaximumWidth(PANEL_MAX_WIDTH)
            else:
                self._splitter_resizable = False
                self.setMaximumWidth(16777215)
                self.setMinimumWidth(280)
                self.setFixedWidth(self._base_width)
            self._replace_measure(preferences)
            return
        if hasattr(self._measure, "set_preferences"):
            self._measure.set_preferences(preferences)
        else:
            self._measure.rebuild_with_preferences(preferences)

    def load_dicom_inspector(self, path) -> None:
        """Load DICOM tags from a file path into the inspector."""
        self._tag_inspector.load_instance(path)

    def set_calculations(self, calculations, *, has_study: bool) -> None:
        """Feed the study-mode calculators with the latest snapshot (Э11)."""
        self.calculators.set_study_calculations(calculations, has_study=has_study)

    def show_measures_tab(self) -> None:
        self._tabs.setCurrentWidget(self._measure)

    def focus_search(self) -> None:
        """Focus the 2.0 search field (the legacy menu has no search)."""
        focus = getattr(self._measure, "focus_search", None)
        if callable(focus):
            focus()

    def show_calculators_tab(self) -> None:
        if self._profile_capabilities.calculators and self._tabs.indexOf(self.calculators) >= 0:
            self._tabs.setCurrentWidget(self.calculators)

    def show_properties_tab(self) -> None:
        """Switch to the Properties tab and make it visible if hidden."""
        props_idx = self._tabs.indexOf(self._properties_panel)
        if props_idx == -1:
            from echo_personal_tool.infrastructure.i18n import tr

            self._tabs.addTab(self._properties_panel, tr("tool_panel.properties"))
            props_idx = self._tabs.indexOf(self._properties_panel)
        self._tabs.setCurrentIndex(props_idx)

    def hide_properties_tab(self) -> None:
        """Remove the Properties tab if it was temporarily added."""
        props_idx = self._tabs.indexOf(self._properties_panel)
        if props_idx != -1:
            self._tabs.removeTab(props_idx)

    @property
    def properties_panel(self) -> PropertiesPanel:
        """Access the properties panel to update it."""
        return self._properties_panel

    def set_doppler_tool_availability(self, *, time_ok: bool, vessel_ok: bool = False) -> None:
        self._last_time_ok = bool(time_ok)
        self._last_vessel_ok = bool(vessel_ok)
        self._measure.set_doppler_tool_availability(time_ok=time_ok, vessel_ok=vessel_ok)

    def reset_doppler_mode(self) -> None:
        self._measure.reset_doppler_mode()

    # ── Panel 2.0 context (no-op for the legacy menu) ──────────────

    def set_view_context(self, context: str | None, doppler_mode: str | None = None) -> None:
        if self._v2_enabled and hasattr(self._measure, "set_view_context"):
            self._measure.set_view_context(context, doppler_mode)

    def reset_view_context_override(self) -> None:
        if self._v2_enabled and hasattr(self._measure, "reset_context_override"):
            self._measure.reset_context_override()

    def set_measurement_count(self, count: int | None) -> None:
        if self._v2_enabled and hasattr(self._measure, "set_measurement_count"):
            self._measure.set_measurement_count(count)

    # ── Protocol card (TP-3 PR-3; no-op for the legacy menu) ───────

    def set_protocols(self, protocols) -> None:
        if self._v2_enabled and hasattr(self._measure, "set_protocols"):
            self._measure.set_protocols(protocols)

    def set_protocol_progress(self, progress) -> None:
        if self._v2_enabled and hasattr(self._measure, "set_protocol_progress"):
            self._measure.set_protocol_progress(progress)

    def set_tool_statuses(self, statuses) -> None:
        if self._v2_enabled and hasattr(self._measure, "set_tool_statuses"):
            self._measure.set_tool_statuses(statuses)

    # ── S2 norm card and norm dots (UI-5; no-op for the legacy menu) ──

    def set_reference_sex_provider(self, provider) -> None:
        if self._v2_enabled and hasattr(self._measure, "set_reference_sex_provider"):
            self._measure.set_reference_sex_provider(provider)

    def set_norms_visible(self, visible: bool) -> None:
        if self._v2_enabled and hasattr(self._measure, "set_norms_visible"):
            self._measure.set_norms_visible(visible)

    def hide_reference_card(self) -> None:
        if self._v2_enabled and hasattr(self._measure, "hide_reference_card"):
            self._measure.hide_reference_card()

    def activate_tool(self, tool_id: str) -> None:
        if self._v2_enabled and hasattr(self._measure, "activate_tool"):
            self._measure.activate_tool(tool_id)

    def update_font_metrics(self) -> None:
        """Keep the panel wide enough for its tab captions (Э4)."""
        labels = [self._tabs.tabText(index) for index in range(self._tabs.count())]
        if self._v2_enabled:
            # The 2.0 panel is 320 px by design; the splitter and the saved
            # width decide the rest, the tab captions do not widen it.
            self._base_width = PANEL_WIDTH
            self.setMinimumWidth(PANEL_MIN_WIDTH)
        else:
            self._base_width = widest_text_width(self, labels, padding=48, minimum=280)
            self.setMinimumWidth(self._base_width)
        self.sync_width(animated=False)

    def toggle_collapse(self) -> None:
        if self._collapsed:
            self.setMinimumWidth(self._saved_width)
            self._collapsed = False
            self.show()
        else:
            self._saved_width = self.width()
            self.hide()
            self._collapsed = True

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def showEvent(self, event: QShowEvent) -> None:  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(0, self._ensure_tab_scroll_arrows)

    def _ensure_tab_scroll_arrows(self) -> None:
        """Create custom left/right scroll arrows overlaid on the tab bar."""
        if hasattr(self, "_arrow_left") and self._arrow_left is not None:
            self._update_arrow_positions()
            return

        tab_bar = self._tabs.tabBar()
        btn_w, btn_h = icon_button_size(self, "\u25c0")

        self._arrow_left = QToolButton(self._tabs)
        self._arrow_left.setText("\u25c0")  # ◀
        self._arrow_left.setObjectName("tabScrollArrow")
        self._arrow_left.setFixedSize(btn_w, btn_h)
        self._arrow_left.setCursor(Qt.CursorShape.PointingHandCursor)
        self._arrow_left.clicked.connect(self._scroll_tab_left)

        self._arrow_right = QToolButton(self._tabs)
        self._arrow_right.setText("\u25b6")  # ▶
        self._arrow_right.setObjectName("tabScrollArrow")
        self._arrow_right.setFixedSize(btn_w, btn_h)
        self._arrow_right.setCursor(Qt.CursorShape.PointingHandCursor)
        self._arrow_right.clicked.connect(self._scroll_tab_right)

        tab_bar.installEventFilter(self)
        self._tabs.resizeEvent = self._on_tabs_resize  # type: ignore[assignment]
        self._update_arrow_positions()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self._tabs.tabBar() and event.type() == event.Type.Resize:
            self._update_arrow_positions()
        return super().eventFilter(obj, event)

    def _on_tabs_resize(self, event) -> None:
        QTabWidget.resizeEvent(self._tabs, event)
        self._update_arrow_positions()

    def _update_arrow_positions(self) -> None:
        tab_bar = self._tabs.tabBar()
        if not hasattr(self, "_arrow_left") or self._arrow_left is None:
            return
        btn_size = 22
        margin = 2
        bar_h = tab_bar.height()
        x_right = tab_bar.width() - btn_size - margin
        y = (bar_h - btn_size) // 2
        self._arrow_right.move(x_right, max(y, 0))
        self._arrow_left.move(x_right - btn_size - margin, max(y, 0))
        has_overflow = tab_bar.width() < tab_bar.sizeHint().width()
        self._arrow_left.setVisible(has_overflow)
        self._arrow_right.setVisible(has_overflow)

    def _scroll_tab_left(self) -> None:
        idx = self._tabs.currentIndex()
        if idx > 0:
            self._tabs.setCurrentIndex(idx - 1)

    def _scroll_tab_right(self) -> None:
        idx = self._tabs.currentIndex()
        if idx < self._tabs.count() - 1:
            self._tabs.setCurrentIndex(idx + 1)
