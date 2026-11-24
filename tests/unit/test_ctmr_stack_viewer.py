"""CtMrStackViewer: multi-page navigation over a CT/MR stack (#557)."""

from threading import Event

import numpy as np

from echo_personal_tool.application.ctmr_slice_requests import SliceResult, SliceTicket
from echo_personal_tool.domain.models.ctmr_stack import CtMrStack
from echo_personal_tool.infrastructure.ctmr_index import index_ctmr_files
from echo_personal_tool.presentation.ctmr_stack_viewer import CtMrStackViewer

pytest_plugins = ("tests.unit.test_ctmr_stacks",)


class _FakeService:
    """Synchronous stand-in for ``CtMrSliceRequests``.

    Returns one deterministic array per frame identity so navigation can be
    checked without touching real files.
    """

    def __init__(self) -> None:
        self._stack: CtMrStack | None = None
        self._result: SliceResult | None = None

    def select_stack(self, stack: CtMrStack | None) -> None:
        self._stack = stack
        self._result = None

    def request(self, index: int) -> SliceTicket:
        stack = self._stack
        assert stack is not None
        ref = stack.frames[index]
        ticket = SliceTicket(ref, index, Event())
        value = (index + 1) * 10
        pixels = np.full((ref.rows, ref.columns), value, dtype=np.int16)
        self._result = SliceResult(ticket, pixels)
        return ticket

    def poll(self):
        result, self._result = self._result, None
        return result

    def claim(self, result: SliceResult) -> bool:
        return result.error is None

    def close(self) -> None:
        self._stack = None


def _make_viewer(qtbot, make_file, **tags):
    index = index_ctmr_files(
        [make_file("z.dcm", z=2, **tags), make_file("a.dcm", z=-1, **tags), make_file("m.dcm", z=0, **tags)]
    )
    viewer = CtMrStackViewer(slice_requests=_FakeService())
    qtbot.addWidget(viewer)
    viewer.show()
    viewer.set_index(index)
    return viewer, index


def _drain(viewer):
    # The fake service resolves synchronously; one poll publishes the slice.
    viewer._on_poll()


def test_first_slice_is_published(qtbot, make_file):
    viewer, index = _make_viewer(qtbot, make_file)
    _drain(viewer)
    assert viewer._canvas._pixmap is not None and not viewer._canvas._pixmap.isNull()
    assert "1 / 3" in viewer._slice_label.text()


def test_step_and_slider_navigate_the_stack(qtbot, make_file):
    viewer, _ = _make_viewer(qtbot, make_file)
    _drain(viewer)
    viewer.step_slice(1)
    _drain(viewer)
    assert viewer._slice_index == 1 and "2 / 3" in viewer._slice_label.text()
    viewer._slider.setValue(2)
    _drain(viewer)
    assert viewer._slice_index == 2 and "3 / 3" in viewer._slice_label.text()
    viewer.step_slice(1)
    assert viewer._slice_index == 2  # clamped at the last slice


def test_cached_slice_is_painted_without_a_service_request(qtbot, make_file):
    viewer, _ = _make_viewer(qtbot, make_file)
    _drain(viewer)
    calls = []
    service = viewer._slice_requests
    original = service.request

    def counting(index):
        calls.append(index)
        return original(index)

    service.request = counting
    viewer._go_to_slice(0)
    _drain(viewer)
    assert calls == []  # cache hit, no new decode


def test_unverified_order_shows_a_warning(qtbot, make_file):
    viewer, _ = _make_viewer(qtbot, make_file, FrameOfReferenceUID=None)
    assert not viewer._warning_label.isHidden()
    assert viewer._warning_label.text()


def test_verified_order_hides_the_warning(qtbot, make_file):
    index = index_ctmr_files([make_file("a.dcm", z=0), make_file("b.dcm", z=2), make_file("c.dcm", z=4)])
    viewer = CtMrStackViewer(slice_requests=_FakeService())
    qtbot.addWidget(viewer)
    viewer.show()
    viewer.set_index(index)
    _drain(viewer)
    assert viewer._warning_label.isHidden()


def test_clear_releases_the_stack(qtbot, make_file):
    viewer, _ = _make_viewer(qtbot, make_file)
    _drain(viewer)
    viewer.clear()
    assert viewer._index is None
    assert viewer._canvas._pixmap is None
    assert viewer._slider.maximum() == 0


def test_multiple_stacks_are_selectable(qtbot, make_file):
    a = make_file("a.dcm", z=0, SeriesInstanceUID="1.2.10.1")
    b = make_file("b.dcm", z=1, SeriesInstanceUID="1.2.10.2")
    index = index_ctmr_files([a, b])
    assert len(index.stacks) == 2
    viewer = CtMrStackViewer(slice_requests=_FakeService())
    qtbot.addWidget(viewer)
    viewer.show()
    seen: list[int] = []
    viewer.stack_changed.connect(seen.append)
    viewer.set_index(index)
    _drain(viewer)
    assert viewer._stack_combo.count() == 2
    viewer._stack_combo.setCurrentIndex(1)
    _drain(viewer)
    assert viewer._stack_index == 1
    assert seen == [1]
