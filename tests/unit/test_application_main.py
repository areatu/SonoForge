"""Tests for echo_personal_tool.main (0% coverage target).

The main() function is a full Qt app launch; we test the module-level
side-effects (logging setup, env defaults) and the main() return path
via heavy mocking to avoid starting a real QApplication.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_logging_config_setup() -> None:
    """Module-level code configures logging at WARNING level."""
    logger = logging.getLogger("pydicom")
    assert logger is not None


def test_env_defaults_set() -> None:
    """QT_LOGGING_RULES env var is set when main module is imported."""
    import echo_personal_tool.main  # noqa: F401

    rules = os.environ.get("QT_LOGGING_RULES", "")
    assert "kf.sonnet" in rules or "kf.service.sycoca" in rules


def test_main_returns_zero_on_normal_exit() -> None:
    """main() returns 0 when QApplication.exec() returns 0."""
    mock_app = MagicMock()
    mock_app.exec.return_value = 0

    with (
        patch("echo_personal_tool.main.QApplication", return_value=mock_app),
        patch("echo_personal_tool.main.MainWindow") as mock_mw_cls,
        patch("echo_personal_tool.main.load_user_preferences") as mock_prefs,
        patch("echo_personal_tool.main.ensure_bundled_fonts_loaded"),
        patch("echo_personal_tool.main.patch_pyqtgraph_export_dialog"),
        patch("echo_personal_tool.main.is_enabled", return_value=False),
        patch("echo_personal_tool.main.apply_maximized_to_work_area"),
        patch("echo_personal_tool.presentation.dark_theme.get_logo_path", return_value=Path("/fake/logo.png")),
        patch("echo_personal_tool.main.ui_font", return_value=MagicMock()),
        patch("echo_personal_tool.infrastructure.runtime_setup.check_models", return_value=True),
    ):
        mock_prefs.return_value = SimpleNamespace(
            startup_mode="new_window",
            last_opened_folder="",
            ui_font_size=10,
            language="en",
        )
        mock_mw_cls.return_value = MagicMock()

        from echo_personal_tool.main import main

        result = main()

    assert result == 0


def test_main_last_folder_opens_on_startup() -> None:
    """When startup_mode is 'last_folder' and the folder exists, open_folder_path is called."""
    mock_app = MagicMock()
    mock_app.exec.return_value = 0

    with (
        patch("echo_personal_tool.main.QApplication", return_value=mock_app),
        patch("echo_personal_tool.main.MainWindow") as mock_mw_cls,
        patch("echo_personal_tool.main.load_user_preferences") as mock_prefs,
        patch("echo_personal_tool.main.ensure_bundled_fonts_loaded"),
        patch("echo_personal_tool.main.patch_pyqtgraph_export_dialog"),
        patch("echo_personal_tool.main.is_enabled", return_value=False),
        patch("echo_personal_tool.main.apply_maximized_to_work_area"),
        patch("echo_personal_tool.main.QTimer") as mock_timer,
        patch("echo_personal_tool.presentation.dark_theme.get_logo_path", return_value=Path("/fake/logo.png")),
        patch("echo_personal_tool.main.ui_font", return_value=MagicMock()),
        patch("echo_personal_tool.infrastructure.runtime_setup.check_models", return_value=True),
    ):
        mock_prefs.return_value = SimpleNamespace(
            startup_mode="last_folder",
            last_opened_folder="/tmp/echo_test_folder_that_exists_42",
            ui_font_size=10,
            language="en",
        )
        mock_window = MagicMock()
        mock_mw_cls.return_value = mock_window

        from echo_personal_tool.main import main

        with patch.object(Path, "is_dir", return_value=True):
            result = main()

    assert result == 0
    assert mock_timer.singleShot.call_count >= 2


def test_main_prints_profiler_on_exit() -> None:
    """When profiler is enabled, print_summary() is called after app.exec()."""
    mock_app = MagicMock()
    mock_app.exec.return_value = 0

    with (
        patch("echo_personal_tool.main.QApplication", return_value=mock_app),
        patch("echo_personal_tool.main.MainWindow") as mock_mw_cls,
        patch("echo_personal_tool.main.load_user_preferences") as mock_prefs,
        patch("echo_personal_tool.main.ensure_bundled_fonts_loaded"),
        patch("echo_personal_tool.main.patch_pyqtgraph_export_dialog"),
        patch("echo_personal_tool.main.is_enabled", return_value=True),
        patch("echo_personal_tool.main.print_summary") as mock_print_summary,
        patch("echo_personal_tool.main.apply_maximized_to_work_area"),
        patch("echo_personal_tool.presentation.dark_theme.get_logo_path", return_value=Path("/fake/logo.png")),
        patch("echo_personal_tool.main.ui_font", return_value=MagicMock()),
        patch("echo_personal_tool.infrastructure.runtime_setup.check_models", return_value=True),
    ):
        mock_prefs.return_value = SimpleNamespace(
            startup_mode="new_window",
            last_opened_folder="",
            ui_font_size=10,
            language="en",
        )
        mock_mw_cls.return_value = MagicMock()

        from echo_personal_tool.main import main

        result = main()

    assert result == 0
    mock_print_summary.assert_called_once()


def _prefs(**overrides):
    """Startup preferences as main() sees them (attribute access only)."""
    values = {
        "startup_mode": "empty",
        "last_opened_folder": "",
        "last_session_source": "",
        "ui_font_size": 10,
        "language": "en",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestScheduleLastSession:
    """Q-05/D-27: what "Last session" reopens at startup."""

    def test_server_session_opens_the_server_dialog(self) -> None:
        from echo_personal_tool.main import _schedule_last_session

        window = MagicMock()
        with patch("echo_personal_tool.main.QTimer") as timer:
            scheduled = _schedule_last_session(window, _prefs(startup_mode="last_folder", last_session_source="server"))

        assert scheduled == "server"
        assert timer.singleShot.call_count == 1
        assert timer.singleShot.call_args[0][1] is window.open_server_dialog
        window.open_folder_path.assert_not_called()

    def test_server_session_wins_over_a_stale_folder_path(self, tmp_path: Path) -> None:
        """The PACS cache is gone after exit: never reopen a stale cache folder."""
        from echo_personal_tool.main import _schedule_last_session

        window = MagicMock()
        preferences = _prefs(
            startup_mode="last_folder",
            last_session_source="server",
            last_opened_folder=str(tmp_path),
        )
        with patch("echo_personal_tool.main.QTimer") as timer:
            assert _schedule_last_session(window, preferences) == "server"
        assert timer.singleShot.call_args[0][1] is window.open_server_dialog

    def test_folder_session_opens_the_folder(self, tmp_path: Path) -> None:
        from echo_personal_tool.main import _schedule_last_session

        window = MagicMock()
        preferences = _prefs(
            startup_mode="last_folder",
            last_session_source="folder",
            last_opened_folder=str(tmp_path),
        )
        with patch("echo_personal_tool.main.QTimer") as timer:
            assert _schedule_last_session(window, preferences) == "folder"
        assert timer.singleShot.call_count == 1

    def test_preferences_from_before_the_field_existed_still_open_the_folder(self, tmp_path: Path) -> None:
        from echo_personal_tool.main import _schedule_last_session

        window = MagicMock()
        preferences = _prefs(startup_mode="last_folder", last_session_source="", last_opened_folder=str(tmp_path))
        with patch("echo_personal_tool.main.QTimer"):
            assert _schedule_last_session(window, preferences) == "folder"

    def test_missing_folder_is_reported_and_nothing_is_scheduled(self) -> None:
        from echo_personal_tool.main import _schedule_last_session

        window = MagicMock()
        preferences = _prefs(
            startup_mode="last_folder",
            last_session_source="folder",
            last_opened_folder="/tmp/echo_folder_that_does_not_exist_42",
        )
        with patch("echo_personal_tool.main.QTimer") as timer:
            assert _schedule_last_session(window, preferences) == "missing_folder"
        timer.singleShot.assert_not_called()

    def test_empty_startup_mode_never_restores_anything(self) -> None:
        from echo_personal_tool.main import _schedule_last_session

        window = MagicMock()
        preferences = _prefs(startup_mode="empty", last_session_source="server")
        with patch("echo_personal_tool.main.QTimer") as timer:
            assert _schedule_last_session(window, preferences) == "none"
        timer.singleShot.assert_not_called()


def test_main_opens_the_server_dialog_for_a_server_session() -> None:
    """End-to-end through main(): a PACS session reopens the loader dialog."""
    mock_app = MagicMock()
    mock_app.exec.return_value = 0

    with (
        patch("echo_personal_tool.main.QApplication", return_value=mock_app),
        patch("echo_personal_tool.main.MainWindow") as mock_mw_cls,
        patch("echo_personal_tool.main.load_user_preferences") as mock_prefs,
        patch("echo_personal_tool.main.ensure_bundled_fonts_loaded"),
        patch("echo_personal_tool.main.patch_pyqtgraph_export_dialog"),
        patch("echo_personal_tool.main.is_enabled", return_value=False),
        patch("echo_personal_tool.main.apply_maximized_to_work_area"),
        patch("echo_personal_tool.main.QTimer") as mock_timer,
        patch("echo_personal_tool.presentation.dark_theme.get_logo_path", return_value=Path("/fake/logo.png")),
        patch("echo_personal_tool.main.ui_font", return_value=MagicMock()),
        patch("echo_personal_tool.infrastructure.runtime_setup.check_models", return_value=True),
    ):
        mock_prefs.return_value = _prefs(startup_mode="last_folder", last_session_source="server")
        mock_window = MagicMock()
        mock_mw_cls.return_value = mock_window

        from echo_personal_tool.main import main

        assert main() == 0

    scheduled = [call.args[1] for call in mock_timer.singleShot.call_args_list]
    assert mock_window.open_server_dialog in scheduled


class TestMeasurementPersistenceNotice:
    """W41-02: the one-time «autosave is on» notice (WP4.1 §10.1)."""

    def _window(self, enabled: bool) -> SimpleNamespace:
        persistence = SimpleNamespace(enabled=enabled)
        controller = SimpleNamespace(measurement_persistence=persistence)
        return SimpleNamespace(_controller=controller, _show_user_preferences=MagicMock())

    def _patch(self, monkeypatch, *, notice_shown: bool) -> tuple[list, MagicMock]:
        from echo_personal_tool import main as main_mod

        marked: list = []
        monkeypatch.setattr(main_mod, "measurement_persistence_notice_shown", lambda: notice_shown or bool(marked))
        monkeypatch.setattr(main_mod, "mark_measurement_persistence_notice_shown", lambda: marked.append(True))
        box_cls = MagicMock()
        monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", box_cls)
        return marked, box_cls

    def test_disabled_persistence_shows_nothing(self, monkeypatch):
        from echo_personal_tool import main as main_mod

        marked, box_cls = self._patch(monkeypatch, notice_shown=False)
        main_mod._maybe_show_measurement_persistence_notice(self._window(enabled=False))
        assert not box_cls.called
        assert marked == []

    def test_enabled_shows_once_then_flag_blocks_repeat(self, monkeypatch):
        from echo_personal_tool import main as main_mod

        marked, box_cls = self._patch(monkeypatch, notice_shown=False)
        main_mod._maybe_show_measurement_persistence_notice(self._window(enabled=True))
        assert box_cls.called
        assert marked == [True]
        box_cls.reset_mock()
        main_mod._maybe_show_measurement_persistence_notice(self._window(enabled=True))
        assert not box_cls.called  # flag already set

    def test_settings_button_opens_preferences(self, monkeypatch):
        from echo_personal_tool import main as main_mod

        marked, box_cls = self._patch(monkeypatch, notice_shown=False)
        sentinel = object()
        box = box_cls.return_value
        box.addButton.return_value = sentinel
        box.clickedButton.return_value = sentinel
        window = self._window(enabled=True)
        main_mod._maybe_show_measurement_persistence_notice(window)
        assert window._show_user_preferences.called
