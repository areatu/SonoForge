"""Portable Git pathspecs and fail-closed synthetic output directory checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts import generate_synthetic_echo_corpus as generator


def test_git_guard_uses_relative_forward_slash_directory_pathspec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text(".cache/\n", encoding="utf-8")
    monkeypatch.setattr(generator, "ROOT", root)
    original_run = subprocess.run
    calls: list[tuple[list[str], bytes]] = []

    def record_run(command: list[str], **kwargs):
        calls.append((command, kwargs["input"]))
        return original_run(command, **kwargs)

    monkeypatch.setattr(generator.subprocess, "run", record_run)
    ignored = root / ".cache" / "nested path" / "кино"
    assert generator.validate_output(ignored) == ignored
    assert calls[-1] == (["git", "check-ignore", "--verbose", "-z", "--stdin"], ".cache/nested path/кино/\0".encode())
    with pytest.raises(ValueError, match="Git-ignored"):
        generator.validate_output(root / "tracked-phantom-output")
    assert calls[-1][1] == b"tracked-phantom-output/\0"
    assert all(not Path(path.decode().strip("\0")).is_absolute() and b"\\" not in path for _, path in calls)
    assert not ignored.exists()


def test_git_guard_fails_closed_on_git_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "not-a-git-repository"
    root.mkdir()
    monkeypatch.setattr(generator, "ROOT", root)
    with pytest.raises(ValueError, match="Git-ignored"):
        generator.validate_output(root / "new-output")
    assert not (root / "new-output").exists()


@pytest.mark.parametrize(
    "stdout",
    [
        b"",
        b"malformed\0",
        b".gitignore\x001\x00!new-output/\x00new-output/\x00",
        b".gitignore\x001\x00*\x00other-output/\x00",
    ],
)
def test_success_exit_code_without_positive_ignore_evidence_is_not_permission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: bytes,
) -> None:
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setattr(generator.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout, b""))
    with pytest.raises(ValueError, match="Git-ignored"):
        generator.validate_output(tmp_path / "new-output")
    assert not (tmp_path / "new-output").exists()


@pytest.mark.parametrize("rule_source", ["global", "info-exclude"])
def test_only_project_gitignore_can_authorize_in_repository_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rule_source: str,
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    if rule_source == "global":
        rules = tmp_path / "global-ignore"
        rules.write_text("*output*/\n")
        subprocess.run(["git", "config", "core.excludesFile", str(rules)], cwd=root, check=True)
    else:
        (root / ".git" / "info" / "exclude").write_text("*output*/\n")
    (root / ".gitignore").write_text(".cache/\n")
    monkeypatch.setattr(generator, "ROOT", root)
    with pytest.raises(ValueError, match="Git-ignored"):
        generator.validate_output(root / "new-output")
    assert generator.validate_output(root / ".cache" / "new-output") == root / ".cache" / "new-output"
