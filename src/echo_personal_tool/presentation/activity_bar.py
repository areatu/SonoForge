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

from echo_personal_tool.presentation.ui_animations import HoverButtonMixin

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


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
        self._label.setText(
            f"<center>"
            f"<span style='font-size:15px;font-weight:bold;'>{self._big}</span><br/>"
            f"<span style='font-size:12px;'>{self._small}</span>"
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
        self.setFixedWidth(96)
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
        from echo_personal_tool.infrastructure.i18n import tr

        _labels = {
            "caliper": (tr("activity.caliper_big"), tr("activity.caliper_small")),
            "lv2d": (tr("activity.lv2d_big"), tr("activity.lv2d_small")),
            "esv": (tr("activity.esv_big"), tr("activity.esv_small")),
            "edv": (tr("activity.edv_big"), tr("activity.edv_small")),
            "es": (tr("activity.es_big"), tr("activity.es_small")),
        }
        for name in [
            "caliper",
            "lv2d",
            "esv",
            "edv",
            "es",
        ]:
            big, small = _labels.get(name, (name, ""))
            btn = _TextButton(big, small)
            btn.clicked.connect(lambda _, n=name: self.action_requested.emit(n))
            HoverButtonMixin.install(btn)
            layout.addWidget(btn)
            self._action_buttons[name] = btn

        layout.addStretch(1)

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
            "lv2d": tr("tools.lv2d_all_diastole"),
            "esv": tr("tools.lv2d_es"),
            "edv": tr("tools.ed_auto"),
            "es": tr("tools.es_auto"),
        }
        action_labels = {
            "caliper": (tr("activity.caliper_big"), tr("activity.caliper_small")),
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
