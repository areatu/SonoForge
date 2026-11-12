"""Isolated contract tests for the ViewerZoom owner (A3)."""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui
pytest.importorskip("pytestqt")

from PySide6.QtCore import QPointF, Qt

from echo_personal_tool.presentation.viewer.zoom import ZOOM_MAX, ZOOM_MIN, ViewerZoom


class _Viewport:
    def __init__(self, width: int = 800, height: int = 600) -> None:
        self._width = width
        self._height = height

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class _Graphics:
    def __init__(self, *, dpr: float = 1.0) -> None:
        self._dpr = dpr
        self._viewport = _Viewport()

    def devicePixelRatioF(self) -> float:  # noqa: N802 - Qt API name
        return self._dpr

    def viewport(self) -> _Viewport:
        return self._viewport

    def mapToScene(self, point):  # noqa: N802 - Qt API name
        return QPointF(float(point.x()), float(point.y()))


class _View:
    def __init__(self) -> None:
        self.ranges: list[tuple[tuple[float, float], tuple[float, float]]] = []

    def setRange(self, *, xRange, yRange, padding: int = 0) -> None:  # noqa: N802 - Qt API name
        del padding
        self.ranges.append((tuple(xRange), tuple(yRange)))


class _Event:
    def __init__(
        self,
        x: float = 400.0,
        y: float = 300.0,
        *,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    ) -> None:
        self._position = QPointF(x, y)
        self._modifiers = modifiers
        self.accepted = False

    def position(self) -> QPointF:
        return self._position

    def modifiers(self) -> Qt.KeyboardModifier:
        return self._modifiers

    def accept(self) -> None:
        self.accepted = True


class _Harness:
    def __init__(self) -> None:
        self.graphics = _Graphics()
        self.view = _View()
        self.frame: np.ndarray | None = np.zeros((100, 200), dtype=np.uint8)
        self.hints: list[str] = []
        self.cursor_refreshes = 0
        self.zoom = ViewerZoom(
            graphics=self.graphics,
            view=self.view,
            frame_provider=lambda: self.frame,
            set_hint=self.hints.append,
            refresh_cursor=self._refresh_cursor,
        )

    def _refresh_cursor(self) -> None:
        self.cursor_refreshes += 1


@pytest.fixture
def harness() -> _Harness:
    return _Harness()


def test_cycle_is_fit_100_200_fit(harness: _Harness) -> None:
    seen = [harness.zoom.mode]
    for _ in range(3):
        harness.zoom.cycle_mode()
        seen.append(harness.zoom.mode)

    assert seen == ["fit", "100%", "200%", "fit"]


def test_cycle_from_custom_goes_to_100(harness: _Harness) -> None:
    harness.zoom.zoom_around(10, 10, 2.0)
    assert harness.zoom.mode == "custom"

    harness.zoom.cycle_mode()

    assert harness.zoom.mode == "100%"
    assert harness.zoom.factor == 1.0


def test_invalid_mode_is_ignored_without_resetting_the_factor(harness: _Harness) -> None:
    harness.zoom.zoom_around(10, 10, 2.0)

    harness.zoom.set_mode("bogus")

    assert harness.zoom.mode == "custom"
    assert harness.zoom.factor == pytest.approx(2.0)


def test_step_mode_stops_at_the_named_ends(harness: _Harness) -> None:
    harness.zoom.step_mode(-1)
    assert harness.zoom.mode == "fit"

    for _ in range(4):
        harness.zoom.step_mode(1)
    assert harness.zoom.mode == "200%"


def test_apply_mode_without_a_frame_does_nothing(harness: _Harness) -> None:
    harness.frame = None

    harness.zoom.apply_mode()

    assert harness.view.ranges == []


def test_apply_fit_uses_the_frame_bounds(harness: _Harness) -> None:
    harness.zoom.apply_mode()

    assert harness.view.ranges[-1] == ((0, 200), (0, 100))


def test_apply_100_uses_the_viewport_around_the_frame_centre(harness: _Harness) -> None:
    harness.zoom.set_mode("100%")

    assert harness.view.ranges[-1] == ((-300.0, 500.0), (-250.0, 350.0))


def test_apply_200_uses_a_quarter_viewport(harness: _Harness) -> None:
    harness.zoom.set_mode("200%")

    assert harness.view.ranges[-1] == ((-100.0, 300.0), (-100.0, 200.0))


def test_zoom_around_without_a_frame_returns_false(harness: _Harness) -> None:
    harness.frame = None

    assert harness.zoom.zoom_around(10, 10, 2.0) is False
    assert harness.zoom.factor == 1.0
    assert harness.zoom.mode == "fit"


def test_zoom_around_same_factor_is_a_noop(harness: _Harness) -> None:
    assert harness.zoom.zoom_around(10, 10, 1.0) is False
    assert harness.view.ranges == []


def test_zoom_around_clamps_and_marks_the_mode_custom(harness: _Harness) -> None:
    assert harness.zoom.zoom_around(10, 10, 1e6) is True
    assert harness.zoom.factor == pytest.approx(ZOOM_MAX)
    assert harness.zoom.mode == "custom"
    assert harness.zoom.preserve_range is True

    assert harness.zoom.zoom_around(10, 10, 1e-6) is True
    assert harness.zoom.factor == pytest.approx(ZOOM_MIN)


def test_ctrl_wheel_requires_a_frame(harness: _Harness) -> None:
    harness.frame = None
    event = _Event()

    assert harness.zoom.handle_ctrl_wheel(event, 120) is False
    assert event.accepted is False


def test_ctrl_wheel_zooms_and_accepts_the_event(harness: _Harness) -> None:
    event = _Event()

    assert harness.zoom.handle_ctrl_wheel(event, 120) is True
    assert harness.zoom.factor == pytest.approx(1.1)
    assert event.accepted is True


def test_ctrl_wheel_reverse_zooms_out(harness: _Harness) -> None:
    harness.zoom.zoom_around(10, 10, 2.0)
    event = _Event()

    assert harness.zoom.handle_ctrl_wheel(event, -120) is True
    assert harness.zoom.factor == pytest.approx(2.0 / 1.1)


def test_loupe_arm_sets_and_clears_the_hint(harness: _Harness) -> None:
    harness.zoom.set_loupe_active(True)
    assert harness.zoom.loupe_active is True
    assert harness.zoom.loupe_hint
    assert harness.hints[-1] == harness.zoom.loupe_hint
    assert harness.cursor_refreshes == 1

    harness.zoom.set_loupe_active(False)
    assert harness.zoom.loupe_active is False
    assert harness.zoom.loupe_hint == ""
    assert harness.hints[-1] == ""
    assert harness.cursor_refreshes == 2


def test_loupe_click_without_a_frame_is_ignored(harness: _Harness) -> None:
    harness.frame = None
    harness.zoom.set_loupe_active(True)

    assert harness.zoom.loupe_click(_Event()) is False
    assert harness.zoom.factor == 1.0


def test_loupe_click_and_shift_click_change_the_factor(harness: _Harness) -> None:
    harness.zoom.set_loupe_active(True)

    assert harness.zoom.loupe_click(_Event()) is True
    assert harness.zoom.factor == pytest.approx(1.6)
    assert "160" in harness.zoom.loupe_hint

    shift = _Event(modifiers=Qt.KeyboardModifier.ShiftModifier)
    assert harness.zoom.loupe_click(shift) is True
    assert harness.zoom.factor == pytest.approx(1.0)


def test_loupe_status_is_silent_when_disarmed(harness: _Harness) -> None:
    harness.zoom.loupe_status()

    assert harness.hints == []
    assert harness.zoom.loupe_hint == ""


def test_preserve_range_is_true_for_named_zoom_modes(harness: _Harness) -> None:
    assert harness.zoom.preserve_range is False

    harness.zoom.set_mode("100%")
    assert harness.zoom.preserve_range is True
