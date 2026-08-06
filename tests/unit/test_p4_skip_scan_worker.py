"""Tests for P4: skip ScanWorker after Orthanc download.

The OrthancDownloadWorker should parse DICOM headers from saved files
and emit a studies_ready signal with StudyMetadata, so the main window
can skip the redundant ScanWorker pass.
"""

from __future__ import annotations

import io
from pathlib import Path

from pydicom.dataset import Dataset

from echo_personal_tool.application.workers.orthanc_download_worker import (
    OrthancDownloadWorker,
)
from echo_personal_tool.domain.models import StudyMetadata
from echo_personal_tool.domain.models.orthanc import InstanceInfo
from echo_personal_tool.infrastructure.fake_dicom_web_client import FakeDicomWebClient
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache

FIXTURES = Path("tests/fixtures/orthanc")
STUDY_UID = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.1"
SERIES_UID = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.2"
INSTANCE_UID = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.3"


def _make_dicom_bytes(
    study_uid: str,
    series_uid: str,
    sop_uid: str,
    *,
    modality: str = "US",
    num_frames: int = 1,
    series_desc: str = "Test Series",
) -> bytes:
    """Create a minimal DICOM file with proper UIDs."""
    ds = Dataset()
    ds.file_meta = Dataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    ds.file_meta.MediaStorageSOPInstanceUID = sop_uid
    ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2.1"
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = modality
    ds.NumberOfFrames = str(num_frames)
    ds.SeriesDescription = series_desc
    ds.StudyDate = "20240404"
    ds.StudyTime = "112054"
    ds.PatientName = "Test^Patient"
    ds.is_implicit_VR = False
    ds.is_little_endian = True

    buf = io.BytesIO()
    ds.save_as(buf, write_like_original=False)
    return buf.getvalue()


class _DicomBackedClient(FakeDicomWebClient):
    """Fake client that returns properly-tagged DICOM bytes."""

    def download_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        return _make_dicom_bytes(study_uid, series_uid, instance_uid)


class _SignalCapture:
    def __init__(self) -> None:
        self.progress: list[tuple[int, int, str]] = []
        self.done: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []
        self.cancelled: list[str] = []
        self.studies_ready: list[list[StudyMetadata]] = []

    def connect(self, worker: OrthancDownloadWorker) -> None:
        worker.signals.progress.connect(
            lambda current, total, series_uid: self.progress.append((current, total, series_uid))
        )
        worker.signals.done.connect(lambda session_id, study_uid: self.done.append((session_id, study_uid)))
        worker.signals.failed.connect(lambda uid, message: self.failed.append((uid, message)))
        worker.signals.cancelled.connect(lambda session_id: self.cancelled.append(session_id))
        worker.signals.studies_ready.connect(lambda studies: self.studies_ready.append(studies))


def test_worker_emits_studies_ready_after_download(tmp_path: Path) -> None:
    client = _DicomBackedClient(FIXTURES)
    cache = OrthancSessionCache(tmp_path)
    session_id = cache.create_session()
    capture = _SignalCapture()

    worker = OrthancDownloadWorker(client, cache, session_id, STUDY_UID, [SERIES_UID])
    capture.connect(worker)
    worker.run()

    assert len(capture.done) == 1
    assert len(capture.studies_ready) == 1

    studies = capture.studies_ready[0]
    assert len(studies) == 1

    study = studies[0]
    assert isinstance(study, StudyMetadata)
    assert study.study_uid == STUDY_UID
    assert len(study.series) >= 1

    series = study.series[0]
    assert series.series_uid == SERIES_UID
    assert len(series.instances) >= 1
    assert series.instances[0].sop_instance_uid == INSTANCE_UID
    assert series.instances[0].modality == "US"


def test_worker_emits_studies_ready_even_when_no_instances(tmp_path: Path) -> None:
    """Empty series still emits studies_ready (empty list)."""

    class _EmptyClient(FakeDicomWebClient):
        def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
            return []

    client = _EmptyClient(FIXTURES)
    cache = OrthancSessionCache(tmp_path)
    session_id = cache.create_session()
    capture = _SignalCapture()

    worker = OrthancDownloadWorker(client, cache, session_id, STUDY_UID, [SERIES_UID])
    capture.connect(worker)
    worker.run()

    assert len(capture.done) == 1
    assert len(capture.studies_ready) == 1
    assert isinstance(capture.studies_ready[0], list)


def test_metadata_groups_instances_by_series(tmp_path: Path) -> None:
    """Instances from different series are grouped correctly."""
    SERIES2 = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.99"

    class _MultiSeriesClient(FakeDicomWebClient):
        def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
            if series_uid == SERIES_UID:
                return [InstanceInfo(INSTANCE_UID, SERIES_UID, study_uid)]
            if series_uid == SERIES2:
                return [
                    InstanceInfo(
                        "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.99",
                        SERIES2,
                        study_uid,
                    )
                ]
            return []

        def download_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
            return _make_dicom_bytes(
                study_uid,
                series_uid,
                instance_uid,
                series_desc=f"Series {series_uid[-4:]}",
            )

    client = _MultiSeriesClient(FIXTURES)
    cache = OrthancSessionCache(tmp_path)
    session_id = cache.create_session()
    capture = _SignalCapture()

    worker = OrthancDownloadWorker(client, cache, session_id, STUDY_UID, [SERIES_UID, SERIES2])
    capture.connect(worker)
    worker.run()

    assert len(capture.studies_ready) == 1
    study = capture.studies_ready[0][0]
    assert len(study.series) == 2
    series_uids = {s.series_uid for s in study.series}
    assert SERIES_UID in series_uids
    assert SERIES2 in series_uids
