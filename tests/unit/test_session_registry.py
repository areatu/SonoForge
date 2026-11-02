"""Regression tests for the process-wide DICOM / video session cache.

``threading.local()`` does not survive between ``QRunnable`` invocations: PySide6 enters the
Python override with ``PyGILState_Ensure`` and leaves it with ``PyGILState_Release``, which
destroys the thread state (and its thread-locals) for threads not created by ``threading``.
Per-thread session caching therefore re-read the whole file on every pooled decode — measured
at 1280×720 as 184–219 ms per 2–8 frame batch and 192–638 ms per scrub step
(`docs/bench/2026-09-06-cine-720p-playback-audit.md` §3.1).

These tests pin the replacement contract: **one session per resolved path, shared by every
thread, serialised by a lock**, with memory hygiene moved to file switches.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from echo_personal_tool.infrastructure import dicom_session as ds
from echo_personal_tool.infrastructure import video_reader as vr
from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom
from tests.fixtures.generate_synthetic_media import write_synthetic_mp4


def _reset_caches() -> None:
    ds._cleanup_all_sessions()
    vr._cleanup_all_readers()
    ds._thread_local = threading.local()
    vr._thread_local = threading.local()


@pytest.fixture(autouse=True)
def _clean_registries():
    """Keep the process-wide caches from leaking into (or out of) these tests."""
    _reset_caches()
    yield
    _reset_caches()


def _write_cine(tmp_path: Path, name: str = "cine.dcm", frame_count: int = 5) -> Path:
    path = tmp_path / name
    write_synthetic_multiframe_dicom(path, frame_count=frame_count, rows=16, cols=16)
    return path


# ── DICOM: shared per path ─────────────────────────────────────────


def test_dicom_session_shared_between_qrunnables(tmp_path: Path) -> None:
    """The root-cause regression: pooled runnables must reuse one session."""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QRunnable, QThreadPool

    path = _write_cine(tmp_path)
    session_ids: list[int] = []
    decoded: list[int] = []
    lock = threading.Lock()

    class Job(QRunnable):
        def __init__(self, index: int) -> None:
            super().__init__()
            self._index = index
            self.setAutoDelete(True)

        def run(self) -> None:
            session = ds.get_thread_dicom_session(path)
            session.open(path)
            frame = session.decode_single_frame(self._index)
            with lock:
                session_ids.append(id(session))
                decoded.append(int(frame[0, 0]))

    pool = QThreadPool()
    pool.setMaxThreadCount(2)
    for index in range(5):
        pool.start(Job(index))
    assert pool.waitForDone(30_000), "pooled decode jobs did not finish"

    assert sorted(decoded) == [0, 1, 2, 3, 4]
    assert len(set(session_ids)) == 1, "each runnable built its own session (thread-local is dead in QThreadPool)"
    # One session only ⇒ the file was read once, not once per job.
    assert len(ds._all_sessions) == 1


def test_dicom_session_shared_across_python_threads(tmp_path: Path) -> None:
    path = _write_cine(tmp_path)
    sessions: list[object] = []

    def work(index: int) -> int:
        session = ds.get_thread_dicom_session(path)
        session.open(path)
        sessions.append(session)
        return int(session.decode_single_frame(index)[0, 0])

    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(work, range(5)))

    assert values == [0, 1, 2, 3, 4]
    assert len({id(s) for s in sessions}) == 1


def test_dicom_session_keyed_by_resolved_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_cine(tmp_path, "a.dcm")
    other = _write_cine(tmp_path, "b.dcm", frame_count=3)

    via_path = ds.get_dicom_session(path)
    via_str = ds.get_dicom_session(str(path))
    monkeypatch.chdir(tmp_path)
    via_relative = ds.get_dicom_session(Path("a.dcm"))
    different_file = ds.get_dicom_session(other)

    assert via_path is via_str is via_relative
    assert different_file is not via_path


def test_pathless_getter_stays_thread_local() -> None:
    """Backwards compatibility: no path ⇒ the old per-thread session."""
    main_session = ds.get_thread_dicom_session()
    assert ds.get_thread_dicom_session() is main_session

    other: list[object] = []
    thread = threading.Thread(target=lambda: other.append(ds.get_thread_dicom_session()))
    thread.start()
    thread.join()

    assert other[0] is not main_session


def test_concurrent_decode_of_shared_session_is_consistent(tmp_path: Path) -> None:
    path = _write_cine(tmp_path, frame_count=8)
    session = ds.get_dicom_session(path)
    session.open(path)
    errors: list[str] = []

    def hammer(worker: int) -> None:
        for index in range(8):
            frame = session.decode_single_frame(index)
            if int(frame[0, 0]) != index:
                errors.append(f"worker {worker}: frame {index} == {int(frame[0, 0])}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(hammer, range(6)))

    assert errors == []


# ── DICOM: memory hygiene ──────────────────────────────────────────


def test_release_stale_sessions_frees_others_but_keeps_them_usable(tmp_path: Path) -> None:
    first = _write_cine(tmp_path, "first.dcm")
    second = _write_cine(tmp_path, "second.dcm")

    session_first = ds.get_dicom_session(first)
    session_first.open(first)
    session_first.decode_single_frame(0)  # materialises the heavy pixel buffer
    assert session_first._has_loadable_pixels()

    session_second = ds.get_dicom_session(second)
    session_second.open(second)  # switches file → releases the other session

    assert not session_first._has_loadable_pixels(), "stale session still pins the pixel buffer"
    # Still registered: re-opening the first file reuses the same object (metadata kept).
    assert ds.get_dicom_session(first) is session_first
    session_first.open(first)
    assert session_first._has_loadable_pixels()
    assert int(session_first.decode_single_frame(2)[0, 0]) == 2


def test_open_reloads_when_the_file_changed_on_disk(tmp_path: Path) -> None:
    path = _write_cine(tmp_path, "cine.dcm", frame_count=3)
    session = ds.get_dicom_session(path)
    session.open(path)
    assert session.frame_count == 3

    # The uncompressed pixel block is mapped (dicom_session._map_pixel_data), and Windows
    # denies write access to a file while a section is mapped over it (ERROR_USER_MAPPED_FILE,
    # which surfaces as OSError EINVAL from open(path, "wb")). Replacing a loaded file
    # therefore starts with releasing it - the contract documented in the audit, section 4.2.
    # Switching instances does this on its own (release_stale_sessions -> release_heavy).
    session.release_heavy()
    assert session._pixel_data_raw is None, "the mapping must be gone before the rewrite"

    write_synthetic_multiframe_dicom(path, frame_count=6, rows=16, cols=16)
    session.open(path)

    assert session.frame_count == 6
    assert int(session.decode_single_frame(5)[0, 0]) == 5


def test_registry_prunes_oldest_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ds, "_max_sessions", 2)
    paths = [_write_cine(tmp_path, f"cine{i}.dcm", frame_count=2) for i in range(3)]

    sessions = [ds.get_dicom_session(p) for p in paths]

    assert len(ds._all_sessions) == 2
    assert sessions[0].frame_count == 0, "pruned session was not released"
    # The pruned path is forgotten, so a fresh session is created for it.
    assert ds.get_dicom_session(paths[0]) is not sessions[0]
    assert ds.get_dicom_session(paths[2]) is sessions[2]


# ── Video reader: same contract ────────────────────────────────────


def test_video_reader_shared_per_path(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    write_synthetic_mp4(clip, frame_count=6, width=32, height=24)
    other = tmp_path / "other.mp4"
    write_synthetic_mp4(other, frame_count=3, width=32, height=24)

    reader = vr.get_thread_video_reader(clip)
    assert vr.get_thread_video_reader(str(clip)) is reader
    assert vr.get_video_reader(clip) is reader
    assert vr.get_thread_video_reader(other) is not reader

    reader.open(clip)
    frames = [reader.read_frame(i) for i in range(6)]
    assert [int(f[0, 0, 0]) for f in frames] == list(range(6))


def test_video_reader_shared_across_threads(tmp_path: Path) -> None:
    """cv2.VideoCapture is not thread-safe: a shared reader must serialise reads."""
    clip = tmp_path / "clip.mp4"
    write_synthetic_mp4(clip, frame_count=8, width=32, height=24)
    reader = vr.get_video_reader(clip)
    reader.open(clip)
    errors: list[str] = []

    def read(index: int) -> None:
        frame = reader.read_frame(index)
        if int(frame[0, 0, 0]) != index % 256:
            errors.append(f"frame {index} == {int(frame[0, 0, 0])}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(read, list(range(8)) * 3))

    assert errors == []


def test_video_reader_pathless_getter_stays_thread_local(tmp_path: Path) -> None:
    main_reader = vr.get_thread_video_reader()
    assert vr.get_thread_video_reader() is main_reader

    other: list[object] = []
    thread = threading.Thread(target=lambda: other.append(vr.get_thread_video_reader()))
    thread.start()
    thread.join()

    assert other[0] is not main_reader


def test_released_shared_reader_can_be_reopened(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    write_synthetic_mp4(clip, frame_count=4, width=32, height=24)

    reader = vr.get_video_reader(clip)
    reader.open(clip)
    assert reader.frame_count == 4
    reader.release()

    same = vr.get_video_reader(clip)
    assert same is reader
    same.open(clip)
    assert same.frame_count == 4
    assert int(same.read_frame(2)[0, 0, 0]) == 2
