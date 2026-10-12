"""N-07 product-profile and portable-media acceptance tests.

These tests pin the Full/Presenter capability matrix and exercise the same
storage roots used by the packaged builds. The read-only case simulates the
filesystem returning EROFS for a portable measurement-store write; the critical
acceptance criterion is that the failure stays on the portable root and never
falls back to the test host's application-data directory.
"""

from __future__ import annotations

import builtins
import errno
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from echo_personal_tool.infrastructure import profile


@pytest.fixture(autouse=True)
def _isolate_profile_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(profile.PROFILE_ENV, profile.PROFILE_FULL)
    monkeypatch.setenv(profile.PORTABLE_ENV, "0")
    monkeypatch.delenv(profile.PORTABLE_DIR_ENV, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "host-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "host-data"))


def test_capability_matrix_pins_full_and_presenter_contract() -> None:
    full = profile.capabilities_for(profile.PROFILE_FULL)
    presenter = profile.capabilities_for(profile.PROFILE_PRESENTER)

    assert full.recent_folders and full.recent_studies and full.continue_last_session
    assert full.measurement_storage and full.measurement_storage_default
    assert full.tabs and full.calculators and full.server_dialog
    assert full.ai_segmentation and full.reference_ui and not full.presenter_view
    assert not full.portable_storage_default

    assert not presenter.recent_folders and not presenter.recent_studies
    assert not presenter.continue_last_session
    assert presenter.measurement_storage and not presenter.measurement_storage_default
    assert presenter.tabs and presenter.calculators and presenter.server_dialog
    assert not presenter.ai_segmentation and not presenter.reference_ui and presenter.presenter_view
    assert presenter.portable_storage_default


def test_full_portable_settings_and_data_paths_stay_on_the_stick(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stick = tmp_path / "usb" / "SonoForgePresenter-data"
    monkeypatch.setenv(profile.PORTABLE_ENV, "1")
    monkeypatch.setenv(profile.PORTABLE_DIR_ENV, str(stick))

    # Cover the ordinary preferences store and the three historical direct
    # QSettings call sites that previously bypassed portable mode.
    settings_specs = (
        ("sonoforge", "preferences", "probe/preferences"),
        ("sonoforge", "server", "probe/server"),
        ("sonoforge", "secrets", "probe/secrets"),
        ("sonoforge", "loader_dialog", "probe/loader-dialog"),
        ("SonoForge", "StrainWindow", "probe/strain"),
        ("sonoforge", "ase-reference", "probe/reference"),
    )
    for organization, application, key in settings_specs:
        settings = profile.qsettings_for(organization, application)
        settings.setValue(key, "on-stick")
        settings.sync()
        expected = stick / f"{application}.ini"
        assert Path(settings.fileName()) == expected
        assert expected.is_file()

    default_settings = profile.qsettings_default()
    default_settings.setValue("probe/default-reference-columns", "on-stick")
    default_settings.sync()
    assert Path(default_settings.fileName()) == stick / "preferences.ini"

    from echo_personal_tool.infrastructure.paths import measurements_dir, orthanc_cache_dir

    assert measurements_dir() == stick / "measurements"
    assert orthanc_cache_dir() == stick / "cache" / "orthanc"
    assert all(path.is_relative_to(stick) for path in stick.rglob("*.ini"))
    assert not (tmp_path / "host-config").exists()
    assert not (tmp_path / "host-data").exists()


def test_read_only_portable_settings_never_select_a_host_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from PySide6.QtCore import QSettings

    stick = tmp_path / "read-only-settings-usb"
    # A file cannot be used as a portable directory, so both Python's mkdir
    # and Qt's actual sync fail without relying on OS-specific chmod behavior.
    stick.write_text("simulated read-only USB root", encoding="utf-8")
    monkeypatch.setenv(profile.PORTABLE_ENV, "1")
    monkeypatch.setenv(profile.PORTABLE_DIR_ENV, str(stick))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "host-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "host-data"))

    settings = profile.qsettings_for("sonoforge", "preferences")
    settings.setValue("probe/read-only", "usb-only")
    settings.sync()
    default_settings = profile.qsettings_default()
    default_settings.setValue("probe/default-read-only", "usb-only")
    default_settings.sync()

    # QSettings keeps targeting the selected USB INI and surfaces an access
    # failure; it must never silently switch to the OS-managed host profile.
    assert Path(settings.fileName()) == stick / "preferences.ini"
    assert Path(default_settings.fileName()) == stick / "preferences.ini"
    assert settings.status() == QSettings.Status.AccessError
    assert default_settings.status() == QSettings.Status.AccessError
    assert stick.is_file()
    assert not (tmp_path / "host-config").exists()
    assert not (tmp_path / "host-data").exists()


def test_presenter_does_not_read_or_write_persistent_path_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from echo_personal_tool.application.download_history import DownloadHistory
    from echo_personal_tool.infrastructure.recent_store import RecentStore
    from echo_personal_tool.infrastructure.user_preferences import (
        load_user_preferences,
        save_user_preferences,
    )

    stick = tmp_path / "presenter-stick"
    monkeypatch.setenv(profile.PROFILE_ENV, profile.PROFILE_PRESENTER)
    monkeypatch.setenv(profile.PORTABLE_DIR_ENV, str(stick))
    monkeypatch.delenv(profile.PORTABLE_ENV, raising=False)  # Presenter defaults to portable.

    download_history = DownloadHistory()
    assert download_history.record(object()) is None
    assert download_history.records() == ()

    settings = profile.qsettings_for("sonoforge", "preferences")
    saved_recents = json.dumps([{"path": "/private/previous-machine/study", "pinned": True}])
    settings.setValue("recent_folders", saved_recents)
    settings.setValue("startup_mode", "last_folder")
    settings.setValue("last_opened_folder", "/private/previous-machine/study")
    settings.setValue("last_session_source", "folder")
    settings.sync()

    preferences = load_user_preferences()
    recent_store = RecentStore(settings)
    assert preferences.startup_mode == "empty"
    assert preferences.last_opened_folder == ""
    assert preferences.last_session_source == ""
    assert preferences.measurement_persistence_enabled is False
    assert recent_store.enabled is False
    assert recent_store.entries() == []
    assert recent_store.last_folder() == ""

    recent_store.record(tmp_path / "new-study")
    preferences.last_opened_folder = str(tmp_path / "new-study")
    preferences.last_session_source = "folder"
    preferences.startup_mode = "last_folder"
    preferences.measurement_persistence_enabled = True  # Presenter supports opt-in.
    save_user_preferences(preferences)
    settings.sync()

    # Legacy history on an existing stick is neither imported into the running
    # profile nor overwritten; newly selected paths are not saved. Explicit
    # opt-in for measurement storage remains a portable preference.
    assert settings.value("recent_folders") == saved_recents
    assert settings.value("startup_mode") == "last_folder"
    assert settings.value("last_opened_folder") == "/private/previous-machine/study"
    assert settings.value("last_session_source") == "folder"
    assert str(tmp_path / "new-study") not in (stick / "preferences.ini").read_text(encoding="utf-8")
    assert load_user_preferences().measurement_persistence_enabled is True
    assert not (tmp_path / "host-data" / "sonoforge").exists()


@pytest.fixture()
def qcoreapp():
    """Core event loop for persistence acceptance without loading the Qt GUI stack."""
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


@pytest.mark.gui
def test_presenter_start_page_hides_recent_studies_places_and_continue(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
    tmp_path: Path,
) -> None:
    from echo_personal_tool.infrastructure.recent_store import RecentFolder, RecentStore
    from echo_personal_tool.presentation.start_page import RecentStudySummary, StartPage

    monkeypatch.setenv(profile.PROFILE_ENV, profile.PROFILE_PRESENTER)
    capabilities = profile.capabilities_for()
    store = RecentStore(entries=[RecentFolder(str(tmp_path / "secret-study"))], enabled=False)
    page = StartPage(
        recent_store=store,
        profile_name=profile.PROFILE_PRESENTER,
        profile_capabilities=capabilities,
    )
    page.refresh_recent_places()
    page.set_recent_studies([RecentStudySummary("private-key", "private study", "sensitive details")])
    page.set_continue_target("folder", str(tmp_path / "secret-study"))

    assert page._places_card.isHidden()
    assert page._studies_card.isHidden()
    assert page._places_list.count() == 0
    assert page._studies_list.count() == 0
    assert page.continue_button.isHidden()
    page.close()


def test_presenter_read_only_measurements_never_fall_back_to_host_data(
    monkeypatch: pytest.MonkeyPatch,
    qcoreapp,
    tmp_path: Path,
) -> None:
    from echo_personal_tool.application.measurement_persistence import MeasurementPersistence
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore
    from echo_personal_tool.infrastructure.paths import measurements_dir

    stick = tmp_path / "read-only-usb"
    host_data = tmp_path / "host-data"
    monkeypatch.setenv(profile.PROFILE_ENV, profile.PROFILE_PRESENTER)
    monkeypatch.setenv(profile.PORTABLE_DIR_ENV, str(stick))
    monkeypatch.delenv(profile.PORTABLE_ENV, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(host_data))

    portable_measurements = measurements_dir()
    assert portable_measurements == stick / "measurements"
    portable_measurements.mkdir(parents=True)
    monkeypatch.setattr(
        "echo_personal_tool.application.measurement_persistence.describe_study",
        lambda _study: {"1.2.3.4": {"fingerprint": "a" * 64, "frames": 1, "spacing": [0.5, 0.5]}},
    )

    uid = "1.2.3"
    session = StudyMeasurementSessionStore()
    persistence = MeasurementPersistence(portable_measurements, session, enabled=True)
    persistence.load([SimpleNamespace(study_uid=uid)], lambda: None)
    assert persistence.flush()  # context/read succeeded on the portable path

    original_open = builtins.open
    lock_file = portable_measurements / ".writer.lock"

    def deny_portable_write(file, mode="r", *args, **kwargs):
        if Path(file) == lock_file and any(flag in mode for flag in ("w", "a", "+", "x")):
            raise OSError(errno.EROFS, "simulated read-only USB media", str(file))
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", deny_portable_write)
    session.set_patient_metrics(uid, 175, 72)
    assert persistence.flush() is False
    assert persistence.has_pending_edits  # failure is visible/retryable, not a false success
    assert list(portable_measurements.glob("*.json")) == []
    assert not (host_data / "sonoforge" / "measurements").exists()
    assert not host_data.exists() or not list(host_data.rglob("*.json"))

    assert persistence.discard_pending()
    assert persistence.close()
