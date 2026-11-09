"""Release SBOMs are finalized before they are recorded and attested."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release"))
import finalize_sbom  # noqa: E402


def _write_bom(path: Path, **extra: object) -> None:
    path.write_text(
        json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [{"name": "numpy"}], **extra}),
        encoding="utf-8",
    )


def test_finalization_binds_release_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "sbom.json"
    _write_bom(path)
    finalize_sbom.finalize(path, "0.4.0")
    content = path.read_bytes()
    result = json.loads(content)
    assert result["metadata"]["component"] == {"type": "application", "name": "SonoForge", "version": "0.4.0"}
    assert result["serialNumber"].startswith("urn:uuid:")
    assert result["components"] == [{"name": "numpy"}]
    finalize_sbom.finalize(path, "0.4.0")
    assert path.read_bytes() == content


@pytest.mark.parametrize(
    "extra",
    [
        {"metadata": {"component": {"version": "0.3.0"}}},
        {"serialNumber": "urn:uuid:00000000-0000-0000-0000-000000000000"},
        {"components": []},
        {"specVersion": "1.7"},
    ],
)
def test_rejects_conflicting_or_invalid_sbom(tmp_path: Path, extra: dict) -> None:
    path = tmp_path / "sbom.json"
    _write_bom(path, **extra)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        finalize_sbom.finalize(path, "0.4.0")
    assert path.read_bytes() == original
