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
    calls: list[list[str]] = []

    def record_run(command: list[str], **kwargs):
        calls.append(command)
        return original_run(command, **kwargs)

    monkeypatch.setattr(generator.subprocess, "run", record_run)
    ignored = root / ".cache" / "nested path" / "кино"
    assert generator.validate_output(ignored) == ignored
    assert calls[-1] == ["git", "check-ignore", "-q", "--", ".cache/nested path/кино/"]
    with pytest.raises(ValueError, match="Git-ignored"):
        generator.validate_output(root / "tracked-phantom-output")
    assert calls[-1] == ["git", "check-ignore", "-q", "--", "tracked-phantom-output/"]
    assert all(not Path(command[-1]).is_absolute() and "\\" not in command[-1] for command in calls)
    assert not ignored.exists()


def test_git_guard_fails_closed_on_git_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "not-a-git-repository"
    root.mkdir()
    monkeypatch.setattr(generator, "ROOT", root)
    # A missing/broken Git repository must never grant permission to write inside it.
    with pytest.raises(ValueError, match="Git-ignored"):
        generator.validate_output(root / "new-output")
    assert not (root / "new-output").exists()
