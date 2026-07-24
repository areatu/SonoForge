"""Unit tests for constructor exporters and importers."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui


# ── html_exporter ──────────────────────────────────────────────────


class TestHtmlExporterFormatNorm:
    def test_none(self) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _format_norm

        assert _format_norm(None) == "—"

    def test_both_low_high(self) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _format_norm
        from echo_personal_tool.constructor.models.reference_model import NormRangeModel

        norm = NormRangeModel(low=60.0, high=100.0)
        result = _format_norm(norm)
        assert ">=60.0" in result
        assert "<=100.0" in result

    def test_low_only(self) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _format_norm
        from echo_personal_tool.constructor.models.reference_model import NormRangeModel

        norm = NormRangeModel(low=50.0)
        result = _format_norm(norm)
        assert ">=50.0" in result

    def test_high_only(self) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _format_norm
        from echo_personal_tool.constructor.models.reference_model import NormRangeModel

        norm = NormRangeModel(high=120.0)
        result = _format_norm(norm)
        assert "<=120.0" in result

    def test_empty_norm(self) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _format_norm
        from echo_personal_tool.constructor.models.reference_model import NormRangeModel

        norm = NormRangeModel()
        assert _format_norm(norm) == "—"


class TestHtmlExporterMime:
    def test_png(self) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _mime

        assert _mime(Path("image.png")) == "png"

    def test_jpg(self) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _mime

        assert _mime(Path("image.jpg")) == "jpeg"

    def test_jpeg(self) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _mime

        assert _mime(Path("image.jpeg")) == "jpeg"

    def test_gif(self) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _mime

        assert _mime(Path("image.gif")) == "gif"

    def test_svg(self) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _mime

        assert _mime(Path("image.svg")) == "svg+xml"

    def test_unknown(self) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _mime

        assert _mime(Path("image.webp")) == "png"


class TestHtmlExporterEmbedImage:
    def test_valid_image(self, tmp_path) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _embed_image

        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        result = _embed_image(img)
        assert result is not None
        assert len(result) > 0

    def test_nonexistent_image(self, tmp_path) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _embed_image

        result = _embed_image(tmp_path / "missing.png")
        assert result is None


class TestHtmlExporterBuildHtml:
    def test_empty_model(self, tmp_path) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _build_html
        from echo_personal_tool.constructor.models.reference_model import ReferenceModel
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        model = ReferenceModel()
        storage = ImageStorage(tmp_path)
        html = _build_html(model, storage)
        assert "<!DOCTYPE html>" in html
        assert "Справочник эхокардиографии" in html

    def test_model_with_topic(self, tmp_path) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import _build_html
        from echo_personal_tool.constructor.models.reference_model import (
            ParameterModel,
            PathologyModel,
            ReferenceModel,
            TopicModel,
        )
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        param = ParameterModel(id="IVSd", name="IVSd", unit="mm")
        patho = PathologyModel(name="HCM", parameters=[param])
        topic = TopicModel(name="Myocardium", pathologies=[patho])
        model = ReferenceModel(topics=[topic])
        storage = ImageStorage(tmp_path)
        html = _build_html(model, storage)
        assert "Myocardium" in html
        assert "HCM" in html
        assert "IVSd" in html
        assert "IVSd" in html


class TestHtmlExporterExportToFile:
    def test_export_creates_file(self, tmp_path) -> None:
        from echo_personal_tool.constructor.exporters.html_exporter import export_to_html
        from echo_personal_tool.constructor.models.reference_model import ReferenceModel

        output = tmp_path / "output.html"
        model = ReferenceModel()
        export_to_html(model, output)
        assert output.exists()
        assert output.stat().st_size > 0


# ── pdf_exporter ───────────────────────────────────────────────────


class TestPdfExporterFormatNorm:
    def test_none(self) -> None:
        from echo_personal_tool.constructor.exporters.pdf_exporter import _format_norm

        assert _format_norm(None) == "—"

    def test_both(self) -> None:
        from echo_personal_tool.constructor.exporters.pdf_exporter import _format_norm
        from echo_personal_tool.constructor.models.reference_model import NormRangeModel

        norm = NormRangeModel(low=60.0, high=100.0)
        result = _format_norm(norm)
        assert ">=60.0" in result
        assert "<=100.0" in result


class TestPdfExporterBuildHtml:
    def test_empty_model(self) -> None:
        from echo_personal_tool.constructor.exporters.pdf_exporter import _build_html
        from echo_personal_tool.constructor.models.reference_model import ReferenceModel

        model = ReferenceModel()
        html = _build_html(model)
        assert "<html>" in html
        assert "</body></html>" in html

    def test_model_with_topic(self) -> None:
        from echo_personal_tool.constructor.exporters.pdf_exporter import _build_html
        from echo_personal_tool.constructor.models.reference_model import (
            PathologyModel,
            ReferenceModel,
            TopicModel,
        )

        patho = PathologyModel(name="HCM")
        topic = TopicModel(name="Myocardium", pathologies=[patho])
        model = ReferenceModel(topics=[topic])
        html = _build_html(model)
        assert "Myocardium" in html
        assert "HCM" in html


# ── excel_importer ─────────────────────────────────────────────────


class TestExcelImporterParseNum:
    def test_none(self) -> None:
        from echo_personal_tool.constructor.importers.excel_importer import _parse_num

        assert _parse_num(None) is None

    def test_valid_number(self) -> None:
        from echo_personal_tool.constructor.importers.excel_importer import _parse_num

        assert _parse_num(42.5) == 42.5
        assert _parse_num("100") == 100.0

    def test_invalid_string(self) -> None:
        from echo_personal_tool.constructor.importers.excel_importer import _parse_num

        assert _parse_num("abc") is None

    def test_empty_string(self) -> None:
        from echo_personal_tool.constructor.importers.excel_importer import _parse_num

        assert _parse_num("") is None


class TestExcelImporterImportFile:
    def test_import_valid_excel(self, tmp_path) -> None:
        import openpyxl

        from echo_personal_tool.constructor.importers.excel_importer import import_excel_file

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Myocardium"
        ws.append(["id", "name", "unit", "norm_male_low", "norm_male_high"])
        ws.append(["IVSd", "IVSd thickness", "mm", 6.0, 11.0])
        ws.append(["LVIDd", "LVIDd", "mm", 35.0, 57.0])

        path = tmp_path / "test.xlsx"
        wb.save(str(path))

        result = import_excel_file(path)
        assert "topics" in result
        assert len(result["topics"]) == 1
        topic = result["topics"][0]
        assert topic["name"] == "Myocardium"
        assert len(topic["pathologies"]) == 1
        params = topic["pathologies"][0]["parameters"]
        assert len(params) == 2
        assert params[0]["id"] == "IVSd"

    def test_import_empty_sheet(self, tmp_path) -> None:
        import openpyxl

        from echo_personal_tool.constructor.importers.excel_importer import import_excel_file

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Empty"
        ws.append(["id", "name"])  # headers only, no data rows

        path = tmp_path / "empty.xlsx"
        wb.save(str(path))

        result = import_excel_file(path)
        assert result["topics"] == []


# ── reference_model ────────────────────────────────────────────────


class TestNormRangeModel:
    def test_creation(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import NormRangeModel

        norm = NormRangeModel(low=60.0, high=100.0)
        assert norm.low == 60.0
        assert norm.high == 100.0

    def test_defaults(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import NormRangeModel

        norm = NormRangeModel()
        assert norm.low is None
        assert norm.high is None

    def test_to_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import NormRangeModel

        norm = NormRangeModel(low=60.0, high=100.0)
        d = norm.to_dict()
        assert d == {"low": 60.0, "high": 100.0}

    def test_from_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import NormRangeModel

        norm = NormRangeModel.from_dict({"low": 50.0, "high": 80.0})
        assert norm.low == 50.0
        assert norm.high == 80.0

    def test_from_dict_none(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import NormRangeModel

        assert NormRangeModel.from_dict(None) is None


class TestParameterModel:
    def test_creation(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import ParameterModel

        param = ParameterModel(id="IVSd", name="IVSd", unit="mm")
        assert param.id == "IVSd"
        assert param.name == "IVSd"
        assert param.unit == "mm"

    def test_to_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            NormRangeModel,
            ParameterModel,
        )

        param = ParameterModel(
            id="IVSd", name="IVSd", unit="mm",
            norm_male=NormRangeModel(low=6.0, high=11.0),
            pathology_desc="Increased in HCM",
        )
        d = param.to_dict()
        assert d["id"] == "IVSd"
        assert d["norm_male"] == {"low": 6.0, "high": 11.0}
        assert d["pathology_desc"] == "Increased in HCM"

    def test_from_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import ParameterModel

        d = {"id": "LVIDd", "name": "LVIDd", "unit": "mm"}
        param = ParameterModel.from_dict(d)
        assert param.id == "LVIDd"


class TestGradationModel:
    def test_creation(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import GradationModel

        grad = GradationModel(name="Mild")
        assert grad.name == "Mild"
        assert grad.parameters == []

    def test_to_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            GradationModel,
            ParameterModel,
        )

        grad = GradationModel(
            name="Mild",
            parameters=[ParameterModel(id="p1", name="P1")],
        )
        d = grad.to_dict()
        assert d["name"] == "Mild"
        assert len(d["parameters"]) == 1

    def test_from_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import GradationModel

        d = {"name": "Severe", "parameters": [{"id": "p1", "name": "P1"}]}
        grad = GradationModel.from_dict(d)
        assert grad.name == "Severe"
        assert len(grad.parameters) == 1


class TestPathologyModel:
    def test_creation(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import PathologyModel

        patho = PathologyModel(name="HCM", slug="hcm")
        assert patho.name == "HCM"
        assert patho.slug == "hcm"
        assert patho.description is None

    def test_to_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import PathologyModel

        patho = PathologyModel(
            name="HCM", slug="hcm",
            description="Hypertrophic cardiomyopathy",
            parameters=[],
        )
        d = patho.to_dict()
        assert d["name"] == "HCM"
        assert d["description"] == "Hypertrophic cardiomyopathy"

    def test_from_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import PathologyModel

        d = {"name": "DCM", "slug": "dcm", "parameters": []}
        patho = PathologyModel.from_dict(d)
        assert patho.name == "DCM"

    def test_post_init_converts_gradation_dicts(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import PathologyModel

        patho = PathologyModel(
            name="HCM",
            gradations=[{"name": "Mild", "parameters": []}],
        )
        assert len(patho.gradations) == 1
        assert patho.gradations[0].name == "Mild"


class TestTopicModel:
    def test_creation(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import TopicModel

        topic = TopicModel(name="Myocardium", slug="myocardium")
        assert topic.name == "Myocardium"
        assert topic.pathologies == []

    def test_to_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import TopicModel

        topic = TopicModel(name="Myocardium", pathologies=[])
        d = topic.to_dict()
        assert d["name"] == "Myocardium"


class TestReferenceModel:
    def test_creation(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import ReferenceModel

        model = ReferenceModel()
        assert model.topics == []

    def test_to_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            ReferenceModel,
            TopicModel,
        )

        model = ReferenceModel(topics=[TopicModel(name="Test")])
        d = model.to_dict()
        assert len(d["topics"]) == 1

    def test_from_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import ReferenceModel

        d = {"topics": [{"name": "Test", "pathologies": []}]}
        model = ReferenceModel.from_dict(d)
        assert len(model.topics) == 1
        assert model.topics[0].name == "Test"

    def test_deep_copy(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            PathologyModel,
            ReferenceModel,
            TopicModel,
        )

        model = ReferenceModel(
            topics=[TopicModel(name="T", pathologies=[PathologyModel(name="P")])],
        )
        copy = model.deep_copy()
        assert copy.topics[0].name == "T"
        # Modifying copy should not affect original
        copy.topics[0].name = "Changed"
        assert model.topics[0].name == "T"


# ── yaml_storage ───────────────────────────────────────────────────


class TestYamlStorage:
    def test_load(self, tmp_path) -> None:
        import yaml

        from echo_personal_tool.constructor.storage.yaml_storage import YamlStorage

        data = {"topics": [{"name": "Test", "pathologies": []}]}
        path = tmp_path / "test.yaml"
        path.write_text(yaml.dump(data), encoding="utf-8")

        storage = YamlStorage(path)
        loaded = storage.load()
        assert loaded == data

    def test_load_empty(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.yaml_storage import YamlStorage

        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")

        storage = YamlStorage(path)
        loaded = storage.load()
        assert loaded == {"topics": []}

    def test_save(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.yaml_storage import YamlStorage

        data = {"topics": [{"name": "New", "pathologies": []}]}
        path = tmp_path / "save.yaml"
        storage = YamlStorage(path)
        storage.save(data)

        loaded = storage.load()
        assert loaded == data

    def test_save_creates_backup(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.yaml_storage import YamlStorage

        path = tmp_path / "test.yaml"
        path.write_text("original", encoding="utf-8")
        storage = YamlStorage(path)
        storage.save({"topics": []})

        bak = path.with_suffix(".yaml.bak")
        assert bak.exists()
        assert bak.read_text() == "original"

    def test_path_property(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.yaml_storage import YamlStorage

        path = tmp_path / "test.yaml"
        storage = YamlStorage(path)
        assert storage.path == path


# ── schema_validator ───────────────────────────────────────────────


class TestSchemaValidator:
    def test_valid_data(self) -> None:
        from echo_personal_tool.constructor.storage.schema_validator import SchemaValidator

        validator = SchemaValidator()
        data = {"topics": [{"name": "Test", "slug": "test", "pathologies": []}]}
        errors = validator.validate(data)
        # Should have no errors for valid minimal data
        assert isinstance(errors, list)

    def test_duplicate_param_ids(self) -> None:
        from echo_personal_tool.constructor.storage.schema_validator import SchemaValidator

        validator = SchemaValidator()
        data = {
            "topics": [
                {
                    "name": "T",
                    "slug": "t",
                    "pathologies": [
                        {
                            "name": "P",
                            "slug": "p",
                            "parameters": [
                                {"id": "IVSd", "name": "IVSd"},
                                {"id": "IVSd", "name": "IVSd dup"},
                            ],
                        }
                    ],
                }
            ]
        }
        errors = validator.validate(data)
        assert any("Duplicate param id" in e.message for e in errors)

    def test_duplicate_topic_slugs(self) -> None:
        from echo_personal_tool.constructor.storage.schema_validator import SchemaValidator

        validator = SchemaValidator()
        data = {
            "topics": [
                {"name": "T1", "slug": "same", "pathologies": []},
                {"name": "T2", "slug": "same", "pathologies": []},
            ]
        }
        errors = validator.validate(data)
        assert any("Duplicate topic slug" in e.message for e in errors)

    def test_duplicate_pathology_slugs(self) -> None:
        from echo_personal_tool.constructor.storage.schema_validator import SchemaValidator

        validator = SchemaValidator()
        data = {
            "topics": [
                {
                    "name": "T",
                    "slug": "t",
                    "pathologies": [
                        {"name": "P1", "slug": "same"},
                        {"name": "P2", "slug": "same"},
                    ],
                }
            ]
        }
        errors = validator.validate(data)
        assert any("Duplicate pathology slug" in e.message for e in errors)

    def test_validation_error_str(self) -> None:
        from echo_personal_tool.constructor.storage.schema_validator import ValidationError

        err = ValidationError(path="topics[0].name", message="Required")
        assert "topics[0].name" in str(err)
        assert "Required" in str(err)


# ── base_editor ────────────────────────────────────────────────────


class TestBaseEditor:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.base_editor import BaseEditor

        editor = BaseEditor()
        qtbot.addWidget(editor)
        assert editor is not None

    def test_delete_selected(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.base_editor import BaseEditor

        editor = BaseEditor()
        qtbot.addWidget(editor)
        editor.delete_selected()  # should not crash

    def test_has_content_changed_signal(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.base_editor import BaseEditor

        editor = BaseEditor()
        qtbot.addWidget(editor)
        assert hasattr(editor, "content_changed")


# ── metadata_editor ────────────────────────────────────────────────


class TestMetadataEditor:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.metadata_editor import MetadataEditor

        editor = MetadataEditor()
        qtbot.addWidget(editor)
        assert editor._parameter is None
