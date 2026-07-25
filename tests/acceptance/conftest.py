"""Shared fixtures for acceptance tests: QApplication, fake clients, synthetic DICOM, mock workers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"

# ── QApplication (session-scoped, created once) ─────────────────────


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app  # type: ignore[return-value]


# ── Synthetic DICOM paths ──────────────────────────────────────────


@pytest.fixture
def synthetic_dicom_path(tmp_path: Path) -> Path:
    """Generate a single-frame synthetic DICOM and return its path."""
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

    return write_synthetic_dicom(tmp_path / "echo" / "study" / "img.dcm")


@pytest.fixture
def synthetic_dicom_dir(tmp_path: Path) -> Path:
    """Generate a directory tree with two synthetic DICOMs (two series)."""
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

    study_dir = tmp_path / "echo" / "study"
    write_synthetic_dicom(study_dir / "series_a" / "frame_001.dcm", series_description="A4C")
    write_synthetic_dicom(study_dir / "series_b" / "frame_001.dcm", series_description="A2C")
    return study_dir


@pytest.fixture
def synthetic_multiframe_path(tmp_path: Path) -> Path:
    """Generate a 10-frame multiframe DICOM for cine testing."""
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

    return write_synthetic_multiframe_dicom(tmp_path / "cine" / "cine.dcm", frame_count=10)


# ── Mock Orthanc / DICOMweb client ────────────────────────────────


@pytest.fixture
def fake_orthanc_client():
    """FakeDicomWebClient instance backed by JSON fixtures."""
    from echo_personal_tool.infrastructure.fake_dicom_web_client import FakeDicomWebClient

    return FakeDicomWebClient(fixtures_dir=FIXTURES / "orthanc")


@pytest.fixture
def mock_dicom_web_client():
    """Fully mocked DicomWebClient with controllable return values."""
    client = MagicMock()
    client.ping.return_value = True
    client.query_studies.return_value = []
    client.query_series.return_value = []
    client.query_instances.return_value = []
    client.download_instance.return_value = b"\x00" * 1024
    client.stow_instances.return_value = MagicMock(success_count=0, failed_uids=[], error_message="")
    return client


# ── Mock ONNX worker ──────────────────────────────────────────────


@pytest.fixture
def mock_onnx_worker():
    """Mock ONNX worker that returns a synthetic LV segmentation mask."""
    mask = np.zeros((64, 64), dtype=np.uint8)
    # Draw a filled circle as a fake LV cavity
    yy, xx = np.ogrid[:64, :64]
    center_y, center_x = 32, 32
    radius = 15
    mask[(yy - center_y) ** 2 + (xx - center_x) ** 2 <= radius**2] = 1

    worker = MagicMock()
    worker.segment.return_value = mask
    worker.is_available.return_value = True
    return worker


@pytest.fixture
def mock_onnx_segmenter():
    """Mock IOnnxSegmenter protocol implementation."""
    mask = np.zeros((64, 64), dtype=np.uint8)
    yy, xx = np.ogrid[:64, :64]
    mask[(yy - 32) ** 2 + (xx - 32) ** 2 <= 15**2] = 1

    seg = MagicMock()
    seg.segment.return_value = mask
    seg.is_available.return_value = True
    return seg


# ── Mock speckle tracking worker ──────────────────────────────────


@pytest.fixture
def mock_speckle_worker():
    """Mock speckle tracking worker that returns synthetic tracking results."""
    from echo_personal_tool.domain.models.speckle import (
        StrainResult,
        TrackingResult,
    )

    n_kernels = 16
    n_frames = 10
    displacements = np.random.randn(n_frames, n_kernels, 2).astype(np.float32) * 0.5
    ncc_scores = np.ones((n_frames, n_kernels), dtype=np.float32) * 0.85
    valid_mask = np.ones((n_frames, n_kernels), dtype=bool)
    kernel_positions = np.column_stack([
        np.linspace(20, 60, n_kernels),
        np.full(n_kernels, 32.0),
    ]).astype(np.float32)

    tracking = TrackingResult(
        frame_index=0,
        displacements=displacements,
        ncc_scores=ncc_scores,
        valid_mask=valid_mask,
        kernel_positions=kernel_positions,
    )

    longitudinal = np.linspace(0, -20, n_frames, dtype=np.float32)
    radial = np.linspace(0, 15, n_frames, dtype=np.float32)

    strain = StrainResult(
        longitudinal=longitudinal,
        radial=radial,
        gls=-18.5,
        ed_index=0,
        es_index=n_frames - 1,
    )

    worker = MagicMock()
    worker.track.return_value = tracking
    worker.compute_strain.return_value = strain
    worker.is_available.return_value = True
    return worker


# ── Mock PDF exporter ─────────────────────────────────────────────


@pytest.fixture
def mock_pdf_export(tmp_path: Path):
    """Mock PDF export that captures the call and writes a placeholder file."""
    output = tmp_path / "report.pdf"

    def _export(text: str, path: Path, *, font_size: int = 10) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 fake")
        return path

    return _export


# ── Patched MainWindow factory ─────────────────────────────────────


@pytest.fixture
def make_main_window(qapp):
    """Factory that creates a MainWindow with mocked internals, ready for testing."""

    def _factory(**overrides):
        from echo_personal_tool.application.app_controller import AppController
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences
        from echo_personal_tool.presentation.main_window import MainWindow

        prefs = UserPreferences(layout_state_json="")
        controller = AppController()
        window = MainWindow(controller=controller, user_preferences=prefs)
        window.resize(1280, 800)
        return window

    return _factory
