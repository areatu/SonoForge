"""Unit tests for bench_lvef (private helpers for LVEF bench evaluation)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.bench_lvef import (
    _compute_pair_lvef,
    _gold_frame_to_contour,
    _resolve_pixel_spacing,
)


# ── _gold_frame_to_contour ─────────────────────────────────────────


class TestGoldFrameToContour:
    def test_basic_conversion(self) -> None:
        frame: dict[str, Any] = {
            "phase": "ED",
            "points": [[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
        }
        contour = _gold_frame_to_contour(frame)
        assert isinstance(contour, Contour)
        assert contour.phase == "ed"
        assert contour.points == [(10.0, 20.0), (30.0, 40.0), (50.0, 60.0)]
        assert contour.source == "gold"
        assert contour.view == "A4C"
        assert contour.chamber == "LV"
        assert contour.num_nodes == 3

    def test_with_mitral_annulus(self) -> None:
        frame: dict[str, Any] = {
            "phase": "ES",
            "points": [[10.0, 20.0], [30.0, 40.0]],
            "mitral_annulus": [[5.0, 10.0], [35.0, 45.0]],
        }
        contour = _gold_frame_to_contour(frame)
        assert contour.mitral_annulus == ((5.0, 10.0), (35.0, 45.0))

    def test_no_mitral_annulus(self) -> None:
        frame: dict[str, Any] = {
            "phase": "ED",
            "points": [[10.0, 20.0]],
        }
        contour = _gold_frame_to_contour(frame)
        assert contour.mitral_annulus is None

    def test_mitral_annulus_none(self) -> None:
        frame: dict[str, Any] = {
            "phase": "ED",
            "points": [[10.0, 20.0]],
            "mitral_annulus": None,
        }
        contour = _gold_frame_to_contour(frame)
        assert contour.mitral_annulus is None

    def test_phase_lowercased(self) -> None:
        frame: dict[str, Any] = {"phase": "ED", "points": [[0.0, 0.0]]}
        contour = _gold_frame_to_contour(frame)
        assert contour.phase == "ed"


# ── _resolve_pixel_spacing ─────────────────────────────────────────


class TestResolvePixelSpacing:
    def test_from_gold_dict(self) -> None:
        gold = {"pixel_spacing_mm": [0.4, 0.4]}
        result = _resolve_pixel_spacing(gold, Path("/nonexistent.dcm"))
        assert result == (0.4, 0.4)

    def test_from_gold_dict_asymmetric(self) -> None:
        gold = {"pixel_spacing_mm": [0.3, 0.5]}
        result = _resolve_pixel_spacing(gold, Path("/nonexistent.dcm"))
        assert result == (0.3, 0.5)

    def test_gold_zero_spacing_ignored(self) -> None:
        gold = {"pixel_spacing_mm": [0.0, 0.5]}
        result = _resolve_pixel_spacing(gold, Path("/nonexistent.dcm"))
        assert result is None

    def test_gold_missing_key(self) -> None:
        gold: dict[str, Any] = {}
        result = _resolve_pixel_spacing(gold, Path("/nonexistent.dcm"))
        assert result is None

    def test_gold_wrong_length(self) -> None:
        gold = {"pixel_spacing_mm": [0.4]}
        result = _resolve_pixel_spacing(gold, Path("/nonexistent.dcm"))
        assert result is None

    def test_fallback_to_dicom(self) -> None:
        gold: dict[str, Any] = {}
        mock_meta = MagicMock()
        mock_meta.pixel_spacing = (0.5, 0.5)
        mock_reader = MagicMock()
        mock_reader.read_metadata.return_value = mock_meta

        fake_path = Path("/fake.dcm")
        with (
            patch("echo_personal_tool.infrastructure.dicom_reader.DicomReaderImpl", return_value=mock_reader),
            patch.object(Path, "is_file", return_value=True),
        ):
            result = _resolve_pixel_spacing(gold, fake_path)
            assert result == (0.5, 0.5)

    def test_dicom_read_failure(self) -> None:
        gold: dict[str, Any] = {}
        mock_reader = MagicMock()
        mock_reader.read_metadata.side_effect = RuntimeError("bad file")

        fake_path = Path("/fake.dcm")
        with (
            patch("echo_personal_tool.infrastructure.dicom_reader.DicomReaderImpl", return_value=mock_reader),
            patch.object(Path, "is_file", return_value=True),
        ):
            result = _resolve_pixel_spacing(gold, fake_path)
            assert result is None


# ── _compute_pair_lvef ─────────────────────────────────────────────


class TestComputePairLvef:
    def _make_contour(self, phase: str, points: list[tuple[float, float]] | None = None) -> Contour:
        pts = points or [(10.0, 20.0), (30.0, 40.0), (50.0, 60.0)]
        return Contour(phase=phase, view="A4C", chamber="LV", points=pts, num_nodes=len(pts))

    def test_no_spacing(self) -> None:
        result = _compute_pair_lvef(
            self._make_contour("ed"), self._make_contour("es"),
            self._make_contour("ed"), self._make_contour("es"),
            spacing=None,
        )
        assert result["lvef_skip_reason"] == "no_pixel_spacing"
        assert result["lvef_auto"] is None

    def test_missing_auto(self) -> None:
        result = _compute_pair_lvef(
            None, self._make_contour("es"),
            self._make_contour("ed"), self._make_contour("es"),
            spacing=(0.5, 0.5),
        )
        assert result["lvef_skip_reason"] == "missing_auto"

    def test_missing_gold(self) -> None:
        result = _compute_pair_lvef(
            self._make_contour("ed"), self._make_contour("es"),
            None, self._make_contour("es"),
            spacing=(0.5, 0.5),
        )
        assert result["lvef_skip_reason"] == "missing_gold"

    def test_successful_computation(self) -> None:
        ed = self._make_contour("ed", [(10.0, 10.0), (50.0, 10.0), (50.0, 50.0), (10.0, 50.0)])
        es = self._make_contour("es", [(15.0, 15.0), (45.0, 15.0), (45.0, 45.0), (15.0, 45.0)])
        result = _compute_pair_lvef(ed, es, ed, es, spacing=(0.5, 0.5))
        assert result["lvef_skip_reason"] is None
        assert result["lvef_auto"] is not None
        assert result["lvef_gold"] is not None
        assert result["lvef_delta"] is not None

    def test_result_keys(self) -> None:
        ed = self._make_contour("ed", [(10.0, 10.0), (50.0, 10.0), (50.0, 50.0), (10.0, 50.0)])
        es = self._make_contour("es", [(15.0, 15.0), (45.0, 15.0), (45.0, 45.0), (15.0, 45.0)])
        result = _compute_pair_lvef(ed, es, ed, es, spacing=(0.5, 0.5))
        assert "lvef_auto" in result
        assert "lvef_gold" in result
        assert "lvef_delta" in result
        assert "lvef_skip_reason" in result
