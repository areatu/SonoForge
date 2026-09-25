"""Tests for the SonoForge Presenter (lite) profile.

Covers: profile flags, portable storage resolution, portable QSettings /
secrets round-trips, the guarded onnxruntime import and profile-based
menu filtering (AI buttons hidden under presenter).
"""

from __future__ import annotations

import os

import pytest

from echo_personal_tool.infrastructure import profile

pytestmark = pytest.mark.gui

_ENV_VARS = (profile.PROFILE_ENV, profile.PORTABLE_ENV, profile.PORTABLE_DIR_ENV)


@pytest.fixture(autouse=True)
def _clean_profile_env(monkeypatch: pytest.MonkeyPatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


# ── Profile flags ───────────────────────────────────────────────────


class TestProfileFlags:
    def test_default_profile_is_full(self):
        assert profile.profile() == profile.PROFILE_FULL
        assert not profile.is_presenter()
        assert profile.has_ai_segmentation()
        assert profile.has_reference_ui()
        assert not profile.portable_enabled()
        assert profile.portable_root() is None
        assert profile.display_name() == "SonoForge"

    def test_presenter_via_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(profile.PROFILE_ENV, "presenter")
        assert profile.is_presenter()
        assert not profile.has_ai_segmentation()
        assert not profile.has_reference_ui()
        assert profile.display_name() == "SonoForge Presenter"

    def test_portable_follows_profile(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(profile.PROFILE_ENV, "presenter")
        assert profile.portable_enabled()
        monkeypatch.setenv(profile.PORTABLE_ENV, "0")
        assert not profile.portable_enabled()

    def test_portable_can_be_enabled_in_full_profile(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(profile.PORTABLE_ENV, "1")
        assert profile.portable_enabled()
        assert not profile.is_presenter()


# ── Portable root resolution ────────────────────────────────────────


class TestPortableRoot:
    def test_explicit_dir_env_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        monkeypatch.setenv(profile.PORTABLE_ENV, "1")
        monkeypatch.setenv(profile.PORTABLE_DIR_ENV, str(tmp_path / "stick"))
        assert profile.portable_root() == tmp_path / "stick"
        assert profile.portable_path("settings.ini") == tmp_path / "stick" / "settings.ini"

    def test_appimage_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        monkeypatch.setenv(profile.PORTABLE_ENV, "1")
        appimage = tmp_path / "SonoForge-Presenter-0.3.0-x86_64.AppImage"
        appimage.touch()
        monkeypatch.setenv("APPIMAGE", str(appimage))
        root = profile.portable_root()
        assert root is not None
        assert root.parent == tmp_path
        assert root.name == profile.PORTABLE_DIR_NAME

    def test_dev_fallback_is_cwd(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        monkeypatch.setenv(profile.PORTABLE_ENV, "1")
        monkeypatch.chdir(tmp_path)
        root = profile.portable_root()
        assert root == tmp_path / profile.PORTABLE_DIR_NAME

    def test_paths_are_none_when_disabled(self):
        assert profile.settings_ini_path() is None
        assert profile.servers_ini_path() is None
        assert profile.secrets_path() is None

    def test_host_paths_untouched_when_not_portable(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
        diag = profile.diag_log_dir()
        orthanc = profile.orthanc_cache_root()
        assert profile.portable_root() is None
        assert "SonoForgePresenter-data" not in str(diag)
        assert "SonoForgePresenter-data" not in str(orthanc)


# ── Portable stores (QSettings + secrets) ───────────────────────────


class TestPortableStores:
    @pytest.fixture
    def portable_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        monkeypatch.setenv(profile.PROFILE_ENV, "presenter")
        monkeypatch.setenv(profile.PORTABLE_DIR_ENV, str(tmp_path / "stick"))
        return tmp_path / "stick"

    def test_qsettings_for_uses_ini_on_stick(self, portable_dir):
        settings = profile.qsettings_for("sonoforge", "preferences")
        settings.setValue("probe", "42")
        settings.sync()
        ini = portable_dir / "preferences.ini"
        assert ini.is_file()
        assert "probe" in ini.read_text(encoding="utf-8")

    def test_user_preferences_roundtrip_on_stick(self, portable_dir):
        from echo_personal_tool.infrastructure.user_preferences import (
            load_user_preferences,
            save_user_preferences,
        )

        prefs = load_user_preferences()
        prefs.language = "ru"
        prefs.ui_font_size = 13
        save_user_preferences(prefs)
        assert (portable_dir / "preferences.ini").is_file()

        reloaded = load_user_preferences()
        assert reloaded.language == "ru"
        assert reloaded.ui_font_size == 13

    def test_server_settings_roundtrip_on_stick(self, portable_dir):
        from echo_personal_tool.infrastructure.server_settings import (
            ServerSettings,
            load_server_settings,
            save_server_settings,
        )

        settings = ServerSettings(
            description="Demo PACS",
            url="http://10.0.0.5:8042/dicom-web",
            username="demo",
            password="s3cret",
        )
        save_server_settings(settings)
        assert (portable_dir / "server.ini").is_file()

        secrets_file = portable_dir / "secrets.ini"
        assert secrets_file.is_file(), "password must be stored on the stick"
        raw = secrets_file.read_text(encoding="utf-8")
        assert "demo" in raw
        assert "s3cret" not in raw, "password must not be stored in plain text"

        reloaded = load_server_settings()
        assert reloaded.url == "http://10.0.0.5:8042/dicom-web"
        assert reloaded.username == "demo"
        assert reloaded.password == "s3cret"

    def test_password_deletion_removes_secret(self, portable_dir):
        from echo_personal_tool.infrastructure.server_settings import (
            ServerSettings,
            save_server_settings,
        )

        save_server_settings(ServerSettings(username="demo", password="pw"))
        secrets_file = portable_dir / "secrets.ini"
        assert "demo" in secrets_file.read_text(encoding="utf-8")

        save_server_settings(ServerSettings(username="demo", password=""))
        assert "demo" not in secrets_file.read_text(encoding="utf-8")

    def test_secret_is_fernet_token_and_device_key_created(self, portable_dir):
        from echo_personal_tool.infrastructure.server_settings import (
            ServerSettings,
            save_server_settings,
        )

        save_server_settings(ServerSettings(username="demo", password="s3cret"))
        raw = (portable_dir / "secrets.ini").read_text(encoding="utf-8")
        assert "gAAAA" in raw, "expected a Fernet (versioned base64) token"
        assert "s3cret" not in raw
        assert (portable_dir / "device.key").is_file(), "per-device key material must stay on the stick"
        if os.name == "posix":
            assert (portable_dir / "secrets.ini").stat().st_mode & 0o777 == 0o600

    def test_without_cryptography_password_is_not_persisted(self, portable_dir, monkeypatch):
        from echo_personal_tool.infrastructure import server_settings as ss

        # Simulate a full-profile install without the 'presenter' extra.
        monkeypatch.setattr(ss, "_portable_fernet", lambda: None)
        ss.save_server_settings(ss.ServerSettings(username="demo", password="s3cret", url="http://pacs:8042"))

        secrets_file = portable_dir / "secrets.ini"
        if secrets_file.is_file():
            assert "demo" not in secrets_file.read_text(encoding="utf-8")

        reloaded = ss.load_server_settings()
        assert reloaded.url == "http://pacs:8042", "non-secret fields must still persist"
        assert reloaded.password == "", "no clear-text fallback may exist"

    def test_orthanc_cache_and_logs_on_stick(self, portable_dir):
        assert profile.orthanc_cache_root().is_relative_to(portable_dir)
        assert profile.diag_log_dir().is_relative_to(portable_dir)


# ── Guarded ONNX engine ─────────────────────────────────────────────


class TestOnnxGuard:
    def test_engine_reports_unavailable_without_ort(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        from echo_personal_tool.infrastructure import onnx_engine

        monkeypatch.setattr(onnx_engine, "ort", None)
        engine = onnx_engine.OnnxInferenceEngine(models_dir=tmp_path)
        assert not engine.is_available()

    def test_create_session_raises_without_ort(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        from echo_personal_tool.infrastructure import onnx_engine

        monkeypatch.setattr(onnx_engine, "ort", None)
        with pytest.raises(RuntimeError, match="onnxruntime"):
            onnx_engine._create_session(tmp_path / "model.onnx")


# ── Menu filtering under presenter ──────────────────────────────────


class TestMenuFiltering:
    def _action_values(self, menu) -> set[str]:
        return {str(btn.action) for _, buttons in menu for btn in buttons}

    def test_full_profile_keeps_ai_buttons(self):
        from echo_personal_tool.presentation.measures_menu import _MENU, _filter_menu

        values = self._action_values(_filter_menu(_MENU, None))
        assert "lav_4c_ai_plus" in values
        assert "lav_4c_auto" in values

    def test_presenter_hides_ai_buttons(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(profile.PROFILE_ENV, "presenter")
        from echo_personal_tool.presentation.measures_menu import _MENU, _filter_menu

        values = self._action_values(_filter_menu(_MENU, None))
        assert "lav_4c_ai_plus" not in values
        assert "lav_4c_auto" not in values
        # non-ONNX tools survive
        assert "mbs_simpson" in values
        assert "speckle_tracking" in values
