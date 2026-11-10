"""Plain-function viewer side for :class:`MModeController` tests (issue 479).

``FakeMModeViewer`` builds the :class:`MModeViewerPort` from attributes and
lists, so a test drives the M-mode controller without a ``ViewerWidget``. It
mimics the two widget behaviours the M-mode flow relies on:

* clearing the generic calibration caliper disarms it and tells the controller
  (``on_calibration_caliper_cleared``), exactly like the widget does;
* the number dialog answers from a queue and records each question.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import numpy as np
from PySide6.QtCore import Qt

from echo_personal_tool.domain.models.frame_panels import FramePanelLayout
from echo_personal_tool.presentation.viewer.mmode_controller import (
    MModeCalibrationKind,
    MModeController,
    MModeViewerPort,
)


@dataclass(frozen=True)
class FakeClick:
    """A mouse press already mapped to view coordinates."""

    x: float
    y: float
    left: bool = True

    def button(self) -> Qt.MouseButton:
        return Qt.MouseButton.LeftButton if self.left else Qt.MouseButton.RightButton


class FakeMModeViewer:
    """Records what the controller asks of the widget."""

    def __init__(
        self,
        *,
        frame: np.ndarray | None = None,
        panels: FramePanelLayout | None = None,
        frame_time_ms: float | None = None,
    ) -> None:
        self.frame = frame
        self.panels = panels
        self.frame_time_ms = frame_time_ms
        self.syncing = False
        self.view: Any = MagicMock(name="view")
        self.answers: list[tuple[float, bool]] = []
        self.questions: list[tuple[str, str, float, float, float, int]] = []
        self.calls: list[str] = []
        self.messages: list[str] = []
        self.calibration_kind: MModeCalibrationKind | None = None
        self.calibration_active = False
        self.calibration_x: float | None = None
        self.vertical_labels: set[str] = {"TAPSE", "M-mode"}
        self.linear_calipers: list[str | tuple[str, ...]] = []
        self.caliper_accepts = True
        self.controller = MModeController(self.port())

    def port(self) -> MModeViewerPort:
        return MModeViewerPort(
            frame=lambda: self.frame,
            frame_time_ms=lambda: self.frame_time_ms,
            resolve_panels=lambda: self.panels,
            syncing=lambda: self.syncing,
            view=lambda: self.view,
            map_event=lambda ev: (ev.x, ev.y),
            cancel_tool=lambda: self.calls.append("cancel_tool"),
            clear_calibration_caliper=self._clear_calibration_caliper,
            arm_calibration=self._arm_calibration,
            show_message=self.messages.append,
            unset_cursor=lambda: self.calls.append("unset_cursor"),
            apply_viewport_cursor=lambda: self.calls.append("apply_viewport_cursor"),
            ask_double=self._ask_double,
            start_linear_caliper_for=self._start_linear_caliper_for,
            start_linear_caliper_sequence=self._start_linear_caliper_sequence,
            add_vertical_labels=self.vertical_labels.update,
            remove_vertical_labels=self.vertical_labels.difference_update,
        )

    def _clear_calibration_caliper(self) -> None:
        self.calls.append("clear_calibration_caliper")
        self.calibration_active = False
        self.calibration_kind = None
        self.controller.on_calibration_caliper_cleared()

    def _arm_calibration(self, kind: MModeCalibrationKind, x: float | None) -> None:
        self.calibration_kind = kind
        self.calibration_active = True
        if x is not None:
            self.calibration_x = x

    def _ask_double(
        self, title: str, prompt: str, value: float, low: float, high: float, decimals: int
    ) -> tuple[float, bool]:
        self.questions.append((title, prompt, value, low, high, decimals))
        return self.answers.pop(0)

    def _start_linear_caliper_for(self, label: str) -> bool:
        self.linear_calipers.append(label)
        return self.caliper_accepts

    def _start_linear_caliper_sequence(self, labels: tuple[str, ...]) -> bool:
        self.linear_calipers.append(labels)
        if self.caliper_accepts:
            # The widget starts a new sequence by dropping the previous session labels.
            self.controller.reset_session_vertical_labels()
        return self.caliper_accepts
