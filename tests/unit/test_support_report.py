"""Tests for the prefilled "report a problem" link (Q-13)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from echo_personal_tool import __version__
from echo_personal_tool.infrastructure.support_report import (
    BUG_TEMPLATE,
    ISSUE_BASE_URL,
    MAX_URL_CHARS,
    OS_OPTIONS,
    build_issue_url,
    default_bundle_path,
    detect_os_option,
    environment_text,
)


def _params(url: str) -> dict[str, str]:
    query = urlsplit(url).query
    return {key: values[0] for key, values in parse_qs(query, keep_blank_values=True).items()}


class TestOsDetection:
    def test_windows_11_by_build_number(self) -> None:
        assert detect_os_option(system="Windows", machine="AMD64", build=26100) == "Windows 11"

    def test_windows_10_below_the_build_cut(self) -> None:
        assert detect_os_option(system="Windows", machine="AMD64", build=19045) == "Windows 10"

    def test_windows_without_a_build_number_is_not_guessed(self) -> None:
        # Off Windows there is no build to read: an empty dropdown beats a wrong one.
        assert detect_os_option(system="Windows", machine="AMD64", build=None) == ""

    @pytest.mark.parametrize(
        ("machine", "expected"),
        [("arm64", "macOS (Apple Silicon)"), ("aarch64", "macOS (Apple Silicon)"), ("x86_64", "macOS (Intel)")],
    )
    def test_macos_by_architecture(self, machine: str, expected: str) -> None:
        assert detect_os_option(system="Darwin", machine=machine) == expected

    @pytest.mark.parametrize("distro", ["ubuntu", "debian", "linuxmint pop", '"debian"'])
    def test_debian_family(self, distro: str) -> None:
        assert detect_os_option(system="Linux", machine="x86_64", distro_id=distro) == "Linux (Ubuntu/Debian)"

    def test_other_linux(self) -> None:
        assert detect_os_option(system="Linux", machine="x86_64", distro_id="fedora") == "Linux (other)"

    def test_unknown_platform_is_empty(self) -> None:
        assert detect_os_option(system="Plan9", machine="mips") == ""

    def test_detected_value_matches_the_issue_template(self) -> None:
        detected = detect_os_option()
        assert detected == "" or detected in OS_OPTIONS


class TestBuildIssueUrl:
    def test_base_fields_are_prefilled(self) -> None:
        url = build_issue_url(os_option="Windows 11", version="9.9.9", additional="SonoForge version: 9.9.9")
        assert url.startswith(ISSUE_BASE_URL + "?")
        params = _params(url)
        assert params["template"] == BUG_TEMPLATE
        assert params["title"] == "[Bug]: "
        assert params["labels"] == "bug"
        assert params["os"] == "Windows 11"
        assert params["version"] == "9.9.9"
        assert params["additional"] == "SonoForge version: 9.9.9"

    def test_version_defaults_to_the_running_build(self) -> None:
        assert _params(build_issue_url(os_option=""))["version"] == __version__

    def test_empty_fields_are_omitted(self) -> None:
        params = _params(build_issue_url(os_option="", description="  ", logs=""))
        assert "os" not in params
        assert "description" not in params
        assert "logs" not in params

    def test_cyrillic_and_spaces_are_percent_encoded(self) -> None:
        url = build_issue_url(os_option="", description="Не открывается папка")
        assert " " not in urlsplit(url).query
        assert _params(url)["description"] == "Не открывается папка"

    def test_long_fields_are_trimmed_under_the_url_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import echo_personal_tool.infrastructure.support_report as support_report

        monkeypatch.setattr(support_report, "MAX_URL_CHARS", 6000)
        url = support_report.build_issue_url(
            os_option="Linux (other)",
            description="keep me",
            steps="S" * 20000,
            expected="E" * 20000,
            logs="L" * 20000,
            additional="A" * 20000,
        )
        assert len(url) <= 6000
        params = _params(url)
        # The least useful field is sacrificed first; the user's own text stays.
        assert params["description"] == "keep me"
        assert params["logs"].endswith("[trimmed]")
        assert len(params["logs"]) < len(params["additional"]) == len(params["steps"])

    def test_extreme_trimming_keeps_the_description(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import echo_personal_tool.infrastructure.support_report as support_report

        monkeypatch.setattr(support_report, "MAX_URL_CHARS", 400)
        url = support_report.build_issue_url(
            os_option="Linux (other)",
            description="The folder with Samsung clips does not open",
            steps="S" * 20000,
            logs="L" * 20000,
        )
        params = _params(url)
        assert params["description"] == "The folder with Samsung clips does not open"
        assert "logs" not in params

    def test_a_single_field_is_capped_before_the_url_limit(self) -> None:
        from echo_personal_tool.infrastructure.support_report import MAX_FIELD_CHARS

        params = _params(build_issue_url(os_option="", additional="A" * (MAX_FIELD_CHARS * 10)))
        assert len(params["additional"]) <= MAX_FIELD_CHARS

    def test_a_single_oversized_field_still_fits(self) -> None:
        url = build_issue_url(os_option="", description="D" * 50000)
        assert len(url) <= MAX_URL_CHARS
        assert _params(url)["description"].startswith("D")


class TestEnvironmentText:
    def test_contains_the_allowlisted_runtime_summary(self) -> None:
        text = environment_text(None)
        assert f"SonoForge version: {__version__}" in text
        assert "Operating system:" in text
        assert "Diagnostic bundle: not created" in text

    def test_bundle_name_is_reported_without_its_directory(self) -> None:
        text = environment_text(None, bundle_name=str(Path("/home/someone/Downloads") / "SonoForge-diagnostics.zip"))
        assert "SonoForge-diagnostics.zip" in text
        assert "/home/someone" not in text
        assert "Downloads" not in text

    def test_no_home_directory_or_study_path_leaks(self) -> None:
        text = environment_text(None)
        assert str(Path.home()) not in text


class TestDefaultBundlePath:
    def test_uses_the_given_directory_and_a_timestamped_name(self, tmp_path: Path) -> None:
        path = default_bundle_path(now=datetime(2026, 10, 7, 13, 45, 9), base_dir=tmp_path)
        assert path.parent == tmp_path
        assert path.name == "SonoForge-diagnostics-20261007-134509.zip"

    def test_falls_back_to_a_writable_standard_location(self) -> None:
        path = default_bundle_path()
        assert path.name.startswith("SonoForge-diagnostics-")
        assert path.suffix == ".zip"
