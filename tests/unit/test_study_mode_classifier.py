"""Unit tests for domain/services/study_mode_classifier.py."""

from __future__ import annotations

from echo_personal_tool.domain.services.study_mode_classifier import (
    MODE_2D,
    MODE_COLOR,
    MODE_CW,
    MODE_M,
    MODE_ORDER,
    MODE_PW,
    classify_region_items,
    mode_for_region,
)


class TestModeForRegion:
    def test_bmode_tissue(self) -> None:
        assert mode_for_region(1, 1) == MODE_2D

    def test_color_flow(self) -> None:
        assert mode_for_region(1, 2) == MODE_COLOR

    def test_m_mode_tissue_and_color(self) -> None:
        assert mode_for_region(2, 1) == MODE_M
        assert mode_for_region(2, 2) == MODE_M

    def test_spectral_pw_and_cw(self) -> None:
        assert mode_for_region(3, 3) == MODE_PW
        assert mode_for_region(3, 4) == MODE_CW

    def test_samsung_mistagged_doppler(self) -> None:
        # Samsung RS85 writes spectral/tissue Doppler as SF=1 regions.
        assert mode_for_region(1, 3) == MODE_PW
        assert mode_for_region(1, 4) == MODE_CW
        assert mode_for_region(1, 0x10) == MODE_PW
        assert mode_for_region(1, 0x11) == MODE_PW

    def test_unknown_region_is_ignored(self) -> None:
        assert mode_for_region(0, 0) is None
        assert mode_for_region(9, 9) is None


class TestClassifyRegionItems:
    def test_empty(self) -> None:
        assert classify_region_items(None) == frozenset()
        assert classify_region_items([]) == frozenset()

    def test_dicom_json_items(self) -> None:
        items = [
            {"00186012": {"vr": "US", "Value": [1]}, "00186014": {"vr": "US", "Value": [1]}},
            {"00186012": {"vr": "US", "Value": [1]}, "00186014": {"vr": "US", "Value": [2]}},
            {"00186012": {"vr": "US", "Value": [3]}, "00186014": {"vr": "US", "Value": [4]}},
        ]
        modes = classify_region_items(items)
        assert modes == frozenset({MODE_2D, MODE_COLOR, MODE_CW})

    def test_merges_duplicate_regions(self) -> None:
        item = {"00186012": {"vr": "US", "Value": [2]}, "00186014": {"vr": "US", "Value": [1]}}
        modes = classify_region_items([item, dict(item)])
        assert modes == frozenset({MODE_M})

    def test_plain_scalar_items_supported(self) -> None:
        assert classify_region_items([{"00186012": 3, "00186014": 3}]) == frozenset({MODE_PW})

    def test_mode_order_covers_all_labels(self) -> None:
        assert set(MODE_ORDER) == {MODE_2D, MODE_COLOR, MODE_M, MODE_PW, MODE_CW}
