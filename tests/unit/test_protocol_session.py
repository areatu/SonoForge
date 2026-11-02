"""Сессия протокола: проекция с контекстом вкладки и статусы строк (TP-3 PR-3).

Сессия — единственное место, где раннер протокола встречается с
``AppController.study_projection``: контекст открытого клипа приходит замыканием
(тонкий адаптер вьюера), а ``authored``/``protocol_id`` — из раннера.  Тесты
ловят аргументы сборки проекции на фейковом контроллере, окно не нужно.
"""

from __future__ import annotations

from echo_personal_tool.application.protocol_runner import StepAction
from echo_personal_tool.application.protocol_session import ProtocolSession
from echo_personal_tool.application.tool_status import ToolState
from echo_personal_tool.domain.protocols import ProjectionValue, StudyProjection

_ED = ("lv.ivsd", "lv.lvedd", "lv.lvpwd")


def _values(keys, *, origin: str = "") -> dict:
    return {key: ProjectionValue(value=1.0, origin=origin) for key in keys}


class _FakeController:
    """Ловит kwargs ``study_projection`` и отдаёт заранее заданную проекцию."""

    def __init__(self, projection: StudyProjection | None = None) -> None:
        self.projection = projection if projection is not None else StudyProjection()
        self.calls: list[dict] = []

    def study_projection(self, **kwargs) -> StudyProjection:
        self.calls.append(kwargs)
        return self.projection


def _session(
    *,
    projection: StudyProjection | None = None,
    clip: tuple[frozenset[str], str] = (frozenset({"2d"}), ""),
) -> tuple[ProtocolSession, _FakeController]:
    controller = _FakeController(projection)
    session = ProtocolSession(
        controller,
        clip_context=lambda: clip,
        language="ru",
        auto_advance_ms=0,
    )
    return session, controller


def test_start_passes_clip_context_protocol_and_empty_authored() -> None:
    session, controller = _session()
    session.start("lv_linear")
    first = controller.calls[0]
    assert first["clip_modes"] == frozenset({"2d"})
    assert first["clip_view"] == ""
    assert first["protocol_id"] == "lv_linear"
    assert first["authored"] == frozenset()


def test_clip_context_is_read_on_every_refresh() -> None:
    """Адаптер вьюера читается заново: смена режима клипа меняет блокировки."""
    cell = [[frozenset({"2d"}), ""]]
    controller = _FakeController()
    session = ProtocolSession(
        controller,
        clip_context=lambda: (cell[0][0], cell[0][1]),
        language="ru",
        auto_advance_ms=0,
    )
    session.start("lv_linear")
    assert controller.calls[0]["clip_modes"] == frozenset({"2d"})
    assert controller.calls[0]["clip_view"] == ""

    cell[0] = [frozenset({"cw"}), "PLAX"]
    session.refresh()
    assert controller.calls[-1]["clip_modes"] == frozenset({"cw"})
    assert controller.calls[-1]["clip_view"] == "PLAX"


def test_arm_emits_step_action_with_tool_and_satisfied_keys() -> None:
    session, _ = _session()
    actions: list[StepAction] = []
    session.action_requested.connect(actions.append)
    session.start("lv_linear")
    session.arm(0)
    assert [a.index for a in actions] == [0]
    assert actions[0].tool_id == "lv.linear_ed"
    assert actions[0].frame_hint == "ed"
    assert "lv.ivsd" in actions[0].satisfied_by


def test_statuses_reflect_the_projection_and_are_reemitted() -> None:
    projection = StudyProjection(values=_values(_ED))
    session, controller = _session(projection=projection)
    statuses_batches: list[tuple] = []
    session.statuses_changed.connect(statuses_batches.append)
    session.start("lv_linear")
    assert statuses_batches, "start() must publish the row statuses"
    by_key = {status.key: status for status in statuses_batches[-1]}
    assert by_key["lv.ivsd"].state is ToolState.DONE
    assert by_key["lv.ivsd"].text

    controller.projection = StudyProjection()
    session.refresh()
    assert {status.key: status for status in statuses_batches[-1]}["lv.ivsd"].state is ToolState.NONE


def test_completion_records_authored_keys_and_finishes() -> None:
    session, controller = _session()
    finished: list[str] = []
    session.finished.connect(finished.append)
    session.start("lv_linear")
    session.arm(0)
    # Шаг 0 закрыт значениями МЖП/КДР/ЗСЛЖ — автопереход взводит шаг 1.
    controller.projection = StudyProjection(values=_values(_ED))
    session.refresh()
    assert session.runner.pending_advance == 1
    assert controller.calls[-1]["authored"] == frozenset(_ED)

    session.runner.advance_now()
    values = _values(_ED)
    values["lv.lvesd"] = ProjectionValue(value=1.0)
    controller.projection = StudyProjection(values=values)
    session.refresh()
    assert finished == ["lv_linear"]
    assert controller.calls[-1]["authored"] == frozenset(_ED) | {"lv.lvesd"}
    assert controller.calls[-1]["protocol_id"] == "lv_linear"


def test_auto_advance_notifies_and_arms_the_next_step() -> None:
    session, controller = _session()
    notes: list[str] = []
    session.notification.connect(notes.append)
    actions: list[StepAction] = []
    session.action_requested.connect(actions.append)
    session.start("simpson_biplane")
    session.arm(0)
    controller.projection = StudyProjection(values=_values(("lv.edv_a4c",)))
    session.refresh()
    assert notes == ["auto_advance"]
    assert session.runner.pending_advance == 1
    session.runner.advance_now()
    assert [a.index for a in actions] == [0, 1]


def test_escape_stops_the_protocol_and_clears_it() -> None:
    from echo_personal_tool.application.protocol_runner import EscapeResult

    session, _ = _session()
    stopped: list[str] = []
    session.stopped.connect(stopped.append)
    session.start("lv_linear")
    assert session.on_escape() is EscapeResult.STOPPED
    assert stopped == ["escape"]
    assert session.active is False
    assert session.progress is None


def test_study_change_stops_the_protocol() -> None:
    session, _ = _session()
    session.start("lv_linear")
    session.on_study_changed()
    assert session.active is False
    assert session.active_protocol_id == ""


def test_stop_without_a_protocol_is_silent() -> None:
    session, _ = _session()
    stopped: list[str] = []
    session.stopped.connect(stopped.append)
    session.stop("user")
    assert stopped == []
    assert session.active is False
