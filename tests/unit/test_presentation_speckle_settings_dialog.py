"""Unit tests for presentation/speckle_settings_dialog.py."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSpeckleSettingsDialogConstruction:
    def test_creates_with_defaults(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        assert dlg.windowTitle() != ""
        assert dlg._preset_combo.count() == 3
        assert dlg._drift_compensation_check.isChecked()
        assert dlg._wall_thickness_spin.value() == 8.0

    def test_ed_auto_checked_when_no_manual(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog(current_frame=5, n_frames=10)
        assert dlg._ed_auto_check.isChecked()
        assert not dlg._ed_spin.isEnabled()
        assert dlg._ed_spin.value() == 5

    def test_es_auto_checked_when_no_manual(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog(current_frame=5, n_frames=10)
        assert dlg._es_auto_check.isChecked()
        assert not dlg._es_spin.isEnabled()

    def test_manual_ed_sets_spin_and_disables_auto(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog(manual_ed=7, n_frames=10)
        assert not dlg._ed_auto_check.isChecked()
        assert dlg._ed_spin.isEnabled()
        assert dlg._ed_spin.value() == 7

    def test_manual_es_sets_spin_and_disables_auto(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog(manual_es=3, n_frames=10)
        assert not dlg._es_auto_check.isChecked()
        assert dlg._es_spin.isEnabled()
        assert dlg._es_spin.value() == 3


class TestSelectedPresetName:
    def test_standard_default(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        assert dlg.selected_preset_name() == "standard"

    def test_research_preset(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        dlg._preset_combo.setCurrentIndex(1)
        assert dlg.selected_preset_name() == "research"

    def test_debug_preset(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        dlg._preset_combo.setCurrentIndex(2)
        assert dlg.selected_preset_name() == "debug"


class TestManualEdEs:
    def test_auto_checked_returns_none(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog(n_frames=10)
        assert dlg.manual_ed is None
        assert dlg.manual_es is None

    def test_manual_ed_unchecked_returns_value(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog(n_frames=10)
        dlg._ed_auto_check.setChecked(False)
        assert dlg.manual_ed == 0

    def test_manual_es_unchecked_returns_value(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog(n_frames=10)
        dlg._es_auto_check.setChecked(False)
        assert dlg.manual_es == 0


class TestGetConfig:
    def test_standard_preset_config(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        config = dlg.get_config()
        assert config.drift_compensation is True
        assert config.wall_thickness_mm == 8.0

    def test_drift_compensation_off(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        dlg._drift_compensation_check.setChecked(False)
        config = dlg.get_config()
        assert config.drift_compensation is False

    def test_wall_thickness_override(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        dlg._wall_thickness_spin.setValue(10.5)
        config = dlg.get_config()
        assert config.wall_thickness_mm == 10.5

    def test_research_preset(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        dlg._preset_combo.setCurrentIndex(1)
        config = dlg.get_config()
        # Research has different defaults, just check it's a valid config
        assert hasattr(config, "kernel_size")
        assert config.kernel_size == 18

    def test_debug_preset(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        dlg._preset_combo.setCurrentIndex(2)
        config = dlg.get_config()
        assert config.bidirectional is False


class TestAutoToggleEdEs:
    def test_toggle_ed_auto_disables_spin(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog(n_frames=10)
        dlg._ed_auto_check.setChecked(True)
        assert not dlg._ed_spin.isEnabled()
        dlg._ed_auto_check.setChecked(False)
        assert dlg._ed_spin.isEnabled()

    def test_toggle_es_auto_disables_spin(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog(n_frames=10)
        dlg._es_auto_check.setChecked(True)
        assert not dlg._es_spin.isEnabled()
        dlg._es_auto_check.setChecked(False)
        assert dlg._es_spin.isEnabled()


class TestFrameRange:
    def test_n_frames_sets_spin_range(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog(n_frames=20)
        assert dlg._ed_spin.maximum() == 19
        assert dlg._es_spin.maximum() == 19


class TestRegularizationAndSideControls:
    """User-controllable regularization and the side declaration (Voigt 2015).

    The consensus requires the amount of regularization to be under the user's
    control and the side/inversion convention to be selectable — both must reach
    the analysis, not just the dialog.
    """

    def test_curve_smoothing_window_defaults_to_the_preset_value(self):
        from echo_personal_tool.domain.models.speckle import SpeckleConfig
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        assert dlg._curve_smoothing_spin.value() == SpeckleConfig.preset_standard().curve_smoothing_frames
        assert dlg.get_config().curve_smoothing_frames == SpeckleConfig.preset_standard().curve_smoothing_frames

    def test_curve_smoothing_window_flows_into_config(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        dlg._curve_smoothing_spin.setValue(15)
        assert dlg.get_config().curve_smoothing_frames == 15

    def test_segment_flip_is_off_by_default_and_flows_into_config(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        assert dlg.get_config().segment_flip is False
        dlg._segment_flip_check.setChecked(True)
        assert dlg.get_config().segment_flip is True

    def test_research_preset_keeps_the_user_window(self):
        from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog

        dlg = SpeckleSettingsDialog()
        dlg._curve_smoothing_spin.setValue(5)
        dlg._preset_combo.setCurrentIndex(1)  # research
        config = dlg.get_config()
        assert config.curve_smoothing_frames == 5
        assert config.spatial_smoothing == 1.2  # preset still applied
