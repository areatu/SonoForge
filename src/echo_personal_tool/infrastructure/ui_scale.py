"""Global UI scale multiplier (Э4 / D-26).

Two different problems, two different mechanisms:

* **OS scaling** (Windows 125 / 150 / 200 %) — Qt 6 already lives in
  device-independent pixels and multiplies geometry, styles and painting by
  the screen's ``devicePixelRatio`` (Per-Monitor DPI Aware V2 on Windows).
  Our job is to not fall out of that model; building a second scale on top
  of Qt is exactly what the Telegram Desktop counter-example warns about.
* **A large 4K screen at 100 %** — the OS does not scale anything, so the
  interface is physically small and the user needs an explicit multiplier.
  Qt's supported mechanism is ``QT_SCALE_FACTOR``, which must be set before
  ``QApplication`` is created.  It is applied verbatim (the rounding policy
  does not apply to it, verified in the sandbox), so a 25 % step gives a
  fractional ``devicePixelRatio`` that Qt renders exactly.

The multiplier is therefore applied once, as an environment variable, and
everything else keeps working in logical pixels.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import MutableMapping

    from PySide6.QtGui import QScreen

#: ``0`` means "follow the operating system" (no QT_SCALE_FACTOR at all).
UI_SCALE_AUTO = 0
#: 25 % step: Qt recommends whole factors or a 25 % step over "exact physical DPI".
SCALE_STEP_PERCENT = 25
MIN_UI_SCALE_PERCENT = 100
MAX_UI_SCALE_PERCENT = 250
UI_SCALE_CHOICES: tuple[int, ...] = (UI_SCALE_AUTO, 100, 125, 150, 175, 200, 225, 250)

UI_SCALE_ENV_VAR = "QT_SCALE_FACTOR"

#: A 4K-class screen at 100 % is the case the one-time hint exists for.
HINT_MIN_PHYSICAL_WIDTH = 3600
HINT_SUGGESTED_PERCENT = 150
_HINT_SETTINGS_KEY = "ui_scale_hint_shown"


def normalize_ui_scale(value: object) -> int:
    """Return a value from :data:`UI_SCALE_CHOICES`, or Auto for anything else."""
    try:
        percent = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return UI_SCALE_AUTO
    return percent if percent in UI_SCALE_CHOICES else UI_SCALE_AUTO


def scale_factor_value(percent: int) -> float | None:
    """Environment value for ``percent``; ``None`` for Auto."""
    percent = normalize_ui_scale(percent)
    if percent == UI_SCALE_AUTO or percent == 100:
        # 100 % is the same as "do not scale": leave the environment alone so
        # an externally set QT_SCALE_FACTOR keeps working.
        return None
    return percent / 100.0


def format_scale_factor(percent: int) -> str:
    """``150`` → ``"1.5"`` (the value written to the environment)."""
    value = percent / 100.0
    return f"{value:g}"


def apply_ui_scale_environment(
    percent: int,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> str | None:
    """Write ``QT_SCALE_FACTOR`` for the multiplier *before* ``QApplication``.

    Returns the value written, or ``None`` when the variable was left alone
    (Auto/100 %).  Auto never clears an externally provided variable: a user
    may launch the app with ``QT_SCALE_FACTOR`` set deliberately.
    """
    target = os.environ if environ is None else environ
    if scale_factor_value(percent) is None:
        return None
    text = format_scale_factor(normalize_ui_scale(percent))
    target[UI_SCALE_ENV_VAR] = text
    return text


def configure_high_dpi_rounding() -> None:
    """Pin Qt's rounding policy explicitly (must run before ``QApplication``).

    ``PassThrough`` is Qt 6's default and the right choice here: fractional
    125/150 % OS scales are honoured exactly and Qt renders at the fractional
    ``devicePixelRatio``.  Rounding to whole factors would either shrink or
    overshoot the user's OS setting.  Pinned by a test so a future change to
    the default cannot silently alter every window geometry.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)


def physical_screen_width(screen: QScreen) -> int:
    """Screen width in physical pixels (logical size × devicePixelRatio)."""
    try:
        return int(round(screen.geometry().width() * screen.devicePixelRatio()))
    except Exception:  # noqa: BLE001 - a probe must never break startup
        return 0


def should_suggest_scale(screen: QScreen | None, percent: int) -> bool:
    """True when a one-time "try 150 %" hint is worth showing.

    Heuristic: the screen is 4K-class **in physical pixels** while the OS (and
    the multiplier) report 100 %, i.e. everything is drawn at 1:1.  A 27-inch
    4K monitor at 100 % is exactly this case; a 3440×1440 ultrawide at 100 %
    has comfortable physical size and is below the threshold.
    """
    if screen is None or normalize_ui_scale(percent) != UI_SCALE_AUTO:
        return False
    if screen.devicePixelRatio() > 1.0:
        return False
    return physical_screen_width(screen) >= HINT_MIN_PHYSICAL_WIDTH


def _settings_store():
    from echo_personal_tool.infrastructure.user_preferences import _settings_store as store

    return store()


def ui_scale_hint_shown() -> bool:
    store = _settings_store()
    value = store.value(_HINT_SETTINGS_KEY, False)
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def mark_ui_scale_hint_shown() -> None:
    store = _settings_store()
    store.setValue(_HINT_SETTINGS_KEY, True)
    store.sync()


def restart_command() -> tuple[str, list[str]]:
    """Command that starts a fresh copy of this application."""
    args = [arg for arg in sys.argv[1:] if arg not in ("--version", "-V")]
    if getattr(sys, "frozen", False):
        return sys.executable, args
    return sys.executable, ["-m", "echo_personal_tool", *args]


def restart_application() -> bool:
    """Start a detached copy of the application; the caller quits the current one."""
    from PySide6.QtCore import QProcess

    program, args = restart_command()
    try:
        return bool(QProcess.startDetached(program, args))
    except Exception:  # noqa: BLE001 - restart is best-effort, the setting is already saved
        return False
