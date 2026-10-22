"""Tests for constructor storage layer."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from echo_personal_tool.constructor.storage.schema_validator import (
    SchemaValidator,
)
from echo_personal_tool.constructor.storage.yaml_storage import YamlStorage


@pytest.fixture
def sample_data() -> dict:
    return {
        "topics": [
            {
                "name": "Левый желудочек",
                "slug": "left_ventricle",
                "pathologies": [
                    {
                        "name": "Диастолическая функция",
                        "slug": "lv_diastolic",
                        "parameters": [
                            {
                                "id": "ea_ratio",
                                "name": "Соотношение E/A",
                                "unit": "",
                                "norm_male": {"low": 0.8, "high": 2.0},
                                "norm_female": {"low": 0.8, "high": 2.0},
                            }
                        ],
                    }
                ],
            }
        ]
    }


@pytest.fixture
def yaml_file(tmp_path: Path, sample_data: dict) -> Path:
    path = tmp_path / "test_references.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f, allow_unicode=True)
    return path


class TestYamlStorage:
    def test_load(self, yaml_file: Path) -> None:
        storage = YamlStorage(yaml_file)
        data = storage.load()
        assert "topics" in data
        assert len(data["topics"]) == 1
        assert data["topics"][0]["slug"] == "left_ventricle"

    def test_save(self, yaml_file: Path, sample_data: dict) -> None:
        storage = YamlStorage(yaml_file)
        storage.save(sample_data)

        # Verify file was written
        with open(yaml_file, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        assert loaded == sample_data

    def test_backup(self, yaml_file: Path, sample_data: dict) -> None:
        storage = YamlStorage(yaml_file)
        storage.save(sample_data)

        # Backup should exist
        bak = yaml_file.with_suffix(yaml_file.suffix + ".bak")
        assert bak.exists()

    def test_load_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        storage = YamlStorage(path)
        data = storage.load()
        assert data == {"topics": []}


class TestSchemaValidator:
    def test_valid_data(self, sample_data: dict) -> None:
        validator = SchemaValidator()
        errors = validator.validate(sample_data)
        assert errors == []

    def test_missing_topics(self) -> None:
        validator = SchemaValidator()
        errors = validator.validate({})
        assert len(errors) > 0

    def test_duplicate_param_ids(self) -> None:
        validator = SchemaValidator()
        data = {
            "topics": [
                {
                    "name": "T",
                    "slug": "t",
                    "pathologies": [
                        {
                            "name": "P1",
                            "slug": "p1",
                            "parameters": [
                                {"id": "param_1", "name": "A", "unit": ""},
                                {"id": "param_1", "name": "B", "unit": ""},
                            ],
                        }
                    ],
                }
            ]
        }
        errors = validator.validate(data)
        assert any("Duplicate" in e.message for e in errors)

    def test_duplicate_topic_slugs(self) -> None:
        validator = SchemaValidator()
        data = {
            "topics": [
                {"name": "A", "slug": "same", "pathologies": []},
                {"name": "B", "slug": "same", "pathologies": []},
            ]
        }
        errors = validator.validate(data)
        assert any("Duplicate topic slug" in e.message for e in errors)
