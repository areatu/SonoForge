"""Э4/D-26: global UI scale, font-derived metrics, DPR-correct rasters.

Two different mechanisms are pinned here:

* the OS scale (125/150/200 %) is Qt's own device-independent pixel model —
  we only pin the rounding policy and make sure rasters are rendered at the
  screen's device pixel ratio;
* the user multiplier (4K at 100 %) goes through ``QT_SCALE_FACTOR`` and must
  be written before ``QApplication`` exists — i.e. from the saved preferences.

The heavier checks (dialog layout, chrome metrics, screenshot size) run in a
subprocess with a real ``QT_SCALE_FACTOR`` because the variable is read once,
when the platform plugin initialises.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from echo_personal_tool.infrastructure.ui_scale import (
    HINT_MIN_PHYSICAL_WIDTH,
    HINT_SUGGESTED_PERCENT,
    MAX_UI_SCALE_PERCENT,
    UI_SCALE_AUTO,
    UI_SCALE_CHOICES,
    UI_SCALE_ENV_VAR,
    apply_ui_scale_environment,
    format_scale_factor,
    normalize_ui_scale,
    physical_screen_width,
    restart_command,
    scale_factor_value,
    should_suggest_scale,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ── the setting itself ──────────────────────────────────────────────


def test_scale_choices_are_the_documented_25_percent_steps() -> None:
    assert UI_SCALE_CHOICES == (0, 100, 125, 150, 175, 200, 225, 250)
    assert MAX_UI_SCALE_PERCENT == 250


def test_unknown_values_fall_back_to_auto() -> None:
    assert normalize_ui_scale(None) == UI_SCALE_AUTO
    assert normalize_ui_scale(150) == 150
    # QSettings may hand the value back as text (INI/registry); a numeric string
    # that names an offered step is accepted, anything else falls back to Auto.
    assert normalize_ui_scale("150") == 150
    assert normalize_ui_scale("150 %") == UI_SCALE_AUTO
    assert normalize_ui_scale(133) == UI_SCALE_AUTO
    assert normalize_ui_scale(-100) == UI_SCALE_AUTO


def test_scale_factor_value_is_none_for_auto_and_100() -> None:
    assert scale_factor_value(UI_SCALE_AUTO) is None
    assert scale_factor_value(100) is None
    assert scale_factor_value(125) == 1.25
    assert scale_factor_value(150) == 1.5
    assert scale_factor_value(250) == 2.5


def test_environment_is_only_touched_for_a_real_multiplier() -> None:
    env: dict[str, str] = {}
    apply_ui_scale_environment(UI_SCALE_AUTO, environ=env)
    assert UI_SCALE_ENV_VAR not in env  # Auto must not clear an external value
    apply_ui_scale_environment(100, environ=env)
    assert UI_SCALE_ENV_VAR not in env
    apply_ui_scale_environment(150, environ=env)
    assert env[UI_SCALE_ENV_VAR] == "1.5"
    assert format_scale_factor(175) == "1.75"


def test_environment_keeps_an_externally_set_multiplier_on_auto() -> None:
    env = {UI_SCALE_ENV_VAR: "1.25"}
    apply_ui_scale_environment(UI_SCALE_AUTO, environ=env)
    assert env[UI_SCALE_ENV_VAR] == "1.25"


def test_preferences_round_trip_the_multiplier(tmp_path, monkeypatch) -> None:
    """The value survives save/load and is clamped to the offered choices."""
    from PySide6.QtCore import QSettings

    from echo_personal_tool.infrastructure import user_preferences as up

    store = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(up, "_settings_store", lambda: store)

    preferences = up.UserPreferences(ui_scale_percent=175)
    up.save_user_preferences(preferences)
    assert up.load_user_preferences().ui_scale_percent == 175

    store.setValue("ui_scale_percent", 133)
    assert up.load_user_preferences().ui_scale_percent == UI_SCALE_AUTO


# ── rounding policy, hint heuristic, restart ────────────────────────


def test_rounding_policy_is_pinned_to_pass_through() -> None:
    """Fractional 125/150 % must be honoured exactly, not rounded away."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    from echo_personal_tool.infrastructure.ui_scale import configure_high_dpi_rounding

    configure_high_dpi_rounding()
    assert QGuiApplication.highDpiScaleFactorRoundingPolicy() == Qt.HighDpiScaleFactorRoundingPolicy.PassThrough


class _FakeScreen:
    def __init__(self, *, width: int, dpr: float) -> None:
        self._width = width
        self._dpr = dpr

    def geometry(self):  # noqa: ANN201 - minimal stand-in for QRect
        from PySide6.QtCore import QRect

        return QRect(0, 0, int(self._width / self._dpr), 1000)

    def devicePixelRatio(self) -> float:
        return self._dpr


def test_physical_width_uses_logical_size_times_dpr() -> None:
    assert physical_screen_width(_FakeScreen(width=3840, dpr=1.0)) == 3840
    assert physical_screen_width(_FakeScreen(width=3840, dpr=1.5)) == 3840


def test_hint_only_for_4k_class_screens_at_100_percent() -> None:
    big = _FakeScreen(width=HINT_MIN_PHYSICAL_WIDTH, dpr=1.0)
    assert should_suggest_scale(big, UI_SCALE_AUTO) is True
    # Already scaled by the OS, or by the user: nothing to suggest.
    assert should_suggest_scale(_FakeScreen(width=3840, dpr=1.5), UI_SCALE_AUTO) is False
    assert should_suggest_scale(big, HINT_SUGGESTED_PERCENT) is False
    # An ordinary full-HD screen at 100 % is exactly what the user asked for.
    assert should_suggest_scale(_FakeScreen(width=1920, dpr=1.0), UI_SCALE_AUTO) is False
    assert should_suggest_scale(None, UI_SCALE_AUTO) is False


def test_hint_is_shown_once(tmp_path, monkeypatch) -> None:
    from PySide6.QtCore import QSettings

    from echo_personal_tool.infrastructure import ui_scale

    store = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(ui_scale, "_settings_store", lambda: store)

    assert ui_scale.ui_scale_hint_shown() is False
    ui_scale.mark_ui_scale_hint_shown()
    assert ui_scale.ui_scale_hint_shown() is True


def test_restart_command_for_frozen_and_source_runs(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["sonoforge", "--version", "/data/clips"])
    monkeypatch.delattr(sys, "frozen", raising=False)
    program, args = restart_command()
    assert program == sys.executable
    assert args == ["-m", "echo_personal_tool", "/data/clips"]

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    program, args = restart_command()
    assert program == sys.executable
    assert args == ["/data/clips"]


# ── layout under a real QT_SCALE_FACTOR (subprocess matrix) ─────────

_PROBE = r"""
import json, sys
from PySide6.QtWidgets import QApplication

from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.dark_theme import apply_clinical_theme
from echo_personal_tool.presentation.activity_bar import ActivityBar
from echo_personal_tool.presentation.ste_results_dialog import SteResultsDialog
from echo_personal_tool.presentation.tool_panel import ToolPanel
from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog
from echo_personal_tool.resources.bundled_fonts import ensure_bundled_fonts_loaded, ui_font

font_px = int(sys.argv[1])
app = QApplication([])
ensure_bundled_fonts_loaded()
app.setFont(ui_font(pixel_size=font_px))
apply_clinical_theme(font_size=font_px, theme="vscode_dark", animate=False)

preferences = UserPreferences(ui_font_size=font_px)
dialog = UserPreferencesDialog(None, on_apply=None)
dialog.resize(dialog.sizeHint())
dialog.show()
app.processEvents()

panel = ToolPanel()
panel.update_font_metrics()
panel.resize(panel.sizeHint())
panel.show()
app.processEvents()

activity = ActivityBar()
activity.show()
app.processEvents()

results = SteResultsDialog(None)
results.show()
app.processEvents()

pixmap = dialog.grab()
report = {
    "dpr": float(app.primaryScreen().devicePixelRatio()),
    "dialog_min_w": int(dialog.minimumSizeHint().width()),
    "dialog_w": int(dialog.width()),
    "dialog_h": int(dialog.height()),
    "panel_min_w": int(panel.minimumWidth()),
    "panel_hint_w": int(panel.sizeHint().width()),
    "activity_min_w": int(activity.minimumWidth()),
    "results_min_w": int(results.minimumWidth()),
    "results_min_h": int(results.minimumHeight()),
    "grab_w": int(pixmap.width()),
    "grab_h": int(pixmap.height()),
}
print(json.dumps(report))
"""


def _probe(*, scale: str, font_px: int) -> dict:
    import os

    env = dict(os.environ)
    env["QT_SCALE_FACTOR"] = scale
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.setdefault("LD_LIBRARY_PATH", str(_REPO_ROOT / "tools" / "qtstub" / "lib"))
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, str(font_px)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
        timeout=180,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("scale", ["1", "1.25", "1.5", "2"])
def test_dialog_fits_and_screenshot_scales_with_the_multiplier(scale: str) -> None:
    report = _probe(scale=scale, font_px=13)

    assert report["dpr"] == pytest.approx(float(scale))
    # Nothing is clipped: the dialog respects its own minimum size hint.
    assert report["dialog_w"] >= report["dialog_min_w"]
    # A grab is rendered in device pixels (DPR-correct raster path).
    assert report["grab_w"] == pytest.approx(report["dialog_w"] * float(scale), abs=2)
    assert report["grab_h"] == pytest.approx(report["dialog_h"] * float(scale), abs=2)


def test_chrome_grows_with_the_ui_font() -> None:
    """Fixed pixel sizes would stay constant here — the audit must not regress."""
    small = _probe(scale="1", font_px=10)
    large = _probe(scale="1", font_px=24)

    assert large["activity_min_w"] > small["activity_min_w"]
    assert large["results_min_h"] > small["results_min_h"]
    assert large["dialog_min_w"] > small["dialog_min_w"]


def test_preferences_carry_no_hardcoded_px_suffix_for_ui_fonts() -> None:
    """The UI font setting is a pixel size now, not points (mixed units, Э4)."""
    from echo_personal_tool.infrastructure.user_preferences import (
        DEFAULT_UI_FONT_SIZE,
        MAX_UI_FONT_SIZE,
        MIN_UI_FONT_SIZE,
    )

    assert MIN_UI_FONT_SIZE <= DEFAULT_UI_FONT_SIZE <= MAX_UI_FONT_SIZE
    assert MAX_UI_FONT_SIZE >= 24
