"""Автомат протокола (TP-3 PR-2, спека TP §6.2, A-04…A-10).

Без цикла событий: автопереход выполняется ``advance_now()`` / отменяется
``cancel_advance()``; ``QTimer`` не запускается.
"""

from __future__ import annotations

from echo_personal_tool.application.protocol_runner import (
    EscapeResult,
    ProtocolRunner,
    StepAction,
)
from echo_personal_tool.domain.protocols import (
    ProjectionValue,
    StepState,
    StudyProjection,
)

_ED = ("lv.ivsd", "lv.lvedd", "lv.lvpwd")


def _values(keys, *, origin: str = "lv_linear", stale: bool = False) -> dict:
    return {key: ProjectionValue(value=1.0, origin=origin, stale=stale) for key in keys}


def _ed(origin: str = "lv_linear") -> StudyProjection:
    return StudyProjection(values=_values(_ED, origin=origin))


def _completed() -> StudyProjection:
    values = _values(_ED)
    values["lv.lvesd"] = ProjectionValue(value=1.0, origin="lv_linear")
    return StudyProjection(values=values)


def test_start_selects_first_unmet_step() -> None:
    runner = ProtocolRunner()
    runner.start("lv_linear")
    current = runner.progress
    assert runner.active
    assert current.current_index == 0
    assert current.step(0).state is StepState.CURRENT


def test_arm_emits_step_action_payload() -> None:
    runner = ProtocolRunner()
    runner.start("lv_linear")
    seen: list[StepAction] = []
    runner.action_requested.connect(seen.append)
    runner.arm(0)
    assert runner.armed_index == 0
    assert len(seen) == 1
    assert seen[0].tool_id == "lv.linear_ed"
    assert seen[0].frame_hint == "ed"


def test_projection_completion_schedules_auto_advance() -> None:
    runner = ProtocolRunner()
    runner.start("lv_linear")
    runner.arm(0)
    notes: list[str] = []
    runner.notification.connect(notes.append)
    runner.set_projection(_ed())
    assert runner.pending_advance == 1
    assert notes == ["auto_advance"]
    runner.advance_now()
    assert runner.armed_index == 1
    assert runner.pending_advance is None


def test_escape_cancels_drawing_then_stops_protocol() -> None:
    runner = ProtocolRunner()
    runner.start("lv_linear")
    cancels: list[bool] = []
    runner.drawing_cancel_requested.connect(lambda: cancels.append(True))
    runner.set_drawing_active(True)
    assert runner.on_escape() is EscapeResult.DRAWING_CANCELLED
    assert cancels == [True]
    assert runner.active
    assert runner.on_escape() is EscapeResult.STOPPED
    assert not runner.active


def test_escape_cancels_pending_advance_but_keeps_protocol() -> None:
    runner = ProtocolRunner()
    runner.start("lv_linear")
    runner.arm(0)
    runner.set_projection(_ed())
    assert runner.pending_advance == 1
    assert runner.on_escape() is EscapeResult.ADVANCE_CANCELLED
    assert runner.pending_advance is None
    assert runner.active


def test_skip_marks_step_and_moves_on() -> None:
    runner = ProtocolRunner()
    runner.start("lv_linear")
    runner.skip()
    current = runner.progress
    assert current.step(0).state is StepState.SKIPPED
    assert current.current_index == 1


def test_repeat_rearms_done_step() -> None:
    runner = ProtocolRunner()
    runner.start("lv_linear")
    runner.arm(0)
    runner.set_projection(_ed())
    runner.advance_now()
    assert runner.armed_index == 1
    runner.repeat(0)
    assert runner.armed_index == 0


def test_shared_value_from_other_protocol_counts_as_done() -> None:
    runner = ProtocolRunner()
    runner.start("lv_linear")
    runner.arm(0)
    runner.set_projection(_ed(origin="la_volume"))
    assert runner.pending_advance == 1


def test_stale_value_does_not_complete_step() -> None:
    runner = ProtocolRunner()
    runner.start("lv_linear")
    runner.arm(0)
    runner.set_projection(StudyProjection(values=_values(_ED, stale=True)))
    assert runner.pending_advance is None


def test_study_change_stops_protocol() -> None:
    runner = ProtocolRunner()
    runner.start("lv_linear")
    reasons: list[str] = []
    runner.stopped.connect(reasons.append)
    runner.on_study_changed()
    assert not runner.active
    assert reasons == ["study_changed"]


def test_finish_emitted_when_all_steps_done() -> None:
    runner = ProtocolRunner()
    finished: list[str] = []
    runner.finished.connect(finished.append)
    runner.start("lv_linear")
    runner.arm(0)
    runner.set_projection(_ed())
    runner.advance_now()
    runner.set_projection(_completed())
    assert finished == ["lv_linear"]


def test_unknown_protocol_rejected() -> None:
    runner = ProtocolRunner()
    try:
        runner.start("nope")
    except KeyError:
        return
    raise AssertionError("expected KeyError")
