"""Tests for frame_panel_parser module."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.frame_panels import PanelKind
from echo_personal_tool.domain.services.frame_panel_parser import (
    _bounds_to_roi,
    _panel_kind,
    detect_panels_heuristic,
)


class TestBoundsToRoi:
    def test_basic(self):
        roi = _bounds_to_roi(10.0, 20.0, 50.0, 60.0)
        assert roi.x0 == 10.0
        assert roi.y0 == 20.0
        assert roi.width == 40.0
        assert roi.height == 40.0

    def test_min_width_height(self):
        roi = _bounds_to_roi(10.0, 10.0, 10.0, 10.0)
        assert roi.width == 1.0
        assert roi.height == 1.0


class TestPanelKind:
    def test_m_mode(self):
        assert _panel_kind(2, 0) == PanelKind.M_MODE

    def test_spectral_format(self):
        assert _panel_kind(3, 0) == PanelKind.DOPPLER

    def test_doppler_data_type(self):
        assert _panel_kind(1, 3) == PanelKind.DOPPLER

    def test_b_mode_data_type_1(self):
        assert _panel_kind(1, 1) == PanelKind.B_MODE

    def test_b_mode_default(self):
        assert _panel_kind(1, 0) == PanelKind.B_MODE

    def test_unknown_returns_none(self):
        assert _panel_kind(0, 0) is None


class TestDetectPanelsHeuristic:
    def test_3d_input(self):
        rgb = np.zeros((200, 300, 3), dtype=np.uint8)
        assert detect_panels_heuristic(rgb) is None

    def test_small_image(self):
        small = np.zeros((40, 40), dtype=np.uint8)
        assert detect_panels_heuristic(small) is None

    def test_wide_strip_m_mode(self):
        """Very wide lower strip should be classified as M-mode."""
        gray = np.zeros((200, 400), dtype=np.uint8)
        layout = detect_panels_heuristic(gray)
        assert layout is not None
        assert len(layout.panels) == 2
        assert layout.panels[0].kind == PanelKind.B_MODE
        assert layout.panels[1].kind == PanelKind.M_MODE

    def test_lower_strip_always_m_mode_due_to_bounds(self):
        """Lower strip has height=1 due to _bounds_to_roi(y1=height-split_y), so aspect > 4 → M_MODE."""
        gray = np.zeros((200, 120), dtype=np.uint8)
        layout = detect_panels_heuristic(gray)
        assert layout is not None
        assert layout.panels[1].kind == PanelKind.M_MODE

    def test_valid_layout_bounds(self):
        gray = np.zeros((200, 300), dtype=np.uint8)
        layout = detect_panels_heuristic(gray)
        assert layout is not None
        upper = layout.panels[0].bounds
        lower = layout.panels[1].bounds
        assert upper.y0 == 0.0
        assert upper.y1 == pytest.approx(lower.y0, abs=1.0)

    def test_height_too_small(self):
        gray = np.zeros((70, 200), dtype=np.uint8)
        assert detect_panels_heuristic(gray) is None
