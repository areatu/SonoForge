"""Unit tests for presentation/ste_results_dialog.py."""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def dialog():
    from echo_personal_tool.presentation.ste_results_dialog import SteResultsDialog

    return SteResultsDialog()


class TestSteResultsDialogConstruction:
    def test_creates_with_widgets(self, dialog):
        assert dialog._strain_curve is not None
        assert dialog._segment_quality is not None
        assert dialog._warning_label is not None
        assert not dialog._warning_label.isVisible()

    def test_window_title(self, dialog):
        assert dialog.windowTitle() != ""

    def test_window_is_independent(self, dialog):
        from PySide6.QtCore import Qt

        assert bool(dialog.windowFlags() & Qt.WindowType.Window)


class TestUpdateResults:
    def test_sets_strain_data(self, dialog):
        long = np.array([0.0, -5.0, -10.0, -8.0])
        radial = np.array([0.0, 3.0, 6.0, 4.0])
        dialog.update_results(
            long,
            radial,
            segment_strain={1: -20.0, 2: -15.0},
            segment_quality={1: 0.8, 2: 0.7},
            gls=-18.0,
            ed_index=0,
            es_index=2,
        )
        # GLS label should be updated
        assert "18.0" in dialog._strain_curve._gls_label.text()

    def test_warning_shown_when_rejected_kernels(self, dialog):
        dialog.update_results(
            np.array([0.0, -5.0]),
            np.array([0.0, 3.0]),
            segment_strain={},
            segment_quality={},
            kernels_total=100,
            kernels_accepted=80,
            kernels_rejected=20,
        )
        assert dialog._warning_label.isVisible()
        assert "80/100" in dialog._warning_label.text()

    def test_warning_hidden_when_no_rejections(self, dialog):
        dialog.update_results(
            np.array([0.0, -5.0]),
            np.array([0.0, 3.0]),
            segment_strain={},
            segment_quality={},
            kernels_total=100,
            kernels_accepted=100,
            kernels_rejected=0,
        )
        assert not dialog._warning_label.isVisible()

    def test_warning_hidden_when_zero_total(self, dialog):
        dialog.update_results(
            np.array([0.0]),
            np.array([0.0]),
            segment_strain={},
            segment_quality={},
            kernels_total=0,
        )
        assert not dialog._warning_label.isVisible()

    def test_show_called_when_not_visible(self, dialog):
        assert not dialog.isVisible()
        with patch.object(dialog, "show") as mock_show:
            dialog.update_results(
                np.array([0.0, -5.0]),
                np.array([0.0, 3.0]),
                segment_strain={},
                segment_quality={},
            )
            mock_show.assert_called_once()


class TestClear:
    def test_clears_strain_curve_and_segments(self, dialog):
        # First set some data
        dialog.update_results(
            np.array([0.0, -5.0, -10.0]),
            np.array([0.0, 3.0, 6.0]),
            segment_strain={1: -20.0},
            segment_quality={1: 0.8},
        )
        dialog.clear()
        assert dialog._strain_curve._gls_label.text() == "GLS: --"
        assert dialog._strain_curve._ed_line is None
        assert dialog._strain_curve._es_line is None


from unittest.mock import patch
