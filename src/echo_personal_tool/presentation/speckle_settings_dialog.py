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
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.speckle import SpeckleConfig
from echo_personal_tool.domain.services.burned_ecg_mask import (
    get_burned_ecg_override,
    store_burned_ecg_override,
)
from echo_personal_tool.domain.services.phase_source import get_forced_phase_source
from echo_personal_tool.presentation.scroll_policy import protect_spinboxes
from echo_personal_tool.presentation.styled_dialogs import localize_dialog_button_box, theme_button_box_icons


def phase_source_label(source: str) -> str:
    """Human word for an ED/ES route («ecg» → «ЭКГ»); unknown stays raw.

    The А.4 indicator must be honest even for a source this build does not
    know (forward compatibility), so an untranslated key falls back to the
    raw route string rather than a placeholder.
    """
    route = str(source or "").strip().lower()
    if not route:
        return "—"
    label = tr(f"phase.gating.{route}")
    return route if label == f"phase.gating.{route}" else label


def ste_phase_gating_hint(last_result: object) -> str:
    """Settings-dialog hint: the last honest route, or the А.4 doctrine.

    Shows what actually gated the previous run (the router decides per clip
    and reports why) instead of a static source chain.
    """
    source = getattr(last_result, "ed_es_source", None)
    if isinstance(source, str) and source:
        return tr("status.phase_gating_last", source=phase_source_label(source))
    return tr("dialog.speckle_settings.phase_source_hint_auto")


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
        ed_es_hint: str | None = None,
        initial_view: str = "A4C",
        phase_source_pref: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.speckle_settings.title"))

        self._preset_combo = QComboBox(self)
        self._preset_combo.addItem("Standard", "standard")
        self._preset_combo.addItem("Research", "research")
        self._preset_combo.addItem("Debug", "debug")

        self._mode_combo = QComboBox(self)
        self._mode_combo.addItem("Sequential (frame-to-frame)", "sequential")
        self._mode_combo.addItem("Incremental (ED-anchored, legacy)", "incremental")
        self._mode_combo.addItem("Bidirectional (ED-anchored, legacy)", "bidirectional")

        # Position (echo view) the contours were drawn on: A4C / A2C / A3C
        self._view_combo = QComboBox(self)
        self._view_combo.addItem("A4C", "A4C")
        self._view_combo.addItem("A2C", "A2C")
        self._view_combo.addItem(tr("strain.position_a3c"), "A3C")
        idx = self._view_combo.findData(initial_view.upper())
        if idx >= 0:
            self._view_combo.setCurrentIndex(idx)

        self._segment_flip_check = QCheckBox(self)
        self._segment_flip_check.setToolTip(tr("dialog.speckle_settings.segment_flip_hint"))

        self._drift_compensation_check = QCheckBox(self)
        self._drift_compensation_check.setChecked(True)
        self._global_motion_check = QCheckBox(self)
        self._global_motion_check.setChecked(True)

        self._wall_thickness_spin = QDoubleSpinBox(self)
        # 25 mm is the upper bound the geometry check accepts. Commercial STE
        # packages cap the *default* band at 5-10 mm, but a hypertrophied or
        # sigmoid wall needs more — with a thinner band only part of the
        # myocardium is measured, and that part is what limits the strain.
        self._wall_thickness_spin.setRange(5.0, 25.0)
        self._wall_thickness_spin.setSingleStep(0.5)
        self._wall_thickness_spin.setDecimals(1)
        self._wall_thickness_spin.setSuffix(" mm")
        self._wall_thickness_spin.setValue(8.0)
        self._wall_thickness_spin.setToolTip(
            "Thickness of the automatically generated epicardial contour.\n"
            "Focal hypertrophy (e.g. a sigmoid basal septum) is handled by "
            "dragging the epicardial contour nodes locally: the drawn "
            "epicardium defines the measured zone node by node."
        )

        # User-controllable regularization (Voigt 2015): the temporal
        # Savitzky-Golay window applied to the strain curves before ESS/TTP/peak
        # are read. 1 disables the filter; even values are made odd by the
        # filter itself. The window actually applied is declared in the report.
        self._curve_smoothing_spin = QSpinBox(self)
        self._curve_smoothing_spin.setRange(1, 31)
        self._curve_smoothing_spin.setSingleStep(2)
        self._curve_smoothing_spin.setSuffix(" " + tr("dialog.speckle_settings.frames"))
        self._curve_smoothing_spin.setValue(int(SpeckleConfig.preset_standard().curve_smoothing_frames))
        self._curve_smoothing_spin.setToolTip(tr("dialog.speckle_settings.curve_smoothing_hint"))

        self._ed_spin = QSpinBox(self)
        self._ed_spin.setRange(0, max(0, n_frames - 1))
        self._ed_spin.setSuffix(f" / {n_frames - 1}" if n_frames > 0 else "")
        self._ed_spin.setValue(manual_ed if manual_ed is not None else current_frame)
        self._ed_auto_check = QCheckBox(tr("dialog.speckle_settings.auto_ed"))
        self._ed_auto_check.setChecked(manual_ed is None)
        self._ed_spin.setEnabled(manual_ed is not None)

        self._es_spin = QSpinBox(self)
        self._es_spin.setRange(0, max(0, n_frames - 1))
        self._es_spin.setSuffix(f" / {n_frames - 1}" if n_frames > 0 else "")
        self._es_spin.setValue(manual_es if manual_es is not None else current_frame)
        self._es_auto_check = QCheckBox(tr("dialog.speckle_settings.auto_es"))
        self._es_auto_check.setChecked(manual_es is None)
        self._es_spin.setEnabled(manual_es is not None)

        self._ed_auto_check.toggled.connect(lambda checked: self._ed_spin.setEnabled(not checked))
        self._es_auto_check.toggled.connect(lambda checked: self._es_spin.setEnabled(not checked))

        # А.4 phase gating (issue #642): which source resolves ED/ES when the
        # anchors are not pinned manually. "auto" = prefer ECG tags, else the
        # image phase field; "ecg"/"image" pin the route (a pinned route that
        # cannot run falls back honestly and is reported in the hint).
        self._phase_source_combo = QComboBox(self)
        self._phase_source_combo.addItem(tr("dialog.speckle_settings.phase_source_auto"), "auto")
        self._phase_source_combo.addItem(tr("dialog.speckle_settings.phase_source_ecg"), "ecg")
        self._phase_source_combo.addItem(tr("dialog.speckle_settings.phase_source_image"), "image")
        # No explicit pref → the session store (the dialog owns the memory).
        pref_index = self._phase_source_combo.findData(
            str(phase_source_pref or get_forced_phase_source() or "auto").lower()
        )
        if pref_index >= 0:
            self._phase_source_combo.setCurrentIndex(pref_index)

        form = QFormLayout()
        form.addRow(tr("strain.position") + ":", self._view_combo)
        form.addRow(tr("dialog.speckle_settings.preset"), self._preset_combo)
        form.addRow(tr("dialog.speckle_settings.tracking_mode"), self._mode_combo)
        form.addRow(tr("dialog.speckle_settings.curve_smoothing") + ":", self._curve_smoothing_spin)
        form.addRow(tr("dialog.speckle_settings.drift_compensation"), self._drift_compensation_check)
        form.addRow(tr("dialog.speckle_settings.global_motion"), self._global_motion_check)
        form.addRow(tr("dialog.speckle_settings.wall_thickness"), self._wall_thickness_spin)
        form.addRow(tr("dialog.speckle_settings.segment_flip") + ":", self._segment_flip_check)
        form.addRow(self._ed_auto_check)
        form.addRow(tr("dialog.speckle_settings.ed_frame"), self._ed_spin)
        form.addRow(self._es_auto_check)
        form.addRow(tr("dialog.speckle_settings.es_frame"), self._es_spin)
        form.addRow(tr("dialog.speckle_settings.phase_source") + ":", self._phase_source_combo)

        # А.5 burned-ECG strip mask (issue #643): «auto» subtracts a detected
        # vendor strip from the phase signals and the tracking domain; «off»
        # is the user's override for a clip where the strip is not there (or
        # must not be excluded).  Unlike the force-source combo, the choice is
        # written to the session store *immediately*: the mask also serves the
        # playback phase strip (outside this dialog's accept), and an override
        # that silently reverted on cancel would be dishonest.
        self._burned_ecg_combo = QComboBox(self)
        self._burned_ecg_combo.addItem(tr("dialog.speckle_settings.burned_ecg_auto"), "auto")
        self._burned_ecg_combo.addItem(tr("dialog.speckle_settings.burned_ecg_off"), "off")
        store_index = self._burned_ecg_combo.findData(str(get_burned_ecg_override() or "auto").lower())
        if store_index >= 0:
            self._burned_ecg_combo.setCurrentIndex(store_index)
        self._burned_ecg_combo.currentIndexChanged.connect(
            lambda _index: store_burned_ecg_override(str(self._burned_ecg_combo.currentData() or "auto"))
        )
        form.addRow(tr("dialog.speckle_settings.burned_ecg") + ":", self._burned_ecg_combo)

        self._source_hint_label = QLabel(ed_es_hint or "")
        self._source_hint_label.setWordWrap(True)
        self._source_hint_label.setStyleSheet(
            "QLabel { color: #90caf9; background: #12283f; padding: 4px 8px; border-radius: 4px; font-size: 11px; }"
        )
        if ed_es_hint:
            form.addRow(self._source_hint_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        localize_dialog_button_box(buttons)
        theme_button_box_icons(buttons)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        protect_spinboxes(self)

    def selected_preset_name(self) -> str:
        return str(self._preset_combo.currentData())

    def selected_view(self) -> str:
        """Position (A4C/A2C/A3C) the user will draw contours on."""
        return str(self._view_combo.currentData())

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

    @property
    def phase_source_pref(self) -> str:
        """The А.4 force-source choice: "auto" | "ecg" | "image"."""
        return str(self._phase_source_combo.currentData() or "auto")

    @property
    def burned_ecg_mask_pref(self) -> str:
        """The А.5 strip-mask override: "auto" | "off"."""
        return str(self._burned_ecg_combo.currentData() or "auto")

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
            global_motion_compensation=self._global_motion_check.isChecked(),
            wall_thickness_mm=float(self._wall_thickness_spin.value()),
            tracking_mode=str(self._mode_combo.currentData()),
            curve_smoothing_frames=int(self._curve_smoothing_spin.value()),
            segment_flip=self._segment_flip_check.isChecked(),
        )


def speckle_ed_es_hint(pins: tuple[bool, bool, bool, bool], *, last_result: object) -> str:
    """The hint above the ED/ES controls: what gated the last run.

    ``pins`` is ``(ed_from_contour, es_from_contour, ed_pinned, es_pinned)``:
    pinned anchors always report themselves; otherwise the honest route of
    the previous run (the А.4 router decides per clip and reports why);
    before any run the А.4 doctrine line is shown.
    """
    ed_from_contour, es_from_contour, ed_pinned, es_pinned = pins
    if ed_from_contour and es_from_contour:
        return "Manual — from EDV/ESV contours"
    if ed_from_contour:
        return "ED pinned from EDV contour; ES auto-detected"
    if es_from_contour:
        return "ES pinned from ESV contour; ED auto-detected"
    if ed_pinned and es_pinned:
        return "Manual frames (auto-detect disabled)"
    source = getattr(last_result, "ed_es_source", None)
    if isinstance(source, str) and source:
        return tr("status.phase_gating_last", source=phase_source_label(source))
    return tr("dialog.speckle_settings.phase_source_hint_auto")
