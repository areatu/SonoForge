"""Acceptance: open DICOM → speckle tracking → view strain curves."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = [pytest.mark.gui, pytest.mark.acceptance]


class TestStrainWorkflow:
    def test_mock_speckle_worker_track(self, mock_speckle_worker) -> None:
        """Mock speckle worker produces tracking results."""
        tracking = mock_speckle_worker.track()
        assert tracking.displacements.shape[0] > 0
        assert tracking.ncc_scores.shape == tracking.displacements.shape[:2]

    def test_mock_speckle_worker_compute_strain(self, mock_speckle_worker) -> None:
        """Mock speckle worker produces strain results."""
        strain = mock_speckle_worker.compute_strain()
        assert strain.longitudinal.shape[0] > 0
        assert strain.radial.shape[0] > 0
        assert isinstance(strain.gls, float)

    def test_gls_is_negative_for_normal_heart(self, mock_speckle_worker) -> None:
        """GLS should be negative (shortening) for a normal heart mock."""
        strain = mock_speckle_worker.compute_strain()
        assert strain.gls < 0

    def test_strain_result_has_valid_indices(self, mock_speckle_worker) -> None:
        """Strain result ED/ES indices are within the longitudinal array range."""
        strain = mock_speckle_worker.compute_strain()
        n_frames = len(strain.longitudinal)
        assert 0 <= strain.ed_index < n_frames
        assert 0 <= strain.es_index < n_frames
        assert strain.ed_index <= strain.es_index

    def test_speckle_config_presets(self) -> None:
        """SpeckleConfig presets produce valid configurations."""
        from echo_personal_tool.domain.models.speckle import SpeckleConfig

        standard = SpeckleConfig.preset_standard()
        assert standard.kernel_size > 0
        assert standard.search_radius > 0
        assert standard.ncc_threshold > 0

        research = SpeckleConfig.preset_research()
        assert research.kernel_size >= standard.kernel_size

        debug = SpeckleConfig.preset_debug()
        assert debug.bidirectional is False
        assert debug.spatial_smoothing == 0.0

    def test_strain_result_dataclass_fields(self, mock_speckle_worker) -> None:
        """StrainResult has expected fields populated."""
        strain = mock_speckle_worker.compute_strain()
        assert hasattr(strain, "longitudinal")
        assert hasattr(strain, "radial")
        assert hasattr(strain, "gls")
        assert hasattr(strain, "ed_index")
        assert hasattr(strain, "es_index")

    def test_tracking_kernel_positions_match_kernels(self, mock_speckle_worker) -> None:
        """Tracking result kernel positions have correct shape."""
        tracking = mock_speckle_worker.track()
        n_kernels = tracking.kernel_positions.shape[0]
        assert n_kernels > 0
        assert tracking.kernel_positions.shape[1] == 2

    def test_strain_widget_standalone(self, qtbot, qapp) -> None:
        """StrainCurveWidget can be created and shown."""
        from echo_personal_tool.presentation.strain_curve_widget import StrainCurveWidget

        widget = StrainCurveWidget()
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)
        assert widget.isVisible()
