"""Unit tests for the M-mode caliper menu actions (TAPSE, IVC expiration/inspiration)."""

from __future__ import annotations

from echo_personal_tool.domain.translation import tr
from echo_personal_tool.presentation.mode_caliper_actions import (
    start_mode_caliper,
    start_mode_caliper_hint,
)


class _FakeViewer:
    def __init__(self, *, arms: bool) -> None:
        self.arms = arms
        self.labels: list[str] = []

    def start_linear_caliper_for(self, label: str) -> bool:
        self.labels.append(label)
        return self.arms


class _FakeWindow:
    """The slice of ``MainWindow`` the action drives, without a window."""

    def __init__(self, *, ready: bool = True, arms: bool = True) -> None:
        self._viewer = _FakeViewer(arms=arms)
        self.ready = ready
        self.status: list[str] = []
        self.hints: list[str] = []
        self.mmode_ready_asked = 0

    def _ensure_mmode_ready_for_tapse(self) -> bool:
        self.mmode_ready_asked += 1
        return self.ready

    def _show_status(self, message: str) -> None:
        self.status.append(message)

    def _show_hint(self, message: str) -> None:
        self.hints.append(message)


def test_an_ivc_caliper_is_armed_and_named_in_the_status_bar() -> None:
    window = _FakeWindow()

    start_mode_caliper(window, "IVC-EXP", "menu.ivc_exp")

    assert window._viewer.labels == ["IVC-EXP"]
    assert window.status == [tr("status.linear_caliper_tool", label=tr("menu.ivc_exp"))]
    assert window.hints == []


def test_tapse_keeps_its_prompt_in_the_hint_strip() -> None:
    window = _FakeWindow()

    start_mode_caliper_hint(window, "TAPSE", "status.rv_tapse_tool")

    assert window._viewer.labels == ["TAPSE"]
    assert window.hints == [tr("status.rv_tapse_tool")]
    assert window.status == []


def test_no_caliper_starts_before_the_mmode_calibration_is_ready() -> None:
    window = _FakeWindow(ready=False)

    start_mode_caliper(window, "IVC-INSP", "menu.ivc_insp")
    start_mode_caliper_hint(window, "TAPSE", "status.rv_tapse_tool")

    assert window.mmode_ready_asked == 2
    assert window._viewer.labels == []
    assert window.status == []
    assert window.hints == []


def test_a_caliper_that_cannot_be_armed_explains_the_missing_frame() -> None:
    window = _FakeWindow(arms=False)

    start_mode_caliper(window, "IVC-EXP", "menu.ivc_exp")

    assert window._viewer.labels == ["IVC-EXP"]
    assert window.status == [tr("status.load_first_frame")]
    assert window.hints == []
