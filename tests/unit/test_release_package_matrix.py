"""The release matrix, the Presenter pins and the packaging workflows agree (QH-5a).

Three promises are pinned here, because each of them is invisible in a normal
test run:

* the declared package matrix (``.github/package-matrix.yml``) is internally
  consistent and names every profile/platform/asset the release publishes;
* the Presenter pin list is the same locked closure as ``uv.lock`` — a second
  dependency list is only acceptable while it provably belongs to this lock;
* the packaging workflows contain no ``pip install -e .`` and no floating
  dependency fallback, install from ``uv.lock``, and actually run the package
  smoke and the published-bytes verification the matrix documents.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOLS = ROOT / "tools" / "release"
if str(RELEASE_TOOLS) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOLS))

import package_matrix  # noqa: E402,I001
import presenter_pins  # noqa: E402,I001

MATRIX_PATH = ROOT / ".github" / "package-matrix.yml"
WORKFLOWS = ROOT / ".github" / "workflows"
PINS = ROOT / "build" / "presenter" / "pinned-packages.txt"
LOCK = ROOT / "uv.lock"
PACKAGING_WORKFLOWS = ("build.yml", "release.yml", "presenter.yml", "benchmark.yml", "ste-fixtures.yml")


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _workflow_text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _run_scripts(workflow: dict) -> str:
    """Every ``run:`` command of every step — comments in the YAML do not count."""
    scripts: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "run" and isinstance(value, str):
                    scripts.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(workflow)
    return "\n".join(scripts)


def _mutated(matrix: dict) -> dict:
    return yaml.safe_load(yaml.safe_dump(matrix, allow_unicode=True))


# ── the shipped matrix ────────────────────────────────────────────────


class TestShippedMatrix:
    def test_matrix_loads_and_validates(self) -> None:
        matrix = package_matrix.load(MATRIX_PATH)
        assert matrix["schema"] == 1
        assert set(matrix["profiles"]) == {"full", "presenter"}
        assert set(matrix["platforms"]) >= {"linux-amd64", "windows-x64", "macos-arm64", "source"}

    def test_every_asset_names_the_version_a_job_and_a_workflow(self) -> None:
        matrix = package_matrix.load(MATRIX_PATH)
        for asset in package_matrix.assets_for(matrix, "9.9.9"):
            assert "9.9.9" in asset["name"]
            assert asset["template"]
            assert asset["job"]
            assert asset["workflow"] in {"release.yml", "presenter.yml"}

    def test_full_and_presenter_asset_sets_are_disjoint(self) -> None:
        matrix = package_matrix.load(MATRIX_PATH)
        full = set(package_matrix.asset_names(matrix, "9.9.9", ["full"]))
        presenter = set(package_matrix.asset_names(matrix, "9.9.9", ["presenter"]))
        assert full and presenter
        assert not full & presenter
        assert set(package_matrix.asset_names(matrix, "9.9.9")) == full | presenter

    def test_every_packaged_asset_has_an_sbom_and_a_smoke_level(self) -> None:
        matrix = package_matrix.load(MATRIX_PATH)
        for asset in package_matrix.assets_for(matrix, "9.9.9"):
            if asset["smoke"] == "none":
                assert asset["platform"] == "source"
                assert asset["sbom"] is None
            else:
                assert asset["smoke"] in {"artifact", "payload"}
                assert asset["sbom"] and "9.9.9" in asset["sbom"]

    def test_the_matrix_matches_the_asset_names_the_workflows_publish(self) -> None:
        """The matrix is only evidence if the packaging jobs produce those names."""
        matrix = package_matrix.load(MATRIX_PATH)
        release = _workflow_text("release.yml")
        presenter = _workflow_text("presenter.yml")
        for asset in package_matrix.assets_for(matrix, "9.9.9"):
            template = asset["template"]
            # `{version}` becomes `${version}` / `$version` / `*-` in shell globs.
            stem = template.split("{version}")[0]
            suffix = template.split("{version}")[1]
            pattern = f"{stem}*{suffix}"
            text = release if asset["workflow"] == "release.yml" else presenter
            assert stem in text or suffix in text, pattern

    def test_checksum_manifests_cover_their_profiles(self) -> None:
        matrix = package_matrix.load(MATRIX_PATH)
        expectations = package_matrix.checksum_expectations(matrix, "9.9.9")
        assert set(expectations) == {"SHA256SUMS", "SHA256SUMS-presenter.txt"}
        full = package_matrix.checksum_expectations(matrix, "9.9.9", ["full"])
        assert set(full) == {"SHA256SUMS"}
        assert not [name for name in full["SHA256SUMS"] if "Presenter" in name]
        presenter = package_matrix.checksum_expectations(matrix, "9.9.9", ["presenter"])
        assert set(presenter) == {"SHA256SUMS-presenter.txt"}

    def test_build_record_names_are_versioned_per_profile_and_platform(self) -> None:
        matrix = package_matrix.load(MATRIX_PATH)
        assert package_matrix.record_name(matrix, "full", "linux-amd64", "1.2.3") == (
            "build-record-full-linux-amd64-1.2.3.json"
        )
        assert package_matrix.record_name(matrix, "presenter", "linux-x86_64", "1.2.3") == (
            "build-record-presenter-linux-x86_64-1.2.3.json"
        )

    def test_the_matrix_declares_its_gaps(self) -> None:
        """A matrix that claims full coverage would be the dishonest kind."""
        matrix = package_matrix.load(MATRIX_PATH)
        gaps = " ".join(f"{gap['id']} {gap['text']}" for gap in matrix["gaps"]).lower()
        assert "deb" in gaps
        assert "g5b" in gaps or "signature" in gaps
        assert "usb" in gaps

    def test_the_matrix_names_the_smoke_and_record_contract(self) -> None:
        matrix = package_matrix.load(MATRIX_PATH)
        assert matrix["smoke"]["module"] == "echo_personal_tool.application.package_smoke"
        assert matrix["smoke"]["entry_flag"] == "--package-smoke"
        assert sorted(matrix["smoke"]["stages"]) == ["restart", "save"]
        assert "{profile}" in matrix["records"]["name"]
        assert "{platform}" in matrix["records"]["name"]

    def test_cli_prints_a_summary_and_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert package_matrix.main([]) == 0
        assert "package matrix OK" in capsys.readouterr().out
        assert package_matrix.main(["--json"]) == 0
        payload = yaml.safe_load(capsys.readouterr().out)
        assert payload["profiles"] == ["full", "presenter"]
        assert len(payload["assets"]) == len(package_matrix.load(MATRIX_PATH)["assets"])

    def test_cli_fails_on_a_broken_matrix(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        broken = tmp_path / "matrix.yml"
        broken.write_text("schema: 2\n", encoding="utf-8")
        assert package_matrix.main(["--matrix", str(broken)]) == 1
        assert "unsupported schema" in capsys.readouterr().err


# ── matrix validation catches contradictions ──────────────────────────


class TestMatrixValidation:
    def _problems(self, matrix: dict) -> str:
        with pytest.raises(package_matrix.MatrixError) as error:
            package_matrix.validate(matrix)
        return str(error.value)

    def test_unknown_profile_is_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["assets"][0]["profile"] = "lite"
        assert "unknown profile" in self._problems(matrix)

    def test_unknown_platform_is_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["assets"][0]["platform"] = "bsd-mips"
        assert "unknown platform" in self._problems(matrix)

    def test_asset_without_version_placeholder_is_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["assets"][0]["name"] = "sonoforge.deb"
        assert "must carry {version}" in self._problems(matrix)

    def test_source_asset_with_an_sbom_is_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        source = next(asset for asset in matrix["assets"] if asset["platform"] == "source")
        source["sbom"] = "x-{version}.sbom.cdx.json"
        assert "source-only" in self._problems(matrix)

    def test_packaged_asset_without_an_sbom_is_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["assets"][0]["sbom"] = None
        assert "must declare an SBOM" in self._problems(matrix)

    def test_full_asset_in_the_presenter_workflow_is_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["assets"][0]["workflow"] = "presenter.yml"
        assert "must be produced by presenter.yml" in self._problems(matrix) or (
            "is not a Presenter asset but is built by presenter.yml" in self._problems(matrix)
        )

    def test_presenter_asset_outside_its_workflow_is_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        presenter = next(asset for asset in matrix["assets"] if asset["profile"] == "presenter")
        presenter["workflow"] = "release.yml"
        assert "must be produced by presenter.yml" in self._problems(matrix)

    def test_undeclared_manifest_is_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["assets"][0]["manifest"] = "SHA256SUMS-other.txt"
        assert "unknown checksum manifest" in self._problems(matrix)

    def test_duplicate_asset_name_is_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["assets"][1]["name"] = matrix["assets"][0]["name"]
        assert "duplicate asset name" in self._problems(matrix)

    def test_unknown_smoke_level_is_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["assets"][0]["smoke"] = "wishful"
        assert "smoke must be one of" in self._problems(matrix)

    def test_missing_gaps_are_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["gaps"] = []
        assert "gaps" in self._problems(matrix)

    def test_empty_forbidden_list_is_rejected(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["policy"]["forbidden"] = []
        assert "policy.forbidden" in self._problems(matrix)

    def test_record_pattern_must_distinguish_profile_and_platform(self) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["records"]["name"] = "build-record-{version}-{profile}.json"
        assert "distinguish profile and platform" in self._problems(matrix)

    def test_load_fails_on_a_contradiction(self, tmp_path: Path) -> None:
        matrix = _mutated(package_matrix.load(MATRIX_PATH))
        matrix["assets"][0]["smoke"] = "wishful"
        broken = tmp_path / "matrix.yml"
        broken.write_text(yaml.safe_dump(matrix, allow_unicode=True), encoding="utf-8")
        with pytest.raises(package_matrix.MatrixError, match="smoke must be one of"):
            package_matrix.load(broken)

    def test_unknown_profile_selection_is_rejected(self) -> None:
        matrix = package_matrix.load(MATRIX_PATH)
        with pytest.raises(package_matrix.MatrixError, match="unknown profile"):
            package_matrix.assets_for(matrix, "9.9.9", ["lite"])


# ── Presenter pins ────────────────────────────────────────────────────


class TestPresenterPins:
    def test_shipped_pins_are_exactly_the_locked_lite_closure(self) -> None:
        assert presenter_pins.check(PINS, LOCK) == []
        assert set(presenter_pins.pins_map(PINS)) == set(presenter_pins.lite_closure(LOCK))

    def test_the_lite_closure_excludes_the_dropped_packages(self) -> None:
        closure = presenter_pins.lite_closure(LOCK)
        for excluded in ("onnxruntime", "pymupdf", "openpyxl", "pyside6", "pyside6-addons"):
            assert excluded not in closure, excluded
        assert "pyside6-essentials" in closure
        assert "shiboken6" in closure  # transitive dependency of the essentials wheel

    def test_transitive_dependencies_are_pinned_not_left_to_pip(self) -> None:
        closure = presenter_pins.lite_closure(LOCK)
        for transitive in ("anyio", "certifi", "httpcore", "idna", "shiboken6", "typing-extensions"):
            assert transitive in closure, transitive

    def test_drifted_version_is_reported(self, tmp_path: Path) -> None:
        pins = tmp_path / "pins.txt"
        pins.write_text("numpy==1.0.0\n", encoding="utf-8")
        problems = presenter_pins.check(pins, LOCK)
        assert any("numpy is pinned to 1.0.0" in problem for problem in problems)

    def test_excluded_package_is_rejected(self, tmp_path: Path) -> None:
        pins = tmp_path / "pins.txt"
        pins.write_text("onnxruntime==1.23.2\n", encoding="utf-8")
        problems = presenter_pins.check(pins, LOCK)
        assert any("onnxruntime must not be pinned" in problem for problem in problems)

    def test_missing_closure_package_is_reported(self, tmp_path: Path) -> None:
        pins = tmp_path / "pins.txt"
        pins.write_text(PINS.read_text(encoding="utf-8").replace("numpy==1.26.4\n", ""), encoding="utf-8")
        problems = presenter_pins.check(pins, LOCK)
        assert any("numpy==1.26.4 is missing" in problem for problem in problems)

    def test_missing_lite_substitute_is_reported(self, tmp_path: Path) -> None:
        pins = tmp_path / "pins.txt"
        pins.write_text("numpy==1.26.4\n", encoding="utf-8")
        problems = presenter_pins.check(pins, LOCK)
        assert any("pyside6-essentials must be pinned" in problem for problem in problems)

    def test_package_outside_the_closure_is_reported(self, tmp_path: Path) -> None:
        pins = tmp_path / "pins.txt"
        pins.write_text(PINS.read_text(encoding="utf-8") + "requests==2.32.0\n", encoding="utf-8")
        problems = presenter_pins.check(pins, LOCK)
        assert any(
            "requests is pinned but not part of the Presenter dependency closure" in problem for problem in problems
        )

    def test_duplicate_pin_is_rejected(self, tmp_path: Path) -> None:
        pins = tmp_path / "pins.txt"
        pins.write_text("numpy==1.26.4\nnumpy==1.26.4\n", encoding="utf-8")
        with pytest.raises(presenter_pins.PinError, match="pinned more than once"):
            presenter_pins.pins_map(pins)

    def test_marker_split_uses_the_presenter_build_environment(self) -> None:
        """scipy resolves to two versions in the lock; the 3.11 one is the pin."""
        versions = presenter_pins.lock_versions(LOCK)
        assert versions["scipy"] == {"1.17.1"}
        assert presenter_pins.marker_applies("python_full_version >= '3.11'") is True
        assert presenter_pins.marker_applies("python_full_version < '3.11'") is False
        assert presenter_pins.marker_applies("python_full_version < '3.11' or sys_platform == 'linux'") is True
        assert presenter_pins.marker_applies("python_full_version >= '3.11' and platform_machine == 'aarch64'") is False
        with pytest.raises(presenter_pins.PinError, match="unknown marker variable"):
            presenter_pins.marker_applies("python_implementation == 'CPython'")

    def test_version_ordering_is_numeric_not_lexical(self) -> None:
        assert presenter_pins.marker_applies("python_full_version >= '3.9'") is True
        assert presenter_pins.marker_applies("python_full_version < '3.9'") is False
        assert presenter_pins.marker_applies("python_full_version > '3.11.2'") is True

    def test_unsupported_pin_line_is_rejected(self, tmp_path: Path) -> None:
        pins = tmp_path / "pins.txt"
        pins.write_text("numpy>=2\n", encoding="utf-8")
        with pytest.raises(presenter_pins.PinError, match="not a `name==version` pin"):
            presenter_pins.parse_pins(pins)

    def test_rewrite_regenerates_the_body_and_keeps_the_header(self, tmp_path: Path) -> None:
        pins = tmp_path / "pins.txt"
        pins.write_text("# header line\n\nnumpy==0.0.1\n", encoding="utf-8")
        body = presenter_pins.rewrite(pins, LOCK)
        text = pins.read_text(encoding="utf-8")
        assert text.startswith("# header line")
        assert "numpy==1.26.4" in body
        assert presenter_pins.check(pins, LOCK) == []

    def test_cli_reports_success_on_the_shipped_files(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert presenter_pins.main(["--pins", str(PINS)]) == 0
        assert "presenter pins OK" in capsys.readouterr().out

    def test_cli_reports_drift_with_a_fix_hint(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pins = tmp_path / "pins.txt"
        pins.write_text("numpy==1.0.0\n", encoding="utf-8")
        assert presenter_pins.main(["--pins", str(pins), "--lock", str(LOCK)]) == 1
        assert "--write" in capsys.readouterr().err


# ── workflow policy ──────────────────────────────────────────────────


class TestWorkflowLockPolicy:
    def test_dependabot_updates_the_uv_lock(self) -> None:
        config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
        updates = config["updates"]
        assert not any(update["package-ecosystem"] == "pip" for update in updates)
        uv = [update for update in updates if update["package-ecosystem"] == "uv"]
        assert len(uv) == 1
        assert uv[0]["directory"] == "/"
        # NumPy 2 needs its own numerical validation, not an automated bump.
        assert any(
            rule["dependency-name"] == "numpy" and "version-update:semver-major" in rule.get("update-types", [])
            for rule in uv[0]["ignore"]
        )

    @pytest.mark.parametrize("name", PACKAGING_WORKFLOWS)
    def test_no_editable_or_floating_install(self, name: str) -> None:
        scripts = _run_scripts(_workflow(name))
        assert "pip install -e" not in scripts
        for line in scripts.splitlines():
            stripped = line.strip()
            if stripped.startswith("pip install") or " python -m pip install" in stripped:
                # A pip install is only allowed when it names a locked version.
                assert "locked_version.py" in stripped, stripped

    @pytest.mark.parametrize("name", PACKAGING_WORKFLOWS)
    def test_the_uv_action_and_python_are_pinned(self, name: str) -> None:
        workflow = _workflow(name)
        assert workflow["env"]["UV_PYTHON_DOWNLOADS"] == "never"
        assert workflow["env"]["PY_VERSION"] == "3.11"

        # Check the policy, not a release-specific SHA that Dependabot cannot
        # update here. Every invocation must be immutable and agree with CI.
        def uv_actions(document: dict) -> list[str]:
            return [
                step["uses"]
                for job in document["jobs"].values()
                for step in job.get("steps", [])
                if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
            ]

        actions = uv_actions(workflow)
        ci_actions = uv_actions(_workflow("ci.yml"))
        assert actions and ci_actions
        assert all(re.fullmatch(r"astral-sh/setup-uv@[0-9a-f]{40}", action) for action in actions + ci_actions)
        assert len(set(actions + ci_actions)) == 1

    @pytest.mark.parametrize("name", ["build.yml", "release.yml", "benchmark.yml", "ste-fixtures.yml"])
    def test_packaging_jobs_sync_from_the_lock(self, name: str) -> None:
        assert "uv sync --locked" in _workflow_text(name)

    def test_release_and_build_use_the_build_extra_from_the_lock(self) -> None:
        for name in ("build.yml", "release.yml"):
            assert "uv sync --locked --extra build" in _workflow_text(name)

    def test_presenter_installs_its_lock_checked_pins_not_a_floating_set(self) -> None:
        text = _workflow_text("presenter.yml")
        assert "build/presenter/pinned-packages.txt" in text
        assert "tools/release/presenter_pins.py" in text
        assert "locked_version.py pyinstaller" in text
        assert "locked_version.py cyclonedx-bom" in text

    def test_every_packaging_workflow_runs_the_package_smoke(self) -> None:
        for name in ("build.yml", "release.yml", "presenter.yml"):
            assert "tools/release/run_package_smoke.py" in _workflow_text(name), name

    def test_presenter_builds_check_their_pins_before_building(self) -> None:
        jobs = _workflow("presenter.yml")["jobs"]
        for job in ("build-windows", "build-linux"):
            steps = jobs[job]["steps"]
            names = [str(step.get("name", "")) for step in steps]
            scripts = " ".join(str(step.get("run", "")) for step in steps)
            assert "tools/release/presenter_pins.py" in scripts, job
            check_index = next(
                index for index, step in enumerate(steps) if "presenter_pins.py" in str(step.get("run", ""))
            )
            build_index = next(
                index
                for index, step in enumerate(steps)
                if "PyInstaller" in str(step.get("run", "")) or "build-appimage.sh" in str(step.get("run", ""))
            )
            assert check_index < build_index, (job, names)

    def test_the_presenter_smoke_runs_the_lite_profile(self) -> None:
        text = _workflow_text("presenter.yml")
        assert "--profile presenter" in text
        assert "--runner artifact" in text  # the shipped exe/AppImage, not an import

    def test_full_profile_smokes_run_the_packaged_executable(self) -> None:
        text = _workflow_text("release.yml")
        assert "dist/SonoForge/SonoForge.exe" in text  # onedir installer payload
        assert "SonoForge.app/Contents/MacOS/SonoForge" in text  # macOS bundle
        assert "dpkg-deb -x" in text  # lite .deb payload

    def test_build_records_are_written_for_every_packaged_asset(self) -> None:
        matrix = package_matrix.load(MATRIX_PATH)
        combos = {(asset["profile"], asset["platform"]) for asset in package_matrix.assets_for(matrix, "9.9.9")}
        texts = (_workflow_text("release.yml") + _workflow_text("presenter.yml")).replace("\n", " ")
        squashed = " ".join(texts.split())
        for profile, platform in combos:
            assert f"--profile {profile} --platform {platform}" in squashed, (profile, platform)

    def test_every_packaged_asset_declares_its_smoke_evidence(self) -> None:
        matrix = package_matrix.load(MATRIX_PATH)
        rows = {asset["name"]: asset for asset in package_matrix.assets_for(matrix, "9.9.9")}
        assert rows["sonoforge_9.9.9_amd64.deb"]["smoke"] == "payload"
        assert rows["SonoForge-9.9.9-macos-arm64.dmg"]["smoke"] == "artifact"
        assert rows["SonoForgePresenter-9.9.9.exe"]["smoke"] == "artifact"

    def test_published_assets_are_verified_after_publishing(self) -> None:
        release = _workflow_text("release.yml")
        presenter = _workflow_text("presenter.yml")
        for text in (release, presenter):
            assert "tools/release/verify_release.py" in text
            assert "gh release download" in text
            assert "--attestations" in text
        assert "--profile full" in release
        assert "--profile presenter" in presenter
        # Verification must happen after the release exists, not instead of it.
        assert release.index("Create GitHub Release") < release.index("tools/release/verify_release.py")

    def test_sboms_are_bound_to_a_version_deterministic_serial(self) -> None:
        for name in ("release.yml", "presenter.yml"):
            text = _workflow_text(name)
            assert "--spec-version 1.6" in text
            assert "releases/tag/v" in text  # uuid5 serialNumber injection
            assert "--output-reproducible" in text

    def test_the_release_workflow_supports_build_and_verify_without_publishing(self) -> None:
        workflow = _workflow("release.yml")
        assert "verify_only" in str(workflow[True]["workflow_dispatch"]["inputs"])
        release_job = workflow["jobs"]["release"]
        assert "verify_only" in str(release_job["if"])

    def test_ci_requires_the_package_smoke(self) -> None:
        workflow = _workflow("ci.yml")
        assert "package_smoke" in workflow["jobs"]
        aggregate = workflow["jobs"]["test"]
        assert "package_smoke" in aggregate["needs"]
        gate = " ".join(str(step.get("run", "")) for step in aggregate["steps"])
        assert "PACKAGE_SMOKE_RESULT" in gate
        smoke_job = " ".join(str(step.get("run", "")) for step in workflow["jobs"]["package_smoke"]["steps"])
        assert "tools/release/run_package_smoke.py" in smoke_job
        assert "uv sync --locked" in smoke_job

    def test_ci_build_job_is_locked(self) -> None:
        build = _workflow("ci.yml")["jobs"]["build"]
        scripts = " ".join(str(step.get("run", "")) for step in build["steps"])
        assert "uv sync --locked --extra build" in scripts
        assert "uv run --no-sync python -m hatchling build" in scripts
        assert "pip install hatch" not in scripts
