"""Vertical icon bar (VS Code style, ~48px)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.ui_animations import HoverButtonMixin
from echo_personal_tool.presentation.ui_metrics import (
    font_pixel_size,
    two_line_height,
    widest_text_width,
)

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"

#: Action buttons of the rail, in visual order.  Single source of truth for the
#: captions: the rail width is measured from the very strings it renders, so a
#: label can never be added to one place and forgotten in the other (a missing
#: key used to measure as the raw key text and inflate the rail).
_ACTION_NAMES = ("caliper", "play", "hr", "lv2d", "esv", "edv", "es")


def _action_labels() -> dict[str, tuple[str, str]]:
    from echo_personal_tool.infrastructure.i18n import tr

    return {name: (tr(f"activity.{name}_big"), tr(f"activity.{name}_small")) for name in _ACTION_NAMES}


def _icon_dir() -> Path:
    import sys

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        return Path(meipass) / "echo_personal_tool" / "resources" / "icons"
    return _ICON_DIR


def _load_icon(name: str, size: int = 48) -> QIcon:
    from PySide6.QtGui import QPainter
    from PySide6.QtSvg import QSvgRenderer

    from echo_personal_tool.presentation.dark_theme import get_theme_palette

    svg_path = _icon_dir() / f"{name}.svg"
    if svg_path.is_file():
        svg_text = svg_path.read_text(encoding="utf-8")
        color = get_theme_palette().get("text", "#f1f5f9")
        svg_text = svg_text.replace("currentColor", color)
        renderer = QSvgRenderer(svg_text.encode("utf-8"))
        if renderer.isValid():
            pixmap = QPixmap(size, size)
            pixmap.fill(0)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            return QIcon(pixmap)
    return QIcon()


class _TextButton(QPushButton):
    """Two-line text button for the activity bar (large + small)."""

    def __init__(self, big: str, small: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._big = big
        self._small = small
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(0)
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background: transparent; border: none;")
        self._update_label()
        layout.addWidget(self._label)

    def _update_label(self) -> None:
        big_px = font_pixel_size(self, 1.15, minimum=10)
        small_px = font_pixel_size(self, 0.92, minimum=8)
        self._label.setText(
            f"<center>"
            f"<span style='font-size:{big_px}px;font-weight:bold;'>{self._big}</span><br/>"
            f"<span style='font-size:{small_px}px;'>{self._small}</span>"
            f"</center>"
        )

    def set_labels(self, big: str, small: str) -> None:
        self._big = big
        self._small = small
        self._update_label()


class ActivityBar(QWidget):
    """Vertical icon bar with tool shortcuts."""

    tab_activated = Signal(str)
    tab_deactivated = Signal(str)
    action_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("activityBar")
        # A fixed rail width — but computed from the current font, not frozen at
        # 96 px (Э4): a long RU caption or a 24 px font used to be clipped.
        self.setFixedWidth(self._bar_width())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._buttons: dict[str, QPushButton] = {}
        for name, icon_file in [
            ("measures", "activity_measures"),
            ("controls", "activity_controls"),
        ]:
            btn = QPushButton()
            btn.setIcon(_load_icon(icon_file))
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, n=name: self._on_click(n))
            HoverButtonMixin.install(btn)
            layout.addWidget(btn)
            self._buttons[name] = btn

        layout.addSpacing(8)

        self._action_buttons: dict[str, QPushButton] = {}

        _labels = _action_labels()
        for name in _ACTION_NAMES:
            big, small = _labels.get(name, (name, ""))
            btn = _TextButton(big, small)
            btn.setMinimumHeight(two_line_height(btn))
            btn.clicked.connect(lambda _, n=name: self.action_requested.emit(n))
            HoverButtonMixin.install(btn)
            self._action_buttons[name] = btn

        # Playback actions sit right under the caliper; the LV quantification
        # block starts after a small separator.
        for name in ["caliper", "play", "hr"]:
            layout.addWidget(self._action_buttons[name])
        layout.addSpacing(8)
        for name in ["lv2d", "esv", "edv", "es"]:
            layout.addWidget(self._action_buttons[name])

        layout.addStretch(1)

        self._playing = False

    def update_font_metrics(self) -> None:
        """Re-measure width and captions after the UI font changed (Э4)."""
        self.setFixedWidth(self._bar_width())
        for button in self._action_buttons.values():
            if isinstance(button, _TextButton):
                button._update_label()

    def _bar_width(self) -> int:
        """Widest rendered caption + padding, never narrower than 96 px.

        Only strings that are actually painted are measured: the play button
        swaps its caption to the pause glyph during playback, so that glyph is
        included too.  Measuring a key that has no translation would compare a
        layout decision against the raw key text.
        """
        labels: list[str] = []
        for big, small in _action_labels().values():
            labels.extend((big, small))
        labels.append(tr("activity.pause_big"))
        return widest_text_width(self, labels, padding=16, minimum=96)

    def set_playing(self, playing: bool) -> None:
        """Swap the play/pause button glyph to match the playback state."""
        if self._playing == playing:
            return
        self._playing = playing
        from echo_personal_tool.infrastructure.i18n import tr

        btn = self._action_buttons.get("play")
        if btn is not None:
            btn.set_labels(
                tr("activity.pause_big") if playing else tr("activity.play_big"),
                tr("activity.play_small"),
            )

    def _on_click(self, name: str) -> None:
        btn = self._buttons[name]
        if btn.isChecked():
            for n, b in self._buttons.items():
                if n != name:
                    b.setChecked(False)
            self.tab_activated.emit(name)
        else:
            self.tab_deactivated.emit(name)

    def set_active(self, name: str | None) -> None:
        for n, b in self._buttons.items():
            b.setChecked(n == name)

    def reload_text(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        tab_names = {"measures": tr("tool_panel.measures"), "controls": tr("tool_panel.controls")}
        for name, btn in self._buttons.items():
            btn.setToolTip(tab_names.get(name, name.capitalize()))
        action_tooltips = {
            "caliper": tr("tool_panel.linear_caliper"),
            "play": tr("viewer.play"),
            "hr": tr("system_bar.heart_rate_tooltip"),
            "lv2d": tr("tools.lv2d_all_diastole"),
            "esv": tr("tools.lv2d_es"),
            "edv": tr("tools.ed_auto"),
            "es": tr("tools.es_auto"),
        }
        action_labels = {
            "caliper": (tr("activity.caliper_big"), tr("activity.caliper_small")),
            "play": (
                tr("activity.pause_big") if self._playing else tr("activity.play_big"),
                tr("activity.play_small"),
            ),
            "hr": (tr("activity.hr_big"), tr("activity.hr_small")),
            "lv2d": (tr("activity.lv2d_big"), tr("activity.lv2d_small")),
            "esv": (tr("activity.esv_big"), tr("activity.esv_small")),
            "edv": (tr("activity.edv_big"), tr("activity.edv_small")),
            "es": (tr("activity.es_big"), tr("activity.es_small")),
        }
        for name, btn in self._action_buttons.items():
            btn.setToolTip(action_tooltips.get(name, name))
            if name in action_labels:
                big, small = action_labels[name]
                btn.set_labels(big, small)
