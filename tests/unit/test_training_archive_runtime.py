"""Archive lifecycle through the real composition, controller and viewer signals."""

from dataclasses import replace

import numpy as np
import pydicom
import pytest
from PySide6.QtCore import QThreadPool

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.composition import in_memory_app_services
from echo_personal_tool.application.training_archive import MeasurementArchiveCapture
from echo_personal_tool.application.training_archive_runtime import confirm_archive
from echo_personal_tool.domain.models import Contour, InstanceMetadata
from echo_personal_tool.infrastructure.training_archive import SqliteMeasurementArchive
from echo_personal_tool.presentation.main_window import MainWindow
from echo_personal_tool.presentation.viewer_widget import ViewerWidget
from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

pytestmark = pytest.mark.gui


@pytest.fixture
def live_archive(tmp_path, qtbot):
    path = write_synthetic_multiframe_dicom(tmp_path / "source.dcm", frame_count=3, moving=True)
    ds = pydicom.dcmread(path)
    archive = SqliteMeasurementArchive(tmp_path / "archive" / "measurement-training.sqlite3")
    skipped = []
    services = replace(
        in_memory_app_services(), training_archive=MeasurementArchiveCapture(archive, lambda: skipped.append(True))
    )
    pool = QThreadPool()
    controller = AppController(services, thread_pool=pool)
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    frames = []
    controller.frame_loaded.connect(lambda pixels: frames.append(pixels.copy()))
    instance = InstanceMetadata(
        str(ds.SOPInstanceUID), str(ds.SeriesInstanceUID), "US", 3, (0.5, 0.4), 40.0, "Test", path=path
    )
    controller.load_instance(instance)
    qtbot.waitUntil(lambda: len(frames) > 0 and not controller.state_manager.snapshot.decode_in_progress, timeout=10000)
    yield archive, controller, window.findChild(ViewerWidget), ds.pixel_array, skipped
    controller.state_manager.set_playing(False)
    pool.waitForDone(10000)
    controller.measurement_persistence.close()
    assert not skipped


def test_real_controller_navigation_archives_old_decoded_frame_once(live_archive):
    archive, controller, _, pixels, _ = live_archive
    contour = Contour(
        "ED",
        points=[(10.0, 45.0), (30.0, 10.0), (50.0, 45.0)],
        mitral_annulus=((10.0, 45.0), (50.0, 45.0)),
        apex_landmark=(30.0, 10.0),
        frame_index=0,
    )
    controller.on_contours_changed([contour])
    assert archive.records() == []
    controller.step_frame(1)
    [record] = archive.records()
    assert record["frame_index"] == 0
    np.testing.assert_array_equal(archive.frame(record["frame_hash"]), pixels[0])
    controller.step_frame(1)
    assert len(archive.records()) == 1 and archive.records()[0]["revision"] == 1


def test_real_viewer_finish_cancel_delete_and_undo(live_archive):
    archive, controller, viewer, pixels, _ = live_archive
    assert viewer.start_atrial_area_length_contour(chamber="RA", phase="ES")
    assert viewer.handle_contour_click((10.0, 45.0))
    viewer.cancel_active_tool()
    assert archive.records() == []
    assert viewer.start_atrial_area_length_contour(chamber="RA", phase="ES")
    for point in [(10.0, 45.0), (12.0, 20.0), (40.0, 10.0), (50.0, 45.0)]:
        assert viewer.handle_contour_click(point)
    assert archive.records() == []
    assert viewer.finish_contour()
    [record] = archive.records()
    assert record["chamber"] == "RA" and record["phase_semantics"] == "atrial_maximum"
    assert record["points"] == [list(p) for p in viewer.contours()[0].points]
    np.testing.assert_array_equal(archive.frame(record["frame_hash"]), pixels[0])
    confirm_archive(controller)
    assert archive.records()[0]["revision"] == 1
    assert viewer.delete_contour_for_current_phase()
    assert archive.records() == []
    assert viewer.undo()
    confirm_archive(controller)
    assert archive.records()[0]["revision"] == 3


def test_real_ai_acceptance_retains_automatic_origin(live_archive):
    archive, controller, _, _, _ = live_archive
    contour = Contour(
        "ES", source="ai", review_pending=True, points=[(10.0, 45.0), (30.0, 10.0), (50.0, 45.0)], frame_index=0
    )
    controller.on_contours_changed([contour])
    confirm_archive(controller)
    assert archive.records() == []
    assert controller.accept_ai_contour_review("A4C", "ES")
    [record] = archive.records()
    assert record["origin"] == "AUTO_ACCEPTED" and record["source"] == "ai"
    assert controller.state_manager.snapshot.contours[0].review_pending is False


def test_study_reset_excludes_archive_and_drops_staged_edits(live_archive):
    archive, controller, _, _, _ = live_archive
    contour = Contour("ES", points=[(10.0, 45.0), (30.0, 10.0), (50.0, 45.0)], frame_index=0)
    controller.on_contours_changed([contour])
    confirm_archive(controller)
    assert len(archive.records()) == 1
    controller.on_contours_changed([Contour("ED", points=contour.points, frame_index=0)])
    controller.reset_measurements_and_calibration()
    confirm_archive(controller)
    assert archive.records() == []
    assert all(r["excluded"] for r in archive.records(include_excluded=True))


def test_disabled_archive_completion_adds_no_clinical_recomputation(qapp, monkeypatch):
    from echo_personal_tool.application.training_archive_runtime import complete_archive

    services = in_memory_app_services()
    controller = AppController(services)
    calls = []
    monkeypatch.setattr(controller, "on_contours_changed", lambda contours: calls.append(contours))
    complete_archive(controller, [Contour("ED")])
    assert services.training_archive is None and calls == []
    assert controller.measurement_persistence.close()
