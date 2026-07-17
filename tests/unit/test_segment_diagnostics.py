"""Tests for cine_segment_diagnostics (DICOM media_format path)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.cine_segment_diagnostics import (
    CineSegmentDiagnosticReport,
    diagnose_cine_frame,
)


class TestDiagnoseCineFrame:
    def test_returns_report(self) -> None:
        frame = np.zeros((100, 100), dtype=np.uint8)
        frame[30:70, 20:80] = 150
        report = diagnose_cine_frame(frame, media_format="dicom", run_onnx=False)
        assert isinstance(report, CineSegmentDiagnosticReport)
        assert report.media_format == "dicom"
        assert report.frame_shape == (100, 100)

    def test_default_media_format(self) -> None:
        frame = np.zeros((100, 100), dtype=np.uint8)
        report = diagnose_cine_frame(frame, run_onnx=False)
        assert report.media_format == "mp4"
