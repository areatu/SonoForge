"""Reproducible dependency-audit evidence and a release-graph SBOM (#563).

The CI run is the gate; this file pins the evidence it leaves behind and the
shape of the release SBOM:

* a dated, lock-bound evidence document whose findings are package/version/
  advisory facts (no paths, environment or advisory prose);
* an exception register that cannot outlive its review date or omit a reason;
* a CycloneDX SBOM generated from the locked runtime requirements, verified
  against the same file — not from the build/dev environment that also contains
  PyInstaller, Hatchling and CycloneDX itself.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "tools" / "security", ROOT / "tools" / "release"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import dependency_audit_evidence as evidence  # noqa: E402
import verify_sbom_graph as sbom_graph  # noqa: E402

pytestmark = pytest.mark.security

_GENERATED_AT = "2026-11-12T09:30:00Z"
_TODAY = "2026-11-12"


def _lock(path: Path) -> Path:
    path.write_text(
        '[[package]]\nname = "sonoforge"\nversion = "0.5.0"\n\n[[package]]\nname = "numpy"\nversion = "2.4.6"\n',
        encoding="utf-8",
    )
    return path


def _report(path: Path, *, vulnerable: bool) -> Path:
    dependency = {"name": "numpy", "version": "2.4.6", "vulns": []}
    if vulnerable:
        dependency["vulns"] = [
            {
                "id": "GHSA-test-0001",
                "aliases": ["CVE-2026-0001"],
                "fix_versions": ["2.4.7"],
                "description": "advisory prose that must not enter the evidence",
            }
        ]
    path.write_text(json.dumps({"dependencies": [dependency]}), encoding="utf-8")
    return path


def _requirements(path: Path) -> Path:
    path.write_text("numpy==2.4.6\n", encoding="utf-8")
    return path


def _exceptions(path: Path, *, review_by: str = "2027-02-12", reason: str | None = "reviewed") -> Path:
    license_entry = {
        "id": "pyside6-lgpl-branch",
        "packages": ["pyside6"],
        "scope": "license",
        "review_by": review_by,
    }
    if reason is not None:
        license_entry["reason"] = reason
    path.write_text(
        json.dumps(
            {
                "schema": evidence.EXCEPTIONS_SCHEMA,
                "reviewed_on": _TODAY,
                "next_review_on": "2027-02-12",
                "vulnerabilities": [],
                "licenses": [license_entry],
            }
        ),
        encoding="utf-8",
    )
    return path


def _document(tmp_path: Path, **kwargs) -> dict:
    return evidence.build_evidence(
        lock_path=_lock(tmp_path / "uv.lock"),
        runtime_report=_report(tmp_path / "pip-audit-runtime.json", vulnerable=True),
        dev_report=_report(tmp_path / "pip-audit-dev.json", vulnerable=False),
        runtime_requirements=_requirements(tmp_path / "runtime-requirements.txt"),
        dev_requirements=_requirements(tmp_path / "dev-requirements.txt"),
        exceptions_path=_exceptions(tmp_path / "exceptions.json"),
        generated_at=_GENERATED_AT,
        pip_audit_version="2.9.0",
        **kwargs,
    )


def test_evidence_binds_the_lock_the_scan_date_tool_and_commands(tmp_path: Path) -> None:
    document = _document(tmp_path)
    lock = (tmp_path / "uv.lock").read_bytes()

    assert document["schema"] == evidence.SCHEMA
    assert document["generated_at"] == _GENERATED_AT
    assert document["pip_audit"] == "2.9.0"
    assert document["python"]
    assert document["lock"]["sha256"] == evidence.sha256_file(tmp_path / "uv.lock")
    assert document["lock"]["packages"] == len(lock.split(b"[[package]]")) - 1
    assert document["commands"]["runtime"].startswith("pip-audit -r")
    assert document["commands"]["dev"].endswith("<dev-report>")
    assert document["contours"]["runtime"]["requirements_sha256"]


def test_findings_keep_only_advisory_facts_and_never_advisory_prose(tmp_path: Path) -> None:
    document = _document(tmp_path)
    runtime = document["contours"]["runtime"]
    finding = runtime["vulnerable_packages"][0]["findings"][0]

    assert runtime["blocking"] is True
    assert runtime["finding_count"] == 1
    assert finding == {
        "id": "GHSA-test-0001",
        "aliases": ["CVE-2026-0001"],
        "fix_versions": ["2.4.7"],
    }
    assert "advisory prose" not in json.dumps(document)
    assert str(tmp_path) not in json.dumps(document), "the artifact never carries a local path"


def test_a_later_scan_date_does_not_erase_the_original_finding(tmp_path: Path) -> None:
    document = _document(tmp_path)
    written = evidence.write_evidence(document, tmp_path / "evidence.json")
    again = evidence.write_evidence(_document(tmp_path), tmp_path / "evidence.json")

    assert written.read_text(encoding="utf-8") == again.read_text(encoding="utf-8")
    assert json.loads(written.read_text(encoding="utf-8"))["generated_at"] == _GENERATED_AT


def test_an_expired_exception_fails_instead_of_aging_silently(tmp_path: Path) -> None:
    with pytest.raises(evidence.EvidenceError, match="due for review"):
        evidence.build_evidence(
            lock_path=_lock(tmp_path / "uv.lock"),
            runtime_report=_report(tmp_path / "runtime.json", vulnerable=False),
            dev_report=_report(tmp_path / "dev.json", vulnerable=False),
            runtime_requirements=_requirements(tmp_path / "runtime.txt"),
            dev_requirements=_requirements(tmp_path / "dev.txt"),
            exceptions_path=_exceptions(tmp_path / "exceptions.json", review_by="2020-01-01"),
            generated_at=_GENERATED_AT,
            pip_audit_version="2.9.0",
        )


def test_an_exception_without_a_reason_is_refused(tmp_path: Path) -> None:
    with pytest.raises(evidence.EvidenceError, match="has no reason"):
        evidence.build_evidence(
            lock_path=_lock(tmp_path / "uv.lock"),
            runtime_report=_report(tmp_path / "runtime.json", vulnerable=False),
            dev_report=_report(tmp_path / "dev.json", vulnerable=False),
            runtime_requirements=_requirements(tmp_path / "runtime.txt"),
            dev_requirements=_requirements(tmp_path / "dev.txt"),
            exceptions_path=_exceptions(tmp_path / "exceptions.json", reason=None),
            generated_at=_GENERATED_AT,
            pip_audit_version="2.9.0",
        )


def test_the_shipped_register_is_current_and_has_review_dates() -> None:
    data = json.loads((ROOT / "docs" / "security" / "dependency-exceptions.json").read_text(encoding="utf-8"))

    assert data["schema"] == evidence.EXCEPTIONS_SCHEMA
    assert data["next_review_on"] >= date.today().isoformat()
    assert all(
        entry["reason"] and entry["review_by"]
        for entries in data.values()
        if isinstance(entries, list)
        for entry in entries
    )


def test_the_dependency_review_license_allowlist_matches_the_register() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "dependency-review.yml").read_text(encoding="utf-8"))
    step = workflow["jobs"]["dependency-review"]["steps"][1]["with"]
    allowed = {item.strip().removeprefix("pkg:pypi/") for item in step["allow-dependencies-licenses"].split(",")}
    register = json.loads((ROOT / "docs" / "security" / "dependency-exceptions.json").read_text(encoding="utf-8"))

    registered = {package for entry in register["licenses"] for package in entry["packages"]}
    assert allowed == registered


def _bom(path: Path, components: list[dict]) -> Path:
    path.write_text(
        json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "components": components}),
        encoding="utf-8",
    )
    return path


def test_sbom_must_equal_the_locked_runtime_graph(tmp_path: Path) -> None:
    requirements = _requirements(tmp_path / "runtime.txt")
    matching = _bom(tmp_path / "sbom.json", [{"name": "NumPy", "version": "2.4.6"}])

    assert sbom_graph.verify(matching, requirements) == []

    extra = _bom(
        tmp_path / "extra.json",
        [{"name": "numpy", "version": "2.4.6"}, {"name": "cyclonedx-bom", "version": "8.0.1"}],
    )
    assert "outside the runtime graph: cyclonedx-bom" in sbom_graph.verify(extra, requirements)[0]

    stale = _bom(tmp_path / "stale.json", [{"name": "numpy", "version": "2.4.5"}])
    problems = sbom_graph.verify(stale, requirements)
    assert any("omits runtime components: numpy==2.4.6" in problem for problem in problems)
    assert any("outside the runtime graph: numpy==2.4.5" in problem for problem in problems)


def test_release_workflows_build_the_sbom_from_runtime_requirements() -> None:
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert release.count("cyclonedx_py requirements") == 3
    assert "cyclonedx_py environment" not in release
    assert release.count("tools/release/verify_sbom_graph.py") == 3
    assert release.count("uv export --locked --no-hashes --no-emit-project") >= 3


def test_ci_leaves_the_dated_evidence_artifact_and_requires_its_test() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    scheduled = (ROOT / ".github" / "workflows" / "security-audit.yml").read_text(encoding="utf-8")
    required = (ROOT / ".github" / "required-tests" / "security.txt").read_text(encoding="utf-8")

    for workflow in (ci, scheduled):
        assert "tools/security/dependency_audit_evidence.py" in workflow
        assert "--runtime-requirements /tmp/runtime-requirements.txt" in workflow
        assert "/tmp/pip-audit-runtime.json" in workflow
        assert "dependency-audit-evidence.json" in workflow
    assert "tests/security/test_dependency_audit_evidence.py" in required
