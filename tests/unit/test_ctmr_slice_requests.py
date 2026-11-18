"""Synthetic classic CT/MR lazy decode and cancellation; no clinical validation."""

from threading import Event
from time import monotonic, sleep

import numpy as np
import pydicom
import pytest
from pydicom.uid import MRImageStorage

from echo_personal_tool.application.ctmr_slice_requests import CtMrSliceRequests
from echo_personal_tool.infrastructure.ctmr_index import index_ctmr_files
from echo_personal_tool.infrastructure.ctmr_slice_reader import (
    SliceReadCancelled,
    SliceSourceChanged,
    read_ctmr_slice,
    source_is_current,
)

pytest_plugins = ("tests.unit.test_ctmr_stacks",)


def _pixels(path, value):
    ds = pydicom.dcmread(path)
    ds.PixelData = np.full((16, 24), value, dtype="<i2").tobytes()
    ds.save_as(path, enforce_file_format=True)


def _receive(service):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        result = service.poll()
        if result is not None:
            return result
        sleep(0.005)
    pytest.fail("slice result did not arrive")


@pytest.mark.parametrize("modality", ["CT", "MR"])
def test_lazy_order_maps_to_exact_sop_and_frame(make_file, monkeypatch, modality):
    tags = {"SOPClassUID": MRImageStorage, "Modality": "MR"} if modality == "MR" else {}
    paths = [make_file("z", z=2, **tags), make_file("a", z=-1, **tags), make_file("m", z=0, **tags)]
    for path, value in zip(paths, (22, -12, 7), strict=True):
        _pixels(path, value)
    stack = index_ctmr_files(paths).stacks[0]
    calls = []

    def reader(ref, cancelled):
        calls.append((ref.sop_uid, ref.local_frame))
        return read_ctmr_slice(ref, cancelled)

    service = CtMrSliceRequests(reader, source_is_current)
    try:
        service.select_stack(stack)
        assert not calls
        for i, value in enumerate((-12, 7, 22)):
            ticket = service.request(i)
            result = _receive(service)
            assert result.ticket is ticket and result.error is None and service.claim(result)
            assert result.ticket.ref == stack.frames[i] and result.ticket.ref.local_frame == 0
            assert np.all(result.pixels == value)
            assert not service.claim(result)
        assert calls == [(ref.sop_uid, 0) for ref in stack.frames]
    finally:
        service.close()


def test_duplicate_sop_uses_only_index_selected_file_and_conflicts_are_quarantined(make_file):
    a = make_file("a", sop="1.2.3.40")
    b = make_file("b", sop="1.2.3.40")
    _pixels(a, 4)
    _pixels(b, 9)
    result = index_ctmr_files([b, a])
    assert [d.code for d in result.diagnostics] == ["duplicate_sop_pixels_unverified"]
    assert len(result.stacks[0].frames) == 1
    assert np.all(read_ctmr_slice(result.stacks[0].frames[0]) == 4)
    conflict = make_file("c", z=7, sop="1.2.3.40")
    result = index_ctmr_files([a, conflict])
    assert not result.stacks and {d.code for d in result.diagnostics} == {"conflicting_sop"}


def test_source_replacement_rejected_before_decode_and_before_claim(make_file):
    path = make_file("a")
    stack = index_ctmr_files([path]).stacks[0]
    service = CtMrSliceRequests(read_ctmr_slice, source_is_current)
    try:
        service.select_stack(stack)
        service.request(0)
        result = _receive(service)
        _pixels(path, 12)
        assert not service.claim(result)
        with pytest.raises(SliceSourceChanged):
            read_ctmr_slice(stack.frames[0])
        service.request(0)
        result = _receive(service)
        assert result.error == "slice_read_failed" and service.claim(result)
    finally:
        service.close()


def test_cancellation_coalesces_pending_and_switching_series_aba(make_file):
    a = make_file("a", z=0)
    b = make_file("b", z=1)
    c = make_file("c", SeriesInstanceUID="1.2.10.2")
    stack_a, stack_b = index_ctmr_files([a, b, c]).stacks
    started, release = Event(), Event()
    calls = []

    def blocked(ref, cancelled):
        calls.append(ref)
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
        return read_ctmr_slice(ref, cancelled)

    service = CtMrSliceRequests(blocked, source_is_current)
    try:
        service.select_stack(stack_a)
        old = service.request(0)
        assert started.wait(5)
        overwritten = service.request(1)
        service.select_stack(stack_b)
        other = service.request(0)
        service.select_stack(stack_a)
        latest = service.request(1)
        assert old.cancelled.is_set() and overwritten.cancelled.is_set() and other.cancelled.is_set()
        release.set()
        result = _receive(service)
        assert result.ticket is latest and service.claim(result)
        assert calls == [old.ref, latest.ref]
        assert service.poll() is None
    finally:
        release.set()
        service.close()


def test_late_queued_result_rejected_after_switch_or_cancel(make_file):
    stack = index_ctmr_files([make_file("a")]).stacks[0]
    service = CtMrSliceRequests(read_ctmr_slice, source_is_current)
    try:
        service.select_stack(stack)
        old = service.request(0)
        result = _receive(service)
        service.select_stack(stack)
        assert old.cancelled.is_set() and not service.claim(result)
        service.request(0)
        result = _receive(service)
        service.cancel()
        assert not service.claim(result)
    finally:
        service.close()


def test_decode_cancellation_and_file_change_during_decode(make_file, monkeypatch):
    from echo_personal_tool.infrastructure import ctmr_slice_reader

    path = make_file("a")
    ref = index_ctmr_files([path]).stacks[0].frames[0]
    calls = []
    original = ctmr_slice_reader.pixel_array

    def changed(*args, **kwargs):
        calls.append(1)
        result = original(*args, **kwargs)
        _pixels(path, 42)
        return result

    monkeypatch.setattr(ctmr_slice_reader, "pixel_array", changed)
    with pytest.raises(SliceReadCancelled):
        read_ctmr_slice(ref, lambda: True)
    assert not calls
    with pytest.raises(SliceSourceChanged):
        read_ctmr_slice(ref)
    assert len(calls) == 1


def test_invalid_requests_and_close(make_file):
    stack = index_ctmr_files([make_file("a")]).stacks[0]
    service = CtMrSliceRequests(read_ctmr_slice, source_is_current)
    with pytest.raises(IndexError):
        service.request(0)
    service.select_stack(stack)
    for index in (-1, 1, True):
        with pytest.raises(IndexError):
            service.request(index)
    service.close()
    service.close()
    with pytest.raises(RuntimeError):
        service.request(0)
    with pytest.raises(RuntimeError):
        service.select_stack(stack)


def test_many_rapid_requests_keep_only_latest_pending(make_file):
    stack = index_ctmr_files([make_file("a"), make_file("b", z=1)]).stacks[0]
    started, release = Event(), Event()
    calls = []

    def blocked(ref, cancelled):
        calls.append(ref)
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
        return read_ctmr_slice(ref, cancelled)

    service = CtMrSliceRequests(blocked, source_is_current)
    try:
        service.select_stack(stack)
        first = service.request(0)
        assert started.wait(5)
        for _ in range(1000):
            service.request(0)
        last = service.request(1)
        assert first.cancelled.is_set()
        release.set()
        result = _receive(service)
        assert result.ticket is last and service.claim(result)
        assert calls == [first.ref, last.ref]
    finally:
        release.set()
        service.close()


def test_late_error_cannot_reach_new_series_and_current_error_is_sanitized(make_file):
    stack = index_ctmr_files([make_file("a")]).stacks[0]

    def broken(ref, cancelled):
        raise ValueError("private path and header data")

    service = CtMrSliceRequests(broken, source_is_current)
    try:
        service.select_stack(stack)
        service.request(0)
        old = _receive(service)
        assert old.error == "slice_read_failed" and old.pixels is None
        service.select_stack(stack)
        assert not service.claim(old)
        service.request(0)
        current = _receive(service)
        assert current.error == "slice_read_failed" and service.claim(current)
    finally:
        service.close()


def test_close_revokes_result_and_running_decode(make_file):
    stack = index_ctmr_files([make_file("a")]).stacks[0]
    entered, release, done = Event(), Event(), Event()

    def blocked(ref, cancelled):
        entered.set()
        assert release.wait(5)
        try:
            return read_ctmr_slice(ref, cancelled)
        finally:
            done.set()

    service = CtMrSliceRequests(blocked, source_is_current)
    service.select_stack(stack)
    ticket = service.request(0)
    assert entered.wait(5)
    service.close()
    assert ticket.cancelled.is_set() and service.poll() is None
    release.set()
    assert done.wait(5)
    assert service.poll() is None


def test_duplicate_positions_remain_separate_exact_sops(make_file):
    a = make_file("z", z=1, sop="1.2.3.20")
    b = make_file("a", z=1, sop="1.2.3.10")
    _pixels(a, 20)
    _pixels(b, 10)
    stack = index_ctmr_files([a, b]).stacks[0]
    assert not stack.spatial_order_verified and "duplicate_positions" in stack.warnings
    assert [frame.sop_uid for frame in stack.frames] == ["1.2.3.10", "1.2.3.20"]
    assert [int(read_ctmr_slice(frame)[0, 0]) for frame in stack.frames] == [10, 20]
