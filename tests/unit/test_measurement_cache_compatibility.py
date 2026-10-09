"""WP4 integration must preserve cache lifecycle and the pre-scanned PACS fast path."""

from __future__ import annotations

from types import SimpleNamespace

import pydicom
import pytest

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.measurement_persistence import MeasurementPersistence
from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO, DopplerPeakMarker
from echo_personal_tool.infrastructure.local_scanner import LocalMediaDirectoryScanner
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.main_window import MainWindow
from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

pytestmark = pytest.mark.gui


def _download(cache, tmp_path, study_uid, *, payload=None):
    """Synthetic download with real cache layout and headers, no PACS network."""
    source = tmp_path / "source.dcm"
    series_uid = study_uid + ".1"
    if payload is None:
        write_synthetic_dicom(source, study_uid=study_uid, series_uid=series_uid)
    else:
        source.write_bytes(payload)
    ds = pydicom.dcmread(source, stop_before_pixels=True)
    session = cache.create_session()
    path = cache.save_instance(session, study_uid, series_uid, str(ds.SOPInstanceUID), source.read_bytes())
    studies = LocalMediaDirectoryScanner().scan(cache.session_path(session))
    return session, path, studies


def _controller(monkeypatch, enabled):
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.load_user_preferences",
        lambda: UserPreferences(measurement_persistence_enabled=enabled),
    )
    return AppController(thread_pool=SimpleNamespace(start=lambda *args: None))


def test_cache_clear_during_restore_preserves_previous_visible_study(tmp_path, monkeypatch, qapp):
    cache = OrthancSessionCache(tmp_path / "cache" / "orthanc")
    old_id, old_path, old = _download(cache, tmp_path, "1.2.3")
    new_id, new_path, new = _download(cache, tmp_path, "1.2.4")
    unused, unused_path, _ = _download(cache, tmp_path, "1.2.5")
    controller = _controller(monkeypatch, True)
    try:
        controller.load_pre_scanned_studies(old)
        assert controller.measurement_persistence.flush()
        controller.load_instance(old[0].series[0].instances[0])
        # Pause restore deterministically. A Settings cache clear may happen here.
        monkeypatch.setattr(controller.measurement_persistence, "load", lambda *args: None)
        controller.load_pre_scanned_studies(new)
        window = SimpleNamespace(_controller=controller, _orthanc_cache=cache, _tabs=SimpleNamespace(tabs=()))
        protected = MainWindow._active_orthanc_cache_sessions(window)
        cache.clear_all(preserve_session_ids=protected)
        assert old_path.exists(), "the old source is still shown/read while restore is pending"
        assert new_path.exists(), "the incoming source must also remain available to restore"
        assert not unused_path.exists()
        assert protected == {old_id, new_id}
    finally:
        controller.measurement_persistence.close()


def test_new_study_does_not_flush_previous_viewer_annotations_under_series_uid(tmp_path, monkeypatch, qapp):
    cache = OrthancSessionCache(tmp_path / "cache" / "orthanc")
    _, _, old = _download(cache, tmp_path, "1.2.3")
    _, _, new = _download(cache, tmp_path, "1.2.4")
    controller = _controller(monkeypatch, True)
    try:
        controller.load_pre_scanned_studies(old)
        assert controller.measurement_persistence.flush()
        controller.load_instance(old[0].series[0].instances[0])
        dto = DopplerMeasurementDTO((DopplerPeakMarker("E", 0.0, 80.0),), (), ())
        controller.on_doppler_markers_changed(dto)
        assert controller.measurement_persistence.flush()

        def select_first(studies):
            # MainWindow._on_instance_selected saves the outgoing viewer's DTO first.
            previous = controller.state_manager.snapshot.instance
            if previous is not None:
                controller.save_doppler_for_frame(previous.sop_instance_uid, 0, dto)
            controller.load_instance(studies[0].series[0].instances[0])

        controller.studies_loaded.connect(select_first)
        controller.load_pre_scanned_studies(new)
        assert controller.measurement_persistence.flush(), "no orphan write under the previous Series UID"
        assert controller._measurement_session.get(new[0].study_uid).all_doppler_dto is None
        assert controller.measurement_persistence.repository.load(old[0].study_uid)["data"].all_doppler_dto == dto
    finally:
        controller.measurement_persistence.discard_pending()
        controller.measurement_persistence.close()


def test_disabled_persistence_does_not_copy_entire_study_on_each_edit(tmp_path, monkeypatch, qapp):
    store = StudyMeasurementSessionStore()
    persistence = MeasurementPersistence(tmp_path / "measurements", store, enabled=False)
    try:

        def unexpected_copy(_):
            pytest.fail("disabled persistence must not deep-copy every completed edit")

        monkeypatch.setattr("echo_personal_tool.application.study_measurement_session.deepcopy", unexpected_copy)
        store.set_patient_metrics("1.2.3", 170.0, 70.0)
        assert not persistence.repository.root.exists()
    finally:
        persistence.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_pre_scanned_pacs_skips_scanworker_and_disabled_skips_fingerprints(tmp_path, monkeypatch, qapp, enabled):
    cache = OrthancSessionCache(tmp_path / "cache" / "orthanc")
    _, path, studies = _download(cache, tmp_path, "1.2.3")
    original_bytes = path.read_bytes()
    original_mtime = path.stat().st_mtime_ns
    controller = _controller(monkeypatch, enabled)
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.ScanWorker",
        lambda *a, **k: pytest.fail("PACS must keep the pre-scanned fast path"),
    )
    if not enabled:
        monkeypatch.setattr(
            "echo_personal_tool.application.measurement_persistence.describe_study",
            lambda *a: pytest.fail("disabled persistence must not read source headers again"),
        )
    try:
        loaded = []
        controller.studies_loaded.connect(loaded.append)
        controller.load_pre_scanned_studies(studies)
        assert controller.measurement_persistence.flush()
        assert loaded == [studies]
        assert path.read_bytes() == original_bytes
        assert path.stat().st_mtime_ns == original_mtime
    finally:
        controller.measurement_persistence.close()


def test_cache_and_measurement_delete_are_isolated(tmp_path, monkeypatch, qapp):
    app_data = tmp_path / "app-data"
    monkeypatch.setattr("echo_personal_tool.infrastructure.paths.measurements_dir", lambda: app_data / "measurements")
    cache = OrthancSessionCache(app_data / "cache" / "orthanc")
    _, path, studies = _download(cache, tmp_path, "1.2.3")
    controller = _controller(monkeypatch, True)
    try:
        controller.load_pre_scanned_studies(studies)
        assert controller.measurement_persistence.flush()
        controller.load_instance(studies[0].series[0].instances[0])
        controller.on_patient_metrics_changed(170.0, 70.0)
        dto = DopplerMeasurementDTO((DopplerPeakMarker("E", 0.0, 80.0),), (), ())
        controller.on_doppler_markers_changed(dto)
        assert controller.measurement_persistence.flush()
        payload = path.read_bytes()
        cache.clear_all()
        assert not path.exists()
        assert controller.measurement_persistence.repository.load("1.2.3")["data"].height_cm == 170.0

        _, restored_path, redownloaded = _download(cache, tmp_path, "1.2.3", payload=payload)
        # Repeated retrieval with different temporary paths must not touch saved metrics.
        controller.load_pre_scanned_studies(redownloaded)
        assert controller.measurement_persistence.flush()
        assert controller._measurement_session.get("1.2.3").height_cm == 170.0
        assert controller._measurement_session.get("1.2.3").all_doppler_dto == dto
        controller.measurement_persistence.delete_all(lambda error: None)
        assert controller.measurement_persistence.flush()
        assert restored_path.exists()
    finally:
        controller.measurement_persistence.close()


def test_empty_restore_finishes_loading_and_reenables_ui(tmp_path, qapp):
    persistence = MeasurementPersistence(tmp_path / "measurements", StudyMeasurementSessionStore(), enabled=True)
    states = []
    persistence.status.connect(states.append)
    try:
        persistence.load([], lambda: None)
        assert persistence.flush()
        assert states == ["loading", "ready"]
    finally:
        persistence.close()


def test_clip_calibration_projection_does_not_deepcopy_study(monkeypatch):
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
    from echo_personal_tool.domain.models import Contour

    store = StudyMeasurementSessionStore()
    store.restore(
        "1.2.3",
        StudyMeasurementData(
            contours=(Contour("ED", points=[(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]),),
            manual_spacing_by_instance=(("1.2.3.1", (0.5, 0.5)),),
        ),
    )
    original_contours = store.get("1.2.3").contours
    monkeypatch.setattr(
        "echo_personal_tool.application.study_measurement_session.deepcopy",
        lambda _: pytest.fail("clip selection must not copy the whole accumulated study"),
    )
    store.on_change = lambda *args: pytest.fail("clip selection must not trigger autosave")
    store.activate_instance("1.2.3", "1.2.3.1")
    assert store.get("1.2.3").contours is original_contours
    assert store.get("1.2.3").manual_pixel_spacing == (0.5, 0.5)


def test_old_cache_protection_released_after_selection_not_before(tmp_path, monkeypatch, qapp):
    cache = OrthancSessionCache(tmp_path / "cache" / "orthanc")
    old_id, _, old = _download(cache, tmp_path, "1.2.3")
    new_id, _, new = _download(cache, tmp_path, "1.2.4")
    controller = _controller(monkeypatch, True)
    try:
        controller.load_pre_scanned_studies(old)
        assert controller.measurement_persistence.flush()
        controller.load_instance(old[0].series[0].instances[0])
        window = SimpleNamespace(_controller=controller, _orthanc_cache=cache, _tabs=SimpleNamespace(tabs=()))
        during_publish = []
        controller.studies_loaded.connect(
            lambda _: during_publish.append(MainWindow._active_orthanc_cache_sessions(window))
        )
        controller.load_pre_scanned_studies(new)
        assert controller.measurement_persistence.flush()
        assert during_publish == [{old_id, new_id}]
        assert MainWindow._active_orthanc_cache_sessions(window) == {new_id}
    finally:
        controller.measurement_persistence.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_empty_study_set_clears_previous_identity(tmp_path, monkeypatch, qapp, enabled):
    cache = OrthancSessionCache(tmp_path / "cache" / "orthanc")
    _, _, studies = _download(cache, tmp_path, "1.2.3")
    controller = _controller(monkeypatch, enabled)
    try:
        assert controller.retained_studies_for_cache == ()
        controller.load_pre_scanned_studies(studies)
        assert controller.measurement_persistence.flush()
        controller.load_instance(studies[0].series[0].instances[0])
        controller.load_pre_scanned_studies([])
        assert controller.measurement_persistence.flush()
        assert controller.state_manager.snapshot.instance is None
        assert controller._current_instance is None
        assert controller.retained_studies_for_cache == ()
    finally:
        controller.measurement_persistence.close()


def test_failed_scan_keeps_previous_identity_and_cache_protection(tmp_path, monkeypatch, qapp):
    cache = OrthancSessionCache(tmp_path / "cache" / "orthanc")
    session_id, path, studies = _download(cache, tmp_path, "1.2.3")
    controller = _controller(monkeypatch, True)
    try:
        controller.load_pre_scanned_studies(studies)
        assert controller.measurement_persistence.flush()
        instance = studies[0].series[0].instances[0]
        controller.load_instance(instance)
        controller.open_folder(tmp_path / "missing")
        assert controller.retained_studies_for_cache == tuple(studies)
        # The fake decode/scan pool deliberately does not execute jobs.
        controller._on_scan_failed("synthetic scan failure")
        assert controller.retained_studies_for_cache == ()
        assert controller.state_manager.snapshot.instance is instance
        assert controller._current_instance is instance
        window = SimpleNamespace(_controller=controller, _orthanc_cache=cache, _tabs=SimpleNamespace(tabs=()))
        protected = MainWindow._active_orthanc_cache_sessions(window)
        assert protected == {session_id}
        cache.clear_all(preserve_session_ids=protected)
        assert path.exists()
    finally:
        controller.measurement_persistence.close()
