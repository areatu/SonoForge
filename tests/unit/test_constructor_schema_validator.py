"""Tests for storage/schema_validator.py (additional edge cases)."""

from __future__ import annotations

import pytest

from echo_personal_tool.constructor.storage.schema_validator import (
    SchemaValidator,
    ValidationError,
)


@pytest.fixture
def validator() -> SchemaValidator:
    return SchemaValidator()


class TestValidationError:
    def test_str(self) -> None:
        err = ValidationError(path="topics[0].slug", message="Duplicate slug")
        assert str(err) == "topics[0].slug: Duplicate slug"

    def test_root_path(self) -> None:
        err = ValidationError(path="<root>", message="Missing required")
        assert str(err) == "<root>: Missing required"


class TestSchemaValidatorSemantic:
    def test_valid_minimal(self, validator: SchemaValidator) -> None:
        data = {"topics": []}
        errors = validator.validate(data)
        # Should pass schema; no semantic errors
        assert errors == []

    def test_duplicate_flat_param_ids(self, validator: SchemaValidator) -> None:
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
                                {"id": "x", "name": "X", "unit": ""},
                                {"id": "x", "name": "X2", "unit": ""},
                            ],
                        }
                    ],
                }
            ]
        }
        errors = validator.validate(data)
        assert any("Duplicate param id" in e.message for e in errors)

    def test_no_duplicate_across_pathologies(self, validator: SchemaValidator) -> None:
        """Same param ID in different pathologies is allowed."""
        data = {
            "topics": [
                {
                    "name": "T",
                    "slug": "t",
                    "pathologies": [
                        {"name": "P1", "slug": "p1", "parameters": [{"id": "x", "name": "X", "unit": ""}]},
                        {"name": "P2", "slug": "p2", "parameters": [{"id": "x", "name": "X", "unit": ""}]},
                    ],
                }
            ]
        }
        errors = validator.validate(data)
        assert not any("Duplicate param id" in e.message for e in errors)

    def test_duplicate_gradation_param_ids(self, validator: SchemaValidator) -> None:
        data = {
            "topics": [
                {
                    "name": "T",
                    "slug": "t",
                    "pathologies": [
                        {
                            "name": "P",
                            "slug": "p",
                            "parameters": [],
                            "gradations": [
                                {"name": "G1", "parameters": [{"id": "x", "name": "X", "unit": ""}]},
                                {"name": "G2", "parameters": [{"id": "x", "name": "X2", "unit": ""}]},
                            ],
                        }
                    ],
                }
            ]
        }
        errors = validator.validate(data)
        # Same ID across gradations is OK, not a duplicate
        assert not any("Duplicate param id" in e.message for e in errors)

    def test_duplicate_gradation_param_ids_within(self, validator: SchemaValidator) -> None:
        data = {
            "topics": [
                {
                    "name": "T",
                    "slug": "t",
                    "pathologies": [
                        {
                            "name": "P",
                            "slug": "p",
                            "parameters": [],
                            "gradations": [
                                {
                                    "name": "G1",
                                    "parameters": [
                                        {"id": "x", "name": "X", "unit": ""},
                                        {"id": "x", "name": "X2", "unit": ""},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        errors = validator.validate(data)
        assert any("Duplicate param id" in e.message for e in errors)

    def test_duplicate_topic_slugs(self, validator: SchemaValidator) -> None:
        data = {
            "topics": [
                {"name": "A", "slug": "same", "pathologies": []},
                {"name": "B", "slug": "same", "pathologies": []},
            ]
        }
        errors = validator.validate(data)
        assert any("Duplicate topic slug" in e.message for e in errors)

    def test_duplicate_pathology_slugs_under_same_topic(self, validator: SchemaValidator) -> None:
        data = {
            "topics": [
                {
                    "name": "T",
                    "slug": "t",
                    "pathologies": [
                        {"name": "P1", "slug": "dup", "parameters": []},
                        {"name": "P2", "slug": "dup", "parameters": []},
                    ],
                }
            ]
        }
        errors = validator.validate(data)
        assert any("Duplicate pathology slug" in e.message for e in errors)

    def test_pathology_slugs_same_across_topics_ok(self, validator: SchemaValidator) -> None:
        data = {
            "topics": [
                {
                    "name": "T1",
                    "slug": "t1",
                    "pathologies": [{"name": "P", "slug": "p", "parameters": []}],
                },
                {
                    "name": "T2",
                    "slug": "t2",
                    "pathologies": [{"name": "P", "slug": "p", "parameters": []}],
                },
            ]
        }
        errors = validator.validate(data)
        assert not any("Duplicate pathology slug" in e.message for e in errors)
