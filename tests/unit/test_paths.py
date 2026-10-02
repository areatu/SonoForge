"""Tests for platform storage paths and the one-time legacy migration."""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.infrastructure import paths, profile


@pytest.fixture
def _full_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv(profile.PROFILE_ENV, profile.PROFILE_FULL)
    monkeypatch.setenv(profile.PORTABLE_ENV, "0")
    monkeypatch.delenv(profile.PORTABLE_DIR_ENV, raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return home


def test_linux_paths_respect_absolute_xdg_data_home(
    _full_profile: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_home = tmp_path / "xdg-data"
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))

    assert paths.data_dir() == data_home / "sonoforge"
    assert paths.models_dir() == data_home / "sonoforge" / "models"
    assert paths.cache_dir() == data_home / "sonoforge" / "cache"
    assert paths.orthanc_cache_dir() == data_home / "sonoforge" / "cache" / "orthanc"
    assert paths.logs_dir() == data_home / "sonoforge" / "logs"


def test_linux_ignores_relative_xdg_data_home(_full_profile: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _full_profile
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "relative/data")

    assert paths.data_dir() == home / ".local" / "share" / "sonoforge"


def test_windows_uses_local_app_data(_full_profile: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    local_app_data = tmp_path / "Local AppData"
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    assert paths.data_dir() == local_app_data / "SonoForge"


def test_windows_falls_back_to_home_appdata(_full_profile: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _full_profile
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", "")

    assert paths.data_dir() == home / "AppData" / "Local" / "SonoForge"


def test_macos_uses_application_support(_full_profile: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _full_profile
    monkeypatch.setattr(paths.sys, "platform", "darwin")

    assert paths.data_dir() == home / "Library" / "Application Support" / "SonoForge"


def test_portable_override_has_priority_over_platform_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    portable = tmp_path / "usb" / "sf-data"
    monkeypatch.setenv(profile.PROFILE_ENV, profile.PROFILE_PRESENTER)
    monkeypatch.setenv(profile.PORTABLE_ENV, "1")
    monkeypatch.setenv(profile.PORTABLE_DIR_ENV, str(portable))
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))

    assert paths.data_dir() == portable
    assert paths.models_dir() == portable / "models"
    assert paths.orthanc_cache_dir() == portable / "cache" / "orthanc"
    assert paths.logs_dir() == portable / "logs"


def test_migration_moves_old_models_cache_fonts_and_logs(
    _full_profile: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = _full_profile
    data_home = tmp_path / "new-xdg-data"
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))

    old_models = home / ".local" / "share" / "sonoforge" / "models"
    old_models.mkdir(parents=True)
    (old_models / "model_manifest.json").write_text("legacy manifest", encoding="utf-8")
    (old_models / "weights.onnx").write_bytes(b"model")

    old_cache = home / ".sonoforge" / "orthanc" / "session-1"
    old_cache.mkdir(parents=True)
    (old_cache / "instance.dcm").write_bytes(b"dicom")

    old_fonts = home / ".sonoforge" / "fonts"
    old_fonts.mkdir(parents=True)
    (old_fonts / "Inter-Regular.ttf").write_bytes(b"font")

    old_logs = home / "SonoForge" / "logs"
    old_logs.mkdir(parents=True)
    (old_logs / "errors.log").write_text("old log", encoding="utf-8")

    warnings = paths.migrate_legacy_paths()

    assert warnings == ()
    assert (paths.models_dir() / "model_manifest.json").read_text(encoding="utf-8") == "legacy manifest"
    assert (paths.models_dir() / "weights.onnx").read_bytes() == b"model"
    assert (paths.cache_dir() / "orthanc" / "session-1" / "instance.dcm").read_bytes() == b"dicom"
    assert (paths.fonts_cache_dir() / "Inter-Regular.ttf").read_bytes() == b"font"
    assert (paths.logs_dir() / "errors.log").read_text(encoding="utf-8") == "old log"
    assert (paths.data_dir() / paths._MIGRATION_MARKER).is_file()
    assert not old_models.exists()
    assert not old_cache.parent.exists()
    assert not old_fonts.exists()
    assert not old_logs.exists()


def test_windows_migrates_old_models_into_local_app_data(
    _full_profile: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = _full_profile
    local_app_data = tmp_path / "local-app-data"
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    old_models = home / ".local" / "share" / "sonoforge" / "models"
    old_models.mkdir(parents=True)
    (old_models / "model_manifest.json").write_text("{}", encoding="utf-8")
    (old_models / "weights.onnx").write_bytes(b"weights")

    assert paths.migrate_legacy_paths() == ()
    assert paths.models_dir() == local_app_data / "SonoForge" / "models"
    assert (paths.models_dir() / "weights.onnx").read_bytes() == b"weights"
    assert not old_models.exists()


def test_migration_does_not_overwrite_and_runs_only_once(
    _full_profile: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = _full_profile
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))

    new_models = paths.models_dir()
    new_models.mkdir(parents=True)
    (new_models / "model_manifest.json").write_text("new", encoding="utf-8")
    old_models = home / ".local" / "share" / "sonoforge" / "models"
    old_models.mkdir(parents=True)
    (old_models / "model_manifest.json").write_text("old", encoding="utf-8")
    (old_models / "legacy-weights.onnx").write_bytes(b"legacy")

    warnings = paths.migrate_legacy_paths()

    assert warnings
    assert (new_models / "model_manifest.json").read_text(encoding="utf-8") == "new"
    assert (new_models / "legacy-weights.onnx").read_bytes() == b"legacy"
    assert (old_models / "model_manifest.json").read_text(encoding="utf-8") == "old"
    assert (paths.data_dir() / paths._MIGRATION_MARKER).is_file()

    late_legacy_file = home / ".sonoforge" / "orthanc" / "late-session" / "instance.dcm"
    late_legacy_file.parent.mkdir(parents=True)
    late_legacy_file.write_bytes(b"later")
    assert paths.migrate_legacy_paths() == ()
    assert late_legacy_file.is_file()


def test_portable_mode_does_not_move_host_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(profile.PROFILE_ENV, profile.PROFILE_PRESENTER)
    monkeypatch.setenv(profile.PORTABLE_ENV, "1")
    monkeypatch.setenv(profile.PORTABLE_DIR_ENV, str(tmp_path / "usb"))
    old_cache = home / ".sonoforge" / "orthanc" / "session-1"
    old_cache.mkdir(parents=True)
    (old_cache / "instance.dcm").write_bytes(b"dicom")

    assert paths.migrate_legacy_paths() == ()
    assert (old_cache / "instance.dcm").is_file()
    assert not (tmp_path / "usb" / paths._MIGRATION_MARKER).exists()


def test_legacy_models_and_cache_remain_readable_until_migrated(
    _full_profile: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = _full_profile
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    old_models = home / ".local" / "share" / "sonoforge" / "models"
    old_models.mkdir(parents=True)
    (old_models / "model_manifest.json").write_text("{}", encoding="utf-8")
    old_cache = home / ".sonoforge" / "orthanc"
    old_cache.mkdir(parents=True)

    assert paths.models_dirs_for_read() == (paths.models_dir(), old_models)
    assert paths.orthanc_cache_dir() == old_cache
    assert profile.orthanc_cache_root() == old_cache


def test_profile_log_helper_uses_canonical_path(
    _full_profile: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))

    assert profile.diag_log_dir() == paths.logs_dir()
