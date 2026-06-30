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


def _load_icon(name: str) -> QIcon:
    svg_path = _ICON_DIR / f"{name}.svg"
    if svg_path.is_file():
        pixmap = QPixmap(str(svg_path))
        if not pixmap.isNull():
            return QIcon(pixmap)
    return QIcon()


class ActivityBar(QWidget):
    """Vertical icon bar (VS Code style, ~48px)."""

    tab_activated = Signal(str)
    tab_deactivated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("activityBar")
        self.setFixedWidth(48)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._buttons: dict[str, QPushButton] = {}
        for name, icon_file in [
            ("measures", "activity_measures"),
            ("controls", "activity_controls"),
            ("dicom", "activity_dicom"),
        ]:
            btn = QPushButton()
            btn.setIcon(_load_icon(icon_file))
            btn.setCheckable(True)
            btn.setToolTip(name.capitalize())
            btn.clicked.connect(lambda _, n=name: self._on_click(n))
            layout.addWidget(btn)
            self._buttons[name] = btn
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
