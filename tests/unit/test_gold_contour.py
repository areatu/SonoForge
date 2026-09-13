"""Unit tests for gold-contour dataclass + I/O helpers (§11.2 п.1)."""

from __future__ import annotations

import dataclasses
import json
import pathlib

import numpy as np
import pytest

from echo_personal_tool.ui.ste import gold_contour as gc


class _K:
    def __init__(self, layer: str):
        self.layer = layer


class _FakeStrainResult:
    def __init__(self, positions, kernels, view: str = "A4C", ed_index: int = 0):
        self.tracked_ed_positions = np.asarray(positions, dtype=float)
        self.kernels = kernels
        self.view = view
        self.ed_index = ed_index
        self.fps = 50.0
        self.global_longitudinal_strain_percent = -20.0


def test_roundtrip(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gc, "GOLD_DIR", tmp_path)
    pts = [[10.0 * i, 50.0 + np.sin(i / 4) * 20] for i in range(25)]
    # 25 endo kernels -> contour_from_result picks those positions
    kernels = [_K("endo") for _ in range(25)]
    result = _FakeStrainResult(positions=pts, kernels=kernels, view="A4C", ed_index=3)

    contour = gc.contour_from_result(
        result,
        view="A4C",
        study_uid="1.2.3.4",
        sop_instance_uid="1.2.3.4.5",
        pixel_spacing_mm=(0.3, 0.3),
    )
    assert contour.view == "A4C"
    assert contour.frame_index == 3
    np.testing.assert_allclose(contour.points, pts, atol=1e-9)

    path = contour.save(source_path="/tmp/foo.dcm")
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["study_id"] == "1.2.3.4"
    assert data["chamber"] == "LV"
    assert data["instance_path"] == "/tmp/foo.dcm"
    assert len(data["frames"][0]["points"]) == 25
    assert data["frames"][0]["phase"] == "ED"

    default = gc.default_path_for("1.2.3.4", "A4C")
    assert default.name.startswith("lv_") and default.suffix == ".json"

    loaded = gc.load_for(default)
    assert loaded is not None
    assert loaded.study_id == "1.2.3.4"
    assert loaded.frame_index == 3
    np.testing.assert_allclose(loaded.points, pts, atol=1e-9)

    loaded2 = gc.GoldContour.from_dict(json.loads(path.read_text()))
    assert dataclasses.asdict(loaded).keys() == dataclasses.asdict(loaded2).keys()


def test_load_missing_returns_none(tmp_path: pathlib.Path) -> None:
    assert gc.load_for(tmp_path / "missing.json") is None
