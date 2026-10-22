"""Fake DICOMweb client backed by JSON fixtures for offline dev."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from echo_personal_tool.domain.models.orthanc import (
    InstanceInfo,
    SeriesInfo,
    StowResult,
    StudyInfo,
    StudyStatistics,
)
from echo_personal_tool.infrastructure.orthanc_dicom_json import (
    parse_instances,
    parse_series,
    parse_studies,
)


class FakeDicomWebClient:
    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self._fixtures = fixtures_dir or Path(__file__).resolve().parents[3] / "tests/fixtures/orthanc"
        self._studies_payload: list[dict] | None = None
        self._series_payload: list[dict] | None = None
        self._instances_payload: list[dict] | None = None
        self._sample_dcm: bytes | None = None

    def _load_studies(self) -> list[dict]:
        if self._studies_payload is None:
            self._studies_payload = json.loads((self._fixtures / "studies.json").read_text(encoding="utf-8"))
        return self._studies_payload

    def _load_series(self) -> list[dict]:
        if self._series_payload is None:
            self._series_payload = json.loads((self._fixtures / "series.json").read_text(encoding="utf-8"))
        return self._series_payload

    def _load_instances(self) -> list[dict]:
        if self._instances_payload is None:
            self._instances_payload = json.loads((self._fixtures / "instances.json").read_text(encoding="utf-8"))
        return self._instances_payload

    def _load_sample_dcm(self) -> bytes:
        if self._sample_dcm is None:
            self._sample_dcm = (self._fixtures / "sample.dcm").read_bytes()
        return self._sample_dcm

    def ping(self) -> bool:
        return True

    def query_studies(
        self,
        *,
        patient_name: str | None = None,
        patient_id: str | None = None,
        study_date: str | None = None,
    ) -> list[StudyInfo]:
        studies = parse_studies(self._load_studies())
        if patient_name is not None:
            needle = patient_name.casefold()
            studies = [s for s in studies if needle in s.patient_name.casefold()]
        if patient_id is not None:
            studies = [s for s in studies if patient_id in s.patient_id]
        if study_date is not None:
            studies = [s for s in studies if study_date in s.study_date]
        return studies

    def query_series(self, study_uid: str) -> list[SeriesInfo]:
        return parse_series(self._load_series(), study_uid)

    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
        return parse_instances(self._load_instances(), study_uid, series_uid)

    def download_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        return self._load_sample_dcm()

    def stow_instances(self, dicom_files: list[bytes]) -> StowResult:
        return StowResult(success_count=len(dicom_files))

    def fetch_preview(
        self,
        study_uid: str,
        series_uid: str,
        instance_uid: str = "",
        *,
        width: int = 0,
        height: int = 0,
        middle_frame: bool = False,
    ) -> bytes:
        """Synthetic rendering so the mock demos thumbnails offline.

        The payload is a real PNG built from the series UID, so the loader
        exercises the same decode path as with a live server.  Fixtures have no
        cine loops, so ``middle_frame`` returns the same frame.
        """
        return _synthetic_preview_png(series_uid or study_uid, width=width, height=height)

    def study_statistics(self, study_uid: str) -> StudyStatistics:
        """Mock mode has no statistics endpoint."""
        return StudyStatistics()

    def close(self) -> None:
        """No-op: the fake holds no sockets, but satisfies the client surface."""

    def cancel_inflight(self) -> None:
        """No-op cancel hook used by the download worker."""


def _synthetic_preview_png(seed: str, *, width: int = 160, height: int = 120) -> bytes:
    """Build a small greyscale PNG resembling a rendered ultrasound frame.

    Deliberately dependency-free (``zlib`` + ``struct`` only): the mock client
    must keep working in minimal installations used for UI development.
    """
    w = max(32, min(int(width) or 160, 512))
    h = max(24, min(int(height) or 120, 512))
    digest = zlib.crc32(seed.encode("utf-8")) if seed else 0
    fan = 40 + (digest % 30)  # half-angle of the sector in "degrees"
    phase = (digest >> 8) % 100
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # PNG filter type 0 (None)
        ny = (y / max(1, h - 1)) * 2.0 - 1.0
        for x in range(w):
            nx = (x / max(1, w - 1)) * 2.0 - 1.0
            radius = (nx * nx * 0.35 + ny * ny) ** 0.5
            inside = abs(nx) < (fan / 90.0) * (ny * 0.5 + 1.0) and ny > -0.9
            speckle = ((x * 37 + y * 17 + phase) * 2654435761) % 251
            value = 8 + speckle * 0.12
            if inside:
                value += 70 - radius * 55
                if abs(ny - 0.15) < 0.02:
                    value += 60
            rows.append(max(0, min(255, int(value))))
    return _png_from_gray(bytes(rows), w, h)


def _png_from_gray(raw_rows: bytes, width: int, height: int) -> bytes:
    """Wrap filtered greyscale rows into a PNG container."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw_rows, 6)) + chunk(b"IEND", b"")
    )
