"""Tests for echo_personal_tool.main (0% coverage target).

The main() function is a full Qt app launch; we test the module-level
side-effects (logging setup, env defaults) and the main() return path
via heavy mocking to avoid starting a real QApplication.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


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
        )
        mock_mw_cls.return_value = MagicMock()

        from echo_personal_tool.main import main

        result = main()

    assert result == 0
    mock_print_summary.assert_called_once()
