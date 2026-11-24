"""Behavioural tests for the CT/MR surface controller (spec 557, 474).

``CtMrSurfaceController`` owns the routing between the ultrasound surface and
the CT/MR stack viewer.  The controller drives widgets through a protocol, so
these tests use a lightweight ``QStackedWidget``-backed double — no
``MainWindow`` required.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QStackedWidget, QWidget

from echo_personal_tool.application.tab_session import TabSession, TabSessionManager
from echo_personal_tool.domain.models.metadata import (
    InstanceMetadata,
    SeriesMetadata,
    StudyMetadata,
)
from echo_personal_tool.presentation.ctmr_surface_controller import CtMrSurfaceController


def _us_study(prefix: str = "us") -> StudyMetadata:
    """An ultrasound study — ``build_ctmr_index`` returns ``None`` for it."""
    instance = InstanceMetadata(
        sop_instance_uid=f"{prefix}.0",
        series_uid=f"{prefix}.series",
        modality="US",
        number_of_frames=4,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="A4C",
        path=None,
    )
    series = SeriesMetadata(
        series_uid=f"{prefix}.series",
        study_uid=f"{prefix}.study",
        modality="US",
        description="Echo",
        instances=(instance,),
    )
    return StudyMetadata(
        study_uid=f"{prefix}.study",
        study_datetime=datetime(2026, 11, 20, 9),
        series=(series,),
    )


class _SurfaceDouble:
    """Minimal window double implementing the CtMrSurfaceWindow protocol."""

    def __init__(self) -> None:
        self._content_widget = QWidget()
        self._viewer_stack = QStackedWidget(self._content_widget)
        self._viewer = QWidget()
        self._viewer_stack.addWidget(self._viewer)
        self._gallery = QWidget()
        self._tool_panel = QWidget()
        self._tool_rail: QWidget | None = QWidget()
        self._rebuild_layout_calls = 0
        self._tabs = TabSessionManager()

    def _rebuild_layout(self) -> None:
        self._rebuild_layout_calls += 1

    @property
    def _tabs_prop(self):
        return self._tabs

    # The protocol names ``_tabs`` as a property; expose it that way.
    @property
    def _tabs_(self):  # noqa: N802
        return self._tabs


# ``_tabs`` is a property on the protocol, so the double needs it as a property.
# Reassign the attribute name to match the protocol exactly.
class _WindowDouble(_SurfaceDouble):
    @property
    def _tabs(self):  # type: ignore[override]
        return self._tabs_prop


def _make_controller(qtbot) -> tuple[CtMrSurfaceController, _WindowDouble]:
    window = _WindowDouble()
    qtbot.addWidget(window._viewer_stack)
    controller = CtMrSurfaceController(window)
    controller.create_viewer()
    return controller, window


def test_is_active_false_initially(qtbot) -> None:
    controller, _ = _make_controller(qtbot)
    assert controller.is_active is False


def test_create_viewer_adds_widget_to_stack(qtbot) -> None:
    controller, window = _make_controller(qtbot)
    viewer = controller._viewer
    assert viewer is not None
    # The stack has at least the ultrasound viewer and the CT/MR viewer.
    assert window._viewer_stack.count() >= 2
    assert window._viewer_stack.widget(0) is window._viewer


def test_apply_ultrasound_keeps_surface_inactive(qtbot) -> None:
    controller, window = _make_controller(qtbot)
    controller.apply([_us_study()])
    assert controller.is_active is False
    # Ultrasound viewer stays visible.
    assert not window._viewer.isHidden()


def test_apply_empty_studies_keeps_inactive(qtbot) -> None:
    controller, _ = _make_controller(qtbot)
    controller.apply([])
    assert controller.is_active is False


def test_apply_layout_visibility_returns_false_when_inactive(qtbot) -> None:
    controller, _ = _make_controller(qtbot)
    assert controller.apply_layout_visibility() is False


def test_show_stack_viewer_inactive_is_noop(qtbot) -> None:
    controller, window = _make_controller(qtbot)
    controller.show_stack_viewer()
    # When inactive the current widget is not switched to the CT/MR viewer.
    assert window._viewer_stack.currentWidget() is not controller._viewer


def test_sync_with_no_active_tab_is_inactive(qtbot) -> None:
    controller, _ = _make_controller(qtbot)
    controller.sync()
    assert controller.is_active is False


def test_sync_with_ultrasound_tab_is_inactive(qtbot) -> None:
    controller, window = _make_controller(qtbot)
    tab = TabSession(
        tab_id="t1",
        origin="folder",
        root="/tmp",
        cache_session_id="c1",
        studies=[_us_study()],
    )
    window._tabs._tabs.append(tab)
    window._tabs._active_id = "t1"
    controller.sync()
    assert controller.is_active is False
