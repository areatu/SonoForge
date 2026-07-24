"""Unit tests for frame panel parser."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.frame_panels import PanelKind
from echo_personal_tool.domain.services.frame_panel_parser import (
    _panel_kind,
    detect_panels_heuristic,
)


class TestPanelKind:
    def test_m_mode(self) -> None:
        assert _panel_kind(2, 0) is PanelKind.M_MODE

    def test_spectral_doppler(self) -> None:
        assert _panel_kind(3, 0) is PanelKind.DOPPLER

    def test_b_mode_2d(self) -> None:
        assert _panel_kind(1, 1) is PanelKind.B_MODE

    def test_b_mode_2d_no_data_type(self) -> None:
        assert _panel_kind(1, 0) is PanelKind.B_MODE

    def test_doppler_data_type(self) -> None:
        assert _panel_kind(0, 3) is PanelKind.DOPPLER

    def test_unknown_returns_none(self) -> None:
        assert _panel_kind(0, 0) is None


class TestDetectPanelsHeuristic:
    def test_returns_none_for_3d_image(self) -> None:
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        assert detect_panels_heuristic(img) is None

    def test_returns_none_for_small_image(self) -> None:
        img = np.zeros((50, 50), dtype=np.uint8)
        assert detect_panels_heuristic(img) is None

    def test_returns_layout_for_composite_image(self) -> None:
        img = np.zeros((200, 300), dtype=np.uint8)
        result = detect_panels_heuristic(img)
        assert result is not None
        assert len(result.panels) == 2
        assert result.panels[0].kind is PanelKind.B_MODE

    def test_wide_lower_strip_is_mmode(self) -> None:
        # Very wide lower strip → M-mode
        img = np.zeros((200, 800), dtype=np.uint8)
        result = detect_panels_heuristic(img)
        assert result is not None
        assert result.panels[1].kind is PanelKind.M_MODE

    def test_wide_lower_strip_is_mmode(self) -> None:
        # Wide image → lower aspect > 4 → M-mode
        img = np.zeros((200, 500), dtype=np.uint8)
        result = detect_panels_heuristic(img)
        assert result is not None
        assert result.panels[1].kind is PanelKind.M_MODE

    def test_both_panels_present(self) -> None:
        img = np.zeros((200, 300), dtype=np.uint8)
        result = detect_panels_heuristic(img)
        assert result is not None
        assert len(result.panels) == 2
        kinds = {p.kind for p in result.panels}
        assert PanelKind.B_MODE in kinds
