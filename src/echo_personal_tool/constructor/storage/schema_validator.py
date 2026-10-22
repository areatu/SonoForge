"""JSON Schema validation for references_structured.yaml."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

_SCHEMA_DIR = Path(__file__).parents[2] / "resources" / "references"


class ValidationError:
    """Single validation error with path context."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class SchemaValidator:
    """Validate reference data against JSON Schema + semantic rules."""

    def __init__(self) -> None:
        schema_path = _SCHEMA_DIR / "references_schema.json"
        with open(schema_path, encoding="utf-8") as f:
            self._schema: dict[str, Any] = json.load(f)

    def validate(self, data: dict[str, Any]) -> list[ValidationError]:
        """Run schema validation + semantic checks. Returns list of errors."""
        errors: list[ValidationError] = []

        # Schema validation
        validator = jsonschema.Draft202012Validator(self._schema)
        for err in validator.iter_errors(data):
            errors.append(
                ValidationError(
                    path=".".join(str(p) for p in err.absolute_path) or "<root>",
                    message=err.message,
                )
            )

        # Semantic: unique param IDs
        errors.extend(self._check_unique_ids(data))

        # Semantic: unique topic/pathology slugs
        errors.extend(self._check_unique_slugs(data))

        return errors

    def _check_unique_ids(self, data: dict[str, Any]) -> list[ValidationError]:
        errors: list[ValidationError] = []
        # Check flat parameters: unique within each pathology
        for t_idx, topic in enumerate(data.get("topics", [])):
            for p_idx, pathology in enumerate(topic.get("pathologies", [])):
                seen_flat: dict[str, str] = {}
                for param in pathology.get("parameters", []):
                    pid = param.get("id", "")
                    loc = f"topics[{t_idx}].pathologies[{p_idx}].parameters"
                    if pid in seen_flat:
                        errors.append(
                            ValidationError(
                                path=f"{loc}(id={pid})",
                                message=f"Duplicate param id '{pid}' in flat parameters (first at {seen_flat[pid]})",
                            )
                        )
                    else:
                        seen_flat[pid] = f"{loc}(id={pid})"

                # Check gradation parameters: unique within each gradation (same ID across gradations is OK)
                for g_idx, grad in enumerate(pathology.get("gradations", [])):
                    seen_grad: dict[str, str] = {}
                    for param in grad.get("parameters", []):
                        pid = param.get("id", "")
                        loc = f"topics[{t_idx}].pathologies[{p_idx}].gradations[{g_idx}].parameters"
                        if pid in seen_grad:
                            errors.append(
                                ValidationError(
                                    path=f"{loc}(id={pid})",
                                    message=f"Duplicate param id '{pid}' in gradation '{grad.get('name', '')}' (first at {seen_grad[pid]})",  # noqa: E501
                                )
                            )
                        else:
                            seen_grad[pid] = f"{loc}(id={pid})"

        return errors

    def _check_unique_slugs(self, data: dict[str, Any]) -> list[ValidationError]:
        errors: list[ValidationError] = []
        seen_topics: dict[str, str] = {}
        seen_pathos: dict[str, str] = {}

        for t_idx, topic in enumerate(data.get("topics", [])):
            slug = topic.get("slug", "")
            if slug in seen_topics:
                errors.append(
                    ValidationError(
                        path=f"topics[{t_idx}].slug",
                        message=f"Duplicate topic slug '{slug}' (first at {seen_topics[slug]})",
                    )
                )
            else:
                seen_topics[slug] = f"topics[{t_idx}].slug"

            for p_idx, pathology in enumerate(topic.get("pathologies", [])):
                pslug = pathology.get("slug", "")
                key = f"{slug}/{pslug}"
                if key in seen_pathos:
                    errors.append(
                        ValidationError(
                            path=f"topics[{t_idx}].pathologies[{p_idx}].slug",
                            message=f"Duplicate pathology slug '{pslug}' under topic '{slug}'",
                        )
                    )
                else:
                    seen_pathos[key] = f"topics[{t_idx}].pathologies[{p_idx}].slug"

        return errors
