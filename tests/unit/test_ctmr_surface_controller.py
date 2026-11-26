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


def _make_controller(qtbot) -> tuple[CtMrSurfaceController, _SurfaceDouble]:
    window = _SurfaceDouble()
    qtbot.addWidget(window._viewer_stack)
    controller = CtMrSurfaceController(window)
    controller.create_viewer()
    return controller, window


@pytest.fixture(autouse=True)
def _enable_ctmr_surface(monkeypatch) -> None:
    """Exercise the enabled path by default; the gate tests opt out explicitly."""
    monkeypatch.setenv("SONOFORGE_ENABLE_CTMR", "1")


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


def test_surface_is_enabled_by_default(qtbot, monkeypatch) -> None:
    """The CT/MR stack surface mounts by default without needing an env var."""
    monkeypatch.delenv("SONOFORGE_ENABLE_CTMR", raising=False)
    controller, window = _make_controller(qtbot)
    assert controller._viewer is not None
    assert window._viewer_stack.count() >= 2


def test_env_zero_disables_the_surface(qtbot, monkeypatch) -> None:
    """Setting ``SONOFORGE_ENABLE_CTMR=0`` explicitly opts out of the surface."""
    from echo_personal_tool.presentation import ctmr_surface_controller as module

    monkeypatch.setenv("SONOFORGE_ENABLE_CTMR", "0")
    controller, window = _make_controller(qtbot)
    assert controller._viewer is None
    assert window._viewer_stack.count() == 1
    monkeypatch.setattr(module, "build_ctmr_index", lambda studies: object())
    controller.apply([_us_study()])
    assert controller.is_active is False
    assert window._viewer_stack.currentWidget() is window._viewer
    assert controller.apply_layout_visibility() is False
    assert controller.create_viewer() is None


def test_opt_in_routes_a_ready_index(qtbot, monkeypatch) -> None:
    """With the opt-in a truthy index activates the surface and takes over."""
    from echo_personal_tool.presentation import ctmr_surface_controller as module

    controller, window = _make_controller(qtbot)

    class _FakeViewer(QWidget):
        def set_index(self, index: object) -> None:
            self.index = index

        def clear(self) -> None:
            pass

    fake = _FakeViewer()
    window._viewer_stack.addWidget(fake)
    controller._viewer = fake
    monkeypatch.setattr(module, "build_ctmr_index", lambda studies: object())
    controller.apply([_us_study()])
    assert controller.is_active is True
    assert window._viewer_stack.currentWidget() is fake
    assert window._viewer.isHidden()
    assert window._gallery.isHidden()
    assert window._tool_panel.isHidden()
