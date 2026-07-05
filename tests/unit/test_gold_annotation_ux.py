"""Tests for gold annotation UX (QSettings round-trip, context menu logic)."""

from __future__ import annotations

import pytest

from echo_personal_tool.infrastructure.user_preferences import (
    UserPreferences,
    load_user_preferences,
    save_user_preferences,
)


class TestGoldPreferences:
    def test_default_gold_disabled(self) -> None:
        prefs = UserPreferences()
        assert prefs.gold_annotation_enabled is False
        assert prefs.gold_dataset_path == ""

    def test_round_trip_gold_settings(self, qtbot) -> None:
        prefs = UserPreferences(
            gold_annotation_enabled=True,
            gold_dataset_path="/tmp/gold_data",
        )
        save_user_preferences(prefs)
        loaded = load_user_preferences()
        assert loaded.gold_annotation_enabled is True
        assert loaded.gold_dataset_path == "/tmp/gold_data"

    def test_gold_defaults_when_missing(self, qtbot) -> None:
        """When QSettings has no gold keys, defaults should be used."""
        from PySide6.QtCore import QSettings
        store = QSettings("echo-personal-tool", "preferences")
        store.remove("gold_annotation_enabled")
        store.remove("gold_dataset_path")
        loaded = load_user_preferences()
        assert loaded.gold_annotation_enabled is False
        assert loaded.gold_dataset_path == ""


class TestGoldContextMenuLogic:
    """Test the logic that determines when gold export menu items appear."""

    def test_gold_export_signal_signature(self) -> None:
        """Verify gold_export_requested signal exists on ViewerWidget."""
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget
        assert hasattr(ViewerWidget, "gold_export_requested")
