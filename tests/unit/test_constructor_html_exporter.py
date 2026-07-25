"""Tests for exporters/html_exporter.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.constructor.exporters.html_exporter import (
    _embed_image,
    _format_norm,
    _mime,
    export_to_html,
)
from echo_personal_tool.constructor.models import (
    GradationModel,
    NormRangeModel,
    ParameterModel,
    PathologyModel,
    ReferenceModel,
    TopicModel,
)


@pytest.fixture
def sample_model() -> ReferenceModel:
    return ReferenceModel(
        topics=[
            TopicModel(
                name="Левый желудочек",
                slug="lv",
                pathologies=[
                    PathologyModel(
                        name="Диастолическая",
                        slug="lv_diag",
                        description="Описание патологии",
                        parameters=[
                            ParameterModel(
                                id="ea_ratio",
                                name="E/A ratio",
                                unit="",
                                norm_male=NormRangeModel(low=0.8, high=2.0),
                                norm_female=NormRangeModel(low=0.8, high=2.0),
                                pathology_desc="Снижение",
                            )
                        ],
                    )
                ],
            )
        ]
    )


@pytest.fixture
def model_with_gradations() -> ReferenceModel:
    return ReferenceModel(
        topics=[
            TopicModel(
                name="Topic",
                slug="topic",
                pathologies=[
                    PathologyModel(
                        name="Patho",
                        slug="patho",
                        parameters=[],
                        gradations=[
                            GradationModel(
                                name="Mild",
                                parameters=[
                                    ParameterModel(id="g1", name="G1", unit="ml"),
                                ],
                            )
                        ],
                    )
                ],
            )
        ]
    )


@pytest.fixture
def model_with_images(tmp_path: Path) -> tuple[ReferenceModel, Path]:
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "test.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    model = ReferenceModel(
        topics=[
            TopicModel(
                name="T",
                slug="t",
                pathologies=[
                    PathologyModel(
                        name="P",
                        slug="p",
                        image_paths=["test.png"],
                        parameters=[],
                    )
                ],
            )
        ]
    )
    return model, images_dir


class TestFormatNorm:
    def test_none(self) -> None:
        assert _format_norm(None) == "\u2014"

    def test_both(self) -> None:
        result = _format_norm(NormRangeModel(low=1.0, high=5.0))
        assert ">=1.0" in result
        assert "<=5.0" in result

    def test_low_only(self) -> None:
        result = _format_norm(NormRangeModel(low=3.0))
        assert ">=3.0" in result

    def test_high_only(self) -> None:
        result = _format_norm(NormRangeModel(high=10.0))
        assert "<=10.0" in result

    def test_empty_range(self) -> None:
        assert _format_norm(NormRangeModel()) == "\u2014"


class TestMime:
    def test_png(self) -> None:
        assert _mime(Path("img.png")) == "png"

    def test_jpg(self) -> None:
        assert _mime(Path("img.jpg")) == "jpeg"

    def test_jpeg(self) -> None:
        assert _mime(Path("img.jpeg")) == "jpeg"

    def test_gif(self) -> None:
        assert _mime(Path("img.gif")) == "gif"

    def test_svg(self) -> None:
        assert _mime(Path("img.svg")) == "svg+xml"

    def test_unknown_defaults_png(self) -> None:
        assert _mime(Path("img.bmp")) == "png"


class TestEmbedImage:
    def test_embed_existing(self, tmp_path: Path) -> None:
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG")
        result = _embed_image(img)
        assert result is not None
        assert len(result) > 0

    def test_embed_nonexistent(self, tmp_path: Path) -> None:
        result = _embed_image(tmp_path / "missing.png")
        assert result is None


class TestExportToHtml:
    def test_export_basic(self, sample_model: ReferenceModel, tmp_path: Path) -> None:
        out = tmp_path / "out.html"
        export_to_html(sample_model, out)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "DOCTYPE html" in content
        assert "Левый желудочек" in content
        assert "ea_ratio" in content

    def test_export_with_gradations(self, model_with_gradations: ReferenceModel, tmp_path: Path) -> None:
        out = tmp_path / "out.html"
        export_to_html(model_with_gradations, out)
        content = out.read_text(encoding="utf-8")
        assert "Mild" in content
        assert "g1" in content

    def test_export_with_images(self, model_with_images: tuple[ReferenceModel, Path], tmp_path: Path) -> None:
        model, images_dir = model_with_images
        out = tmp_path / "out.html"
        export_to_html(model, out, images_dir=images_dir)
        content = out.read_text(encoding="utf-8")
        assert "data:image/png;base64," in content

    def test_export_missing_image(self, tmp_path: Path) -> None:
        model = ReferenceModel(
            topics=[
                TopicModel(
                    name="T",
                    slug="t",
                    pathologies=[
                        PathologyModel(
                            name="P",
                            slug="p",
                            image_paths=["nonexistent.png"],
                            parameters=[],
                        )
                    ],
                )
            ]
        )
        out = tmp_path / "out.html"
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        export_to_html(model, out, images_dir=images_dir)
        content = out.read_text(encoding="utf-8")
        assert "не найден" in content

    def test_export_search_js_present(self, sample_model: ReferenceModel, tmp_path: Path) -> None:
        out = tmp_path / "out.html"
        export_to_html(sample_model, out)
        content = out.read_text(encoding="utf-8")
        assert "filterTable" in content
        assert "toggleSection" in content

    def test_export_pathology_desc(self, sample_model: ReferenceModel, tmp_path: Path) -> None:
        out = tmp_path / "out.html"
        export_to_html(sample_model, out)
        content = out.read_text(encoding="utf-8")
        assert "Описание патологии" in content
        assert "Снижение" in content

    def test_export_empty_model(self, tmp_path: Path) -> None:
        model = ReferenceModel()
        out = tmp_path / "out.html"
        export_to_html(model, out)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "DOCTYPE html" in content
