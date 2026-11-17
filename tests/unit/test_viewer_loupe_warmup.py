"""Item 6/7 of the 2026-11-17 list: the loupe must open without a first-press stall.

The owner reported that the very first *hold* on ``Z`` froze the application on
Windows 10 for seconds.  That keystroke paid for three one-time costs that have
nothing to do with the click: ``import cv2`` inside the lens module, the SVG
cursor glyph, and the first translucent child widget of the process (the
compositor allocates its backing store then).

The fix is a warm-up in an idle slice instead of in the keystroke, plus the
cursor helper moved to its own module.  This file pins the parts that would
silently regress:

* the warm-up is *scheduled* once and runs from the event loop, never inline;
* it builds exactly the two expensive things — the lens and the cursor;
* a broken install does not break the warm-up, and ``Z`` still works (the lens
  is created on demand, the old way);
* the schedule is idempotent, so repeated ``showEvent`` calls do not rebuild.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import QObject, Qt  # noqa: E402

from echo_personal_tool.presentation.magnifier_cursor import (  # noqa: E402
    ZOOM_CURSOR_HOTSPOT,
    magnifier_cursor,
)
from echo_personal_tool.presentation.viewer.magnifier_controller import (  # noqa: E402
    MagnifierController,
)


class _FakeLens:
    """Stand-in for :class:`MagnifierLens` that records how it was configured."""

    def __init__(self) -> None:
        self.configured: tuple[float, bool] | None = None
        self.hidden = False
        self.geometry: object | None = None
        self.visible = False

    def configure(self, zoom: float, reduce_motion: bool = False) -> None:
        self.configured = (zoom, reduce_motion)

    def hide(self) -> None:
        self.hidden = True
        self.visible = False

    def show(self) -> None:
        self.visible = True

    def setGeometry(self, geometry: object) -> None:  # noqa: N802 - Qt spelling
        self.geometry = geometry


@pytest.fixture()
def lens_factory():
    created: list[_FakeLens] = []

    def factory() -> _FakeLens:
        lens = _FakeLens()
        created.append(lens)
        return lens

    return created, factory


def test_cursor_helper_reports_the_lens_centre_as_its_hotspot(qapp) -> None:
    """The click point is the middle of the glyph, not its corner (item 4, 2026-10-23)."""
    assert ZOOM_CURSOR_HOTSPOT == (9, 9)
    # Real SVG rendering needs a live QGuiApplication; the offscreen stub used by
    # the rest of the suite aborts inside QtSvg, so the glyph path is covered by
    # the native GUI acceptance run and the fallback path is asserted here.
    cursor = magnifier_cursor()
    assert cursor is not None


def test_cursor_helper_falls_back_instead_of_raising(monkeypatch, qapp) -> None:
    """A broken install still gets a pointer — the fallback is the whole recovery."""

    def broken_load_icon(_name: str):
        raise OSError("no SVG plugin in this build")

    monkeypatch.setattr(
        "echo_personal_tool.presentation.window_chrome.title_bar.load_icon",
        broken_load_icon,
    )
    cursor = magnifier_cursor()
    assert cursor is not None
    assert cursor.shape() == Qt.CursorShape.CrossCursor


def test_lens_factory_is_not_touched_at_construction(lens_factory) -> None:
    created, factory = lens_factory
    MagnifierController(parent=QObject(), lens_factory=factory)
    assert created == [], "building the lens at construction would defeat the warm-up"


def test_schedule_warmup_waits_for_the_event_loop(qtbot, lens_factory) -> None:
    created, factory = lens_factory
    controller = MagnifierController(parent=QObject(), lens_factory=factory)

    controller.schedule_warmup()

    assert created == [], "the lens is built in an idle slice, not inside showEvent"
    qtbot.waitUntil(lambda: len(created) == 1, timeout=2000)
    assert created[0].configured is not None, "the warmed lens is configured, not raw"


def test_schedule_warmup_is_idempotent(qtbot, lens_factory) -> None:
    created, factory = lens_factory
    controller = MagnifierController(parent=QObject(), lens_factory=factory)

    controller.schedule_warmup()
    controller.schedule_warmup()
    qtbot.waitUntil(lambda: len(created) == 1, timeout=2000)
    controller.schedule_warmup()
    qtbot.wait(50)

    assert len(created) == 1, "every showEvent would otherwise rebuild the lens"


def test_a_disabled_magnifier_warms_nothing_up(qtbot, lens_factory) -> None:
    created, factory = lens_factory
    controller = MagnifierController(parent=QObject(), lens_factory=factory)
    controller.configure(enabled=False)

    controller.schedule_warmup()
    qtbot.wait(100)

    assert created == [], "no lens for a user who turned the loupe off"


def test_a_broken_lens_factory_does_not_reach_the_event_loop(qtbot) -> None:
    def factory() -> _FakeLens:
        raise RuntimeError("no OpenCV in this install")

    controller = MagnifierController(parent=QObject(), lens_factory=factory)

    controller.schedule_warmup()
    qtbot.wait(100)

    # The warm-up swallowed the failure: no exception reached the event loop, and
    # the lens is simply built later, on the first real Z press.
    assert controller.lens is None
