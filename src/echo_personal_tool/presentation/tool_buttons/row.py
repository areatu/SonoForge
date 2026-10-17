"""The tool row over the image (UI-2 PR-3): renders :data:`model.ROW_TOOLS`.

Each button emits the same ``action_requested(action, view, phase, extra)`` as
the tool panel, so the window routes the row and the panel through one handler.
MainWindow places the row above the viewer (``_viewer_frame``) when the user chose it.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.keyboard_shortcuts import shortcut_label
from echo_personal_tool.presentation.tool_buttons.model import ROW_TOOLS, RowTool


class ToolButtonRow(QWidget):
    """A horizontal row of image-tool buttons (labels from the locale)."""

    action_requested = Signal(object, str, str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolButtonRow")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 4, 8, 4)
        self._layout.setSpacing(4)
        self._buttons: dict[str, QToolButton] = {}
        for tool in ROW_TOOLS:
            button = QToolButton(self)
            button.setObjectName(f"toolRow_{tool.id}")
            button.setAutoRaise(True)
            button.clicked.connect(lambda _checked=False, t=tool: self._emit(t))
            self._buttons[tool.id] = button
            self._layout.addWidget(button)
        self._layout.addStretch(1)
        self.reload_text()

    def button(self, tool_id: str) -> QToolButton | None:
        return self._buttons.get(tool_id)

    def reload_text(self) -> None:
        """Re-read the captions and key hints (after a language change)."""
        for tool in ROW_TOOLS:
            button = self._buttons[tool.id]
            button.setText(tr(tool.label_key))
            tip = tr(tool.label_key)
            if tool.shortcut_id:
                tip = f"{tip} · {shortcut_label(tool.shortcut_id)}"
            button.setToolTip(tip)

    def _emit(self, tool: RowTool) -> None:
        self.action_requested.emit(*tool.payload())
