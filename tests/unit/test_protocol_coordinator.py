"""ProtocolCoordinator tested without MainWindow or QWidget."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal

from echo_personal_tool.application.protocol_runner import DEFAULT_AUTO_ADVANCE_MS
from echo_personal_tool.application.protocol_session import ProtocolSession
from echo_personal_tool.domain.protocols import StudyProjection
from echo_personal_tool.presentation.coordinators.protocol_coordinator import ProtocolCoordinator, ProtocolWindowPort


class FakeBar(QObject):
    skip_requested = Signal()
    done_requested = Signal()
    cancel_point_requested = Signal()
    rap_chosen = Signal(float)
    rap_other_requested = Signal()
    rap_reference_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.set_labels = MagicMock()
        self.set_step = MagicMock()
        self.clear = MagicMock()
        self.show_notification = MagicMock()


class FakeHost:
    def __init__(self) -> None:
        self.panel = MagicMock()
        self.panel.is_v2 = True
        self.bar = FakeBar()
        self.source = MagicMock()
        self.source.study_projection.return_value = StudyProjection()
        self.calls: list[str] = []
        self.rap: list[float] = []
        self.drawing = False
        self.answer = (0.0, False)
        self.port = ProtocolWindowPort(
            create_bar=lambda: self.bar,
            create_session=lambda parent: ProtocolSession(
                self.source, clip_context=lambda: (frozenset({"2d"}), ""), parent=parent
            ),
            tool_panel=lambda: self.panel,
            finish_tool=lambda: self.calls.append("finish"),
            open_reference=lambda: self.calls.append("reference"),
            viewer_drawing=lambda: self.drawing,
            cancel_viewer_tool=lambda: self.calls.append("cancel"),
            show_status=self.calls.append,
            ask_rap=lambda: self.answer,
            set_rap=self.rap.append,
        )
        self.coordinator = ProtocolCoordinator(self.port)


def test_port_is_frozen_and_session_is_lazy() -> None:
    host = FakeHost()
    assert host.coordinator.session is None
    assert host.coordinator.step_bar is None
    with pytest.raises(FrozenInstanceError):
        host.port.finish_tool = lambda: None
    session = host.coordinator.ensure_session()
    assert host.coordinator.ensure_session() is session
    assert session.parent() is host.coordinator


def test_selection_arm_skip_and_stop_update_the_panel() -> None:
    host = FakeHost()
    owner = host.coordinator
    owner.select("lv_linear")
    assert owner.is_active()
    session = owner.session
    assert session is not None and session.active_protocol_id == "lv_linear"
    owner.activate_step(0)
    assert session.runner.armed_index == 0
    assert owner.armed_index == 0
    assert host.bar.set_step.called
    host.bar.skip_requested.emit()
    assert session.progress is not None and session.progress.steps[0].state.value == "skipped"
    owner.stop_requested()
    assert not session.active
    assert owner.armed_index is None
    assert host.bar.clear.called
    host.panel.measure.clear_action_highlight.assert_called()


def test_auto_advance_is_remembered_and_default_is_manual() -> None:
    host = FakeHost()
    owner = host.coordinator
    owner.select("lv_linear")
    session = owner.session
    assert session is not None and session.runner.auto_advance_ms == 0
    owner.auto_advance_toggled("lv_linear", True)
    assert session.runner.auto_advance_ms == DEFAULT_AUTO_ADVANCE_MS
    owner.stop_requested()
    owner.select("lv_linear")
    assert session.runner.auto_advance_ms == DEFAULT_AUTO_ADVANCE_MS
    owner.auto_advance_toggled("lv_linear", False)
    assert session.runner.auto_advance_ms == 0


def test_escape_and_study_change_stop_protocol() -> None:
    host = FakeHost()
    owner = host.coordinator
    assert not owner.escape()
    owner.select("lv_linear")
    assert owner.escape()
    assert not owner.is_active()
    owner.select("lv_linear")
    owner.study_changed()
    assert not owner.is_active()


def test_bar_callbacks_and_rap_dialog() -> None:
    host = FakeHost()
    assert host.coordinator.ensure_step_bar() is host.bar
    assert host.coordinator.ensure_step_bar() is host.bar
    host.bar.done_requested.emit()
    host.bar.rap_reference_requested.emit()
    host.bar.rap_chosen.emit(8.0)
    host.answer = (12.0, True)
    host.bar.rap_other_requested.emit()
    host.answer = (20.0, False)
    host.bar.rap_other_requested.emit()
    assert host.calls == ["finish", "reference"]
    assert host.rap == [8.0, 12.0]


def test_escape_cancels_drawing_before_stopping_protocol() -> None:
    host = FakeHost()
    owner = host.coordinator
    owner.select("lv_linear")
    owner.activate_step(0)
    host.drawing = True
    assert owner.escape()
    assert "cancel" in host.calls
    assert owner.is_active()
    host.drawing = False
    assert owner.escape()
    assert not owner.is_active()


def test_pending_advance_can_be_confirmed_or_cancelled() -> None:
    from echo_personal_tool.domain.protocols import ProjectionValue

    host = FakeHost()
    owner = host.coordinator
    owner.select("lv_linear")
    owner.activate_step(0)
    host.source.study_projection.return_value = StudyProjection(
        values={key: ProjectionValue(value=1.0, origin="lv_linear") for key in ("lv.ivsd", "lv.lvedd", "lv.lvpwd")}
    )
    owner.study_projection_changed()
    session = owner.session
    assert session is not None and session.runner.pending_advance == 1
    assert owner.advance_pending()
    assert session.runner.armed_index == 1
    assert not owner.advance_pending()
    owner.activate_step(0)
    owner.study_projection_changed()
    assert session.runner.pending_advance == 1
    assert owner.escape()
    assert session.runner.pending_advance is None
    assert owner.is_active()


def test_deleting_owner_deletes_coordinator_and_session(qapp: object) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    host = FakeHost()
    parent = QObject()
    coordinator = ProtocolCoordinator(host.port, parent=parent)
    session = coordinator.ensure_session()
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(coordinator)
    assert not isValid(session)
