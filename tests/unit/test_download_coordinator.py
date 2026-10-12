"""DownloadCoordinator: cache lifetime and the dialog hand-off (N-08, Э9/PR-C).

The dialog routing itself is exercised through ``test_presentation_main_window``
(``TestLastSessionSource``); here the coordinator is driven against a fake
window, so the cache rules of spec §3/§5 (D-27) are tested on their own.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from echo_personal_tool.domain.models.metadata import (
    InstanceMetadata,
    SeriesMetadata,
    StudyMetadata,
)
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
from echo_personal_tool.presentation.download_coordinator import DownloadCoordinator

pytestmark = pytest.mark.gui


class _FakeTabCoordinator:
    """``_tab_coordinator`` as the window exposes it: a manager with open tabs."""

    def __init__(self, tab_cache_ids: tuple[str, ...] = ()) -> None:
        self.tabs = SimpleNamespace(
            tabs=tuple(SimpleNamespace(cache_session_id=session_id) for session_id in tab_cache_ids)
        )


class FakeWindow:
    """The ``DownloadWindow`` surface: a controller, a viewer and recorders."""

    def __init__(self) -> None:
        self._controller = SimpleNamespace(studies=[], retained_studies_for_cache=())
        self._viewer = None
        self._tab_coordinator = _FakeTabCoordinator()
        self.statuses: list[str] = []
        self.batches: list[tuple[list[StudyMetadata], str]] = []
        self.sources: list[tuple[str, str | None]] = []
        self.opened: list[tuple[Path, str, str]] = []
        self.protected: set[str] = set()

    def _show_status(self, message: str) -> None:
        self.statuses.append(message)

    def _active_orthanc_cache_sessions(self) -> set[str]:
        return set(self.protected)

    def _open_server_batch(self, studies, session_id: str) -> bool:  # noqa: ANN001
        self.batches.append((list(studies), session_id))
        return True

    def _remember_session_source(self, source: str, folder: str | None = None) -> None:
        self.sources.append((source, folder))

    def open_folder_path(self, directory: Path, *, origin: str = "folder", cache_session_id: str = "") -> None:
        self.opened.append((Path(directory), origin, cache_session_id))


@pytest.fixture()
def cache(tmp_path) -> OrthancSessionCache:
    return OrthancSessionCache(tmp_path / "cache")


def _coordinator(cache: OrthancSessionCache) -> tuple[DownloadCoordinator, FakeWindow]:
    window = FakeWindow()
    return DownloadCoordinator(window, cache=cache), window


def _touch_instance(cache: OrthancSessionCache, session_id: str, *, name: str = "instance.dcm") -> Path:
    study_dir = cache.study_path(session_id, "1.2.3")
    study_dir.mkdir(parents=True, exist_ok=True)
    path = study_dir / name
    path.write_bytes(b"DICM")
    return path


def _studies_with(path: Path) -> list[StudyMetadata]:
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.4",
        series_uid="1.2.3",
        modality="US",
        number_of_frames=2,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="A4C",
        path=path,
    )
    series = SeriesMetadata(
        series_uid="1.2.3",
        study_uid="1.2.3",
        modality="US",
        description="A4C",
        instances=(instance,),
    )
    return [StudyMetadata(study_uid="1.2.3", study_datetime=None, series=(series,))]  # type: ignore[arg-type]


def test_prepare_removes_sessions_left_by_an_earlier_run(cache: OrthancSessionCache) -> None:
    stale = cache.create_session()
    _touch_instance(cache, stale)
    old = time.time() - 30 * 86400
    os.utime(cache.session_path(stale), (old, old))
    coordinator, _ = _coordinator(cache)

    coordinator.prepare()

    assert not cache.session_path(stale).exists()


def test_a_closed_tabs_cache_is_deleted_once_nothing_uses_it(cache: OrthancSessionCache) -> None:
    coordinator, window = _coordinator(cache)
    session_id = cache.create_session()
    _touch_instance(cache, session_id)

    coordinator.queue_purge(session_id)
    window.protected = {session_id}
    coordinator.process_pending_purges()
    assert cache.session_path(session_id).exists(), "a session in use is never deleted"

    window.protected = set()
    coordinator.process_pending_purges()
    assert not cache.session_path(session_id).exists()


def test_a_failed_purge_is_not_retried_and_does_not_raise(cache: OrthancSessionCache) -> None:
    coordinator, window = _coordinator(cache)
    session_id = cache.create_session()
    _touch_instance(cache, session_id)
    calls: list[str] = []

    def boom(session: str) -> None:
        calls.append(session)
        raise OSError("device busy")

    cache.clear_session = boom  # type: ignore[method-assign]
    coordinator.queue_purge(session_id)

    coordinator.process_pending_purges()  # must not raise
    coordinator.process_pending_purges()

    assert calls == [session_id], "the entry is dropped; the exit cleanup owns the leftovers"
    assert window.statuses == []


def test_an_empty_session_id_is_never_queued(cache: OrthancSessionCache) -> None:
    coordinator, _ = _coordinator(cache)
    clear = MagicMock()
    cache.clear_session = clear  # type: ignore[method-assign]

    coordinator.queue_purge("")
    coordinator.process_pending_purges()

    assert not clear.called


def test_active_sessions_cover_the_viewer_and_every_open_tab(cache: OrthancSessionCache) -> None:
    coordinator, window = _coordinator(cache)
    viewer_session = cache.create_session()
    tab_session = cache.create_session()
    other = cache.create_session()
    window._controller.studies = _studies_with(_touch_instance(cache, viewer_session))
    window._tab_coordinator = _FakeTabCoordinator((tab_session,))

    active = coordinator.active_cache_sessions()

    assert active == {viewer_session, tab_session}
    assert other not in active


def test_a_study_retained_for_the_cache_is_protected_too(cache: OrthancSessionCache) -> None:
    coordinator, window = _coordinator(cache)
    retained = cache.create_session()
    window._controller.retained_studies_for_cache = _studies_with(_touch_instance(cache, retained))

    assert retained in coordinator.active_cache_sessions()


def test_clear_all_wipes_every_session(cache: OrthancSessionCache) -> None:
    coordinator, _ = _coordinator(cache)
    first = cache.create_session()
    second = cache.create_session()
    _touch_instance(cache, first)
    _touch_instance(cache, second)

    coordinator.clear_all()

    assert not cache.session_path(first).exists()
    assert not cache.session_path(second).exists()


def test_send_to_server_without_studies_explains_instead_of_uploading(cache: OrthancSessionCache) -> None:
    coordinator, window = _coordinator(cache)
    information = MagicMock()
    with (
        patch("PySide6.QtWidgets.QMessageBox.information", information),
        patch("echo_personal_tool.presentation.dicom_upload_dialog.run_dicom_upload_dialog") as upload,
    ):
        coordinator.send_to_server()

    assert information.called
    assert not upload.called


def test_send_to_server_uploads_with_the_viewer_annotations(cache: OrthancSessionCache) -> None:
    coordinator, window = _coordinator(cache)
    shape = SimpleNamespace(sop_instance_uid="1.2.3.4")
    window._controller.studies = _studies_with(Path("/tmp/1.2.3.dcm"))
    window._viewer = SimpleNamespace(
        contours=lambda: [shape],
        _stored_linear_measurements={"a": shape},
    )
    with patch("echo_personal_tool.presentation.dicom_upload_dialog.run_dicom_upload_dialog") as upload:
        coordinator.send_to_server()

    assert upload.called
    annotations = upload.call_args.kwargs["annotations"]
    assert annotations == {"1.2.3.4": [shape, shape]}
