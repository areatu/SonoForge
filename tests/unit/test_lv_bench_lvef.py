"""Tests for LVEF pairing helpers in Tier-1 bench evaluation."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.bench_lvef import (
    _compute_pair_lvef,
    _gold_frame_to_contour,
    _resolve_pixel_spacing,
)


class TestGoldFrameToContour:
    def test_builds_contour_from_gold_frame(self) -> None:
        gf = {
            "phase": "ED",
            "points": [[10, 20], [30, 40], [50, 20]],
            "mitral_annulus": [[10, 60], [50, 60]],
        }
        c = _gold_frame_to_contour(gf)
        assert c.phase == "ed"
        assert c.mitral_annulus is not None
        assert len(c.points) == 3
        assert c.source == "gold"
        assert c.review_pending is False

    def test_es_phase_lowercased(self) -> None:
        gf = {
            "phase": "ES",
            "points": [[0, 0], [10, 0], [10, 10]],
            "mitral_annulus": [[0, 15], [10, 15]],
        }
        c = _gold_frame_to_contour(gf)
        assert c.phase == "es"

    def test_no_annulus(self) -> None:
        gf = {
            "phase": "ED",
            "points": [[0, 0], [10, 0], [10, 10]],
        }
        c = _gold_frame_to_contour(gf)
        assert c.mitral_annulus is None
        assert c.is_open_arc is False


class TestResolvePixelSpacing:
    def test_prefers_gold_spacing(self, tmp_path: Path) -> None:
        gold = {"pixel_spacing_mm": [0.5, 0.5]}
        result = _resolve_pixel_spacing(gold, tmp_path / "dummy.dcm")
        assert result == (0.5, 0.5)

    def test_returns_none_when_no_gold_no_dicom(self, tmp_path: Path) -> None:
        gold = {}
        result = _resolve_pixel_spacing(gold, tmp_path / "nonexistent.dcm")
        assert result is None


class TestComputePairLvef:
    def test_returns_skip_when_spacing_none(self) -> None:
        result = _compute_pair_lvef(
            auto_ed=None,
            auto_es=None,
            gold_ed=None,
            gold_es=None,
            spacing=None,
        )
        assert result["lvef_skip_reason"] == "no_pixel_spacing"
        assert result["lvef_auto"] is None
        assert result["lvef_gold"] is None
        assert result["lvef_delta"] is None

    def test_returns_skip_when_auto_contours_missing(self) -> None:
        result = _compute_pair_lvef(
            auto_ed=None,
            auto_es=None,
            gold_ed=Contour(phase="ed", points=[(0, 0), (10, 0), (10, 10)]),
            gold_es=Contour(phase="es", points=[(0, 0), (5, 0), (5, 5)]),
            spacing=(1.0, 1.0),
        )
        assert result["lvef_skip_reason"] == "missing_auto"
        assert result["lvef_auto"] is None

    def test_returns_skip_when_gold_contours_missing(self) -> None:
        auto_ed = Contour(
            phase="ed",
            points=[(0, 0), (20, 0), (20, 30)],
            mitral_annulus=((0, 0), (20, 0)),
        )
        auto_es = Contour(
            phase="es",
            points=[(0, 0), (10, 0), (10, 15)],
            mitral_annulus=((0, 0), (10, 0)),
        )
        result = _compute_pair_lvef(
            auto_ed=auto_ed,
            auto_es=auto_es,
            gold_ed=None,
            gold_es=None,
            spacing=(1.0, 1.0),
        )
        assert result["lvef_skip_reason"] == "missing_gold"
