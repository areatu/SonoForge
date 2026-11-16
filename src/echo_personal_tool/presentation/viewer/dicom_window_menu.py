"""Context-menu entry for DICOM header windows and numeric W/L (issue 542).

The menu is a thin presentation adapter: the rendering rules and the numeric
state live in :class:`~echo_personal_tool.presentation.viewer.display.ViewerDisplay`.
Only instances whose header actually carries a display chain get the submenu;
plain ultrasound images keep their familiar W/L controls.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox, QWidget

from echo_personal_tool.application.localization import tr

if TYPE_CHECKING:
    from echo_personal_tool.presentation.viewer.display import ViewerDisplay

_SPLIT = re.compile(r"[,;\s]+")


def add_dicom_window_actions(menu: QMenu, display: ViewerDisplay) -> None:
    """Append header windows / numeric W/L when the current instance has them."""
    if not display.has_dicom_display():
        return
    submenu = menu.addMenu(tr("viewer.window_menu"))
    presets = display.window_presets()
    for index, preset in enumerate(presets):
        action = submenu.addAction(preset.label)
        action.triggered.connect(lambda _checked=False, i=index: display.apply_window_preset(i))
    if presets:
        submenu.addSeparator()
    submenu.addAction(tr("viewer.window_numeric"), lambda: _ask_numeric(display))
    submenu.addAction(tr("viewer.window_reset"), display.reset_dicom_window)


def _parent(display: ViewerDisplay) -> QWidget | None:
    parent = display.parent()
    return parent if isinstance(parent, QWidget) else None


def _ask_numeric(display: ViewerDisplay) -> None:
    current = display.window_level_values()
    text = f"{current[0]:g}, {current[1]:g}" if current is not None else "40, 80"
    entered, accepted = QInputDialog.getText(
        _parent(display),
        tr("viewer.window_numeric_title"),
        tr("viewer.window_numeric_prompt"),
        text=text,
    )
    if not accepted:
        return
    parts = [part for part in _SPLIT.split(entered.strip()) if part]
    try:
        center, width = float(parts[0]), float(parts[1])
    except (IndexError, ValueError):
        _invalid(display)
        return
    if not display.apply_numeric_window(center, width):
        _invalid(display)


def _invalid(display: ViewerDisplay) -> None:
    QMessageBox.warning(
        _parent(display),
        tr("viewer.window_numeric_title"),
        tr("viewer.window_numeric_invalid"),
    )
