"""Tests for the headless diagnostic harness, not a contract for current decoder defects."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from bench.dicom_loading_audit import audit_file, discover, fallback_counter, measure, ndarray_backing_bytes

from echo_personal_tool.infrastructure.dicom_session import DicomSession
from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom


def test_measure_returns_value_and_nonnegative_timings():
    result, timings = measure(lambda: 42)
    assert result == 42
    assert timings["wall_ms"] >= 0
    assert timings["cpu_ms"] >= 0
    assert timings["fallback_calls"] == 0


def test_backing_bytes_detects_full_cine_retained_by_one_frame():
    cine = np.zeros((24, 128, 128), dtype=np.uint8)
    frame = np.ascontiguousarray(cine[0])
    assert ndarray_backing_bytes(frame) == cine.nbytes
    assert ndarray_backing_bytes(frame.copy()) == frame.nbytes


def test_fallback_counter_restores_class_after_exception(monkeypatch):
    def fake_fallback(self, index):
        return np.zeros((2, 2), dtype=np.uint8)

    monkeypatch.setattr(DicomSession, "_decode_pydicom_fallback", fake_fallback)
    with pytest.raises(RuntimeError), fallback_counter() as counts:
        DicomSession()._decode_pydicom_fallback(0)
        raise RuntimeError("stop probe")
    assert counts["calls"] == 1
    assert DicomSession._decode_pydicom_fallback is fake_fallback


def test_discover_extensionless_dicom_and_deduplicate(tmp_path):
    cine = tmp_path / "extensionless"
    write_synthetic_multiframe_dicom(cine, frame_count=3, rows=16, cols=16)
    (tmp_path / "annotation.json").write_text("{}")
    assert list(discover([tmp_path, cine])) == [cine]


def test_audit_splits_phases_without_patient_identifiers(tmp_path: Path):
    cine = tmp_path / "private-patient-name.dcm"
    write_synthetic_multiframe_dicom(cine, frame_count=3, rows=16, cols=16)
    result = audit_file(cine, samples=2, workers=[1, 2], bulk=True, reference=True)
    assert result["frames"] == 3
    assert result["sampled_frames"] == 2
    phases = result["phases"]
    assert result["first_frame_pipeline_ms"] == round(
        sum(phases[k]["wall_ms"] for k in ("session_open", "pixel_setup", "first_frame_codec")), 3
    )
    assert all(phase["fallback_calls"] == 0 for phase in phases.values())
    assert result["j2k_cv2_candidate"] == {}
    assert "private-patient-name" not in json.dumps(result)
    assert "PatientName" not in result


def test_audit_releases_session_on_failure(tmp_path, monkeypatch):
    cine = tmp_path / "cine.dcm"
    write_synthetic_multiframe_dicom(cine, frame_count=3, rows=16, cols=16)
    released = []
    original = DicomSession.release

    def release(self):
        released.append(self)
        return original(self)

    def fail(self):
        raise RuntimeError("codec failure")

    monkeypatch.setattr(DicomSession, "release", release)
    monkeypatch.setattr(DicomSession, "decode_first_frame", fail)
    with pytest.raises(RuntimeError, match="codec failure"):
        audit_file(cine, samples=1, workers=[1], bulk=False, reference=False)
    assert released
    assert all(session._open_path is None for session in released)
