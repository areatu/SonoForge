"""Vertical icon bar (VS Code style, ~48px)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def _icon_dir() -> Path:
    import sys
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        return Path(meipass) / "echo_personal_tool" / "resources" / "icons"
    return _ICON_DIR


def _load_icon(name: str) -> QIcon:
    from echo_personal_tool.presentation.echopac_theme import get_theme_palette
    svg_path = _icon_dir() / f"{name}.svg"
    if svg_path.is_file():
        svg_text = svg_path.read_text(encoding="utf-8")
        color = get_theme_palette().get("text", "#f1f5f9")
        svg_text = svg_text.replace("currentColor", color)
        pixmap = QPixmap()
        pixmap.loadFromData(svg_text.encode("utf-8"))
        if not pixmap.isNull():
            return QIcon(pixmap)
    return QIcon()


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
            layout.addWidget(btn)
            self._buttons[name] = btn

        layout.addSpacing(8)

        self._action_buttons: dict[str, QPushButton] = {}
        for name, icon_file in [
            ("caliper", "activity_caliper"),
            ("lv2d", "activity_lv2d"),
            ("esv", "activity_esv"),
            ("simpson_manual_ed", "activity_simpd"),
            ("simpson_manual_es", "activity_simps"),
            ("auto_ed", "activity_auto_d"),
            ("auto_es", "activity_auto_s"),
        ]:
            btn = QPushButton()
            btn.setIcon(_load_icon(icon_file))
            btn.clicked.connect(lambda _, n=name: self.action_requested.emit(n))
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
        tab_names = {"measures": tr("measures"), "controls": tr("controls")}
        for name, btn in self._buttons.items():
            btn.setToolTip(tab_names.get(name, name.capitalize()))
        action_names = {
            "caliper": tr("tools.caliper"),
            "lv2d": tr("tools.lv2d_all_diastole"),
            "esv": tr("tools.lv2d_es"),
            "simpson_manual_ed": tr("tools.ed_auto"),
            "simpson_manual_es": tr("tools.es_auto"),
            "auto_ed": tr("tools.ed_auto"),
            "auto_es": tr("tools.es_auto"),
        }
        for name, btn in self._action_buttons.items():
            btn.setToolTip(action_names.get(name, name))
