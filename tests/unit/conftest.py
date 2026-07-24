"""Shared fixtures for GUI (PySide6) unit tests.

Provides:
- Session-scoped QApplication with offscreen rendering
- Fake signal/mock classes for AppController and workers
- Common domain model factories
- QSettings isolation
- Proper widget cleanup via qtbot

Usage in test files:
    pytestmark = pytest.mark.gui
    pytest.importorskip("pytestqt")

    def test_something(qapp, qtbot):
        ...
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

# ── Offscreen rendering for headless CI ───────────────────────────
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.gui


# ═══════════════════════════════════════════════════════════════════
#  QApplication (session-scoped — only one per process)
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def qapp_session():
    """Session-scoped QApplication. Safe to use across all GUI tests."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture()
def qapp(qapp_session):
    """Alias for qapp_session — most tests use this name."""
    return qapp_session


# ═══════════════════════════════════════════════════════════════════
#  Fake / Mock helpers
# ═══════════════════════════════════════════════════════════════════


class FakeSignal:
    """Minimal signal stand-in with connect/emit. Stores callbacks."""

    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback, *args, **kwargs) -> None:
        self._callbacks.append(callback)

    def disconnect(self, callback=None) -> None:
        if callback is not None:
            self._callbacks = [c for c in self._callbacks if c is not callback]
        else:
            self._callbacks.clear()

    def emit(self, *args) -> None:
        for cb in list(self._callbacks):
            cb(*args)

    @property
    def signal_count(self) -> int:
        return len(self._callbacks)


class RecordingThreadPool:
    """Records start() calls without running workers."""

    def __init__(self) -> None:
        self.started: list[Any] = []

    def start(self, worker) -> None:
        self.started.append(worker)

    def waitForDone(self, *args, **kwargs) -> None:
        pass


class FakeDecodeWorker:
    """Mimics DicomDecodeWorker/VideoDecodeWorker shape."""

    def __init__(self, path=None, request_id=0, parent=None, first_frame_only=False, **kw) -> None:
        self.path = Path(path) if path else Path("/dev/null")
        self.request_id = request_id
        self.parent = parent
        self.first_frame_only = first_frame_only
        self.signals = SimpleNamespace(
            first_frame_ready=FakeSignal(),
            progress=FakeSignal(),
            finished=FakeSignal(),
            failed=FakeSignal(),
        )


class FakeFrameLoaderWorker:
    """Mimics FrameLoaderWorker shape."""

    def __init__(self, path=None, parent=None, **kw) -> None:
        self.path = Path(path) if path else Path("/dev/null")
        self.parent = parent
        self.signals = SimpleNamespace(
            finished=FakeSignal(),
            failed=FakeSignal(),
        )


class FakeThumbnailWorker:
    """Mimics ThumbnailLoaderWorker shape."""

    def __init__(self, path=None, size=64, parent=None, **kw) -> None:
        self.path = Path(path) if path else Path("/dev/null")
        self.size = size
        self.parent = parent
        self.signals = SimpleNamespace(
            finished=FakeSignal(),
            failed=FakeSignal(),
        )


class FakeOnnxWorker:
    """Mimics OnnxWorker shape."""

    def __init__(self, *args, parent=None, **kw) -> None:
        self.parent = parent
        self.signals = SimpleNamespace(
            finished=FakeSignal(),
            failed=FakeSignal(),
        )


class FakeSegmenter:
    """Mimics IOnnxSegmenter protocol."""

    def __init__(self, available: bool = False, mask: np.ndarray | None = None) -> None:
        self._available = available
        self._mask = mask

    def is_available(self) -> bool:
        return self._available

    def segment(self, frame: np.ndarray, roi=None) -> np.ndarray:
        if self._mask is not None:
            return self._mask.copy()
        return np.zeros(frame.shape[:2], dtype=np.uint8)


# ═══════════════════════════════════════════════════════════════════
#  Domain model factories
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_signal():
    """Create a fresh FakeSignal."""
    return FakeSignal()


@pytest.fixture
def recording_pool():
    """Create a fresh RecordingThreadPool."""
    return RecordingThreadPool()


@pytest.fixture
def fake_segmenter():
    """Create a FakeSegmenter (not available by default)."""
    return FakeSegmenter(available=False)


@pytest.fixture
def synthetic_dicom_path(tmp_path):
    """Create a synthetic DICOM file and return its path."""
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

    path = tmp_path / "test.dcm"
    write_synthetic_dicom(path)
    return path


@pytest.fixture
def synthetic_multiframe_dicom_path(tmp_path):
    """Create a synthetic multi-frame DICOM file."""
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

    path = tmp_path / "cine.dcm"
    write_synthetic_multiframe_dicom(path, num_frames=8)
    return path


@pytest.fixture
def synthetic_image():
    """Return a synthetic grayscale image (128x128)."""
    img = np.zeros((128, 128), dtype=np.uint8)
    # Draw a bright circle in the center
    y, x = np.ogrid[-64:64, -64:64]
    mask = x**2 + y**2 < 30**2
    img[mask] = 200
    return img


@pytest.fixture
def synthetic_rgb_image():
    """Return a synthetic RGB image (128x128x3)."""
    img = np.zeros((128, 128, 3), dtype=np.uint8)
    img[:, :, 0] = 100  # red channel
    img[:, :, 1] = 150  # green channel
    img[32:96, 32:96, 2] = 200  # blue square
    return img


@pytest.fixture
def sample_instance_metadata(synthetic_dicom_path):
    """Return a minimal InstanceMetadata for tests."""
    from echo_personal_tool.domain.models import InstanceMetadata

    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5.6",
        series_uid="1.2.3.4.5",
        modality="US",
        number_of_frames=1,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test A4C",
        path=synthetic_dicom_path,
        media_format="dicom",
    )


@pytest.fixture
def sample_viewer_state(sample_instance_metadata):
    """Return a ViewerState with sample instance."""
    from echo_personal_tool.domain.models import ViewerState

    return ViewerState(
        instance=sample_instance_metadata,
        current_frame_index=0,
        total_frames=1,
        frame_time_ms=33.3,
        is_playing=False,
    )


@pytest.fixture
def sample_user_preferences():
    """Return default UserPreferences without touching QSettings."""
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences

    return UserPreferences()


# ═══════════════════════════════════════════════════════════════════
#  QSettings isolation
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def isolated_qsettings(monkeypatch: pytest.MonkeyPatch):
    """Isolate QSettings to a temporary org/app so tests don't pollute real settings.

    Usage:
        def test_something(isolated_qsettings):
            # QSettings now uses "sonoforge-test" / "test-<testname>"
            ...
    """
    from PySide6.QtCore import QSettings

    import echo_personal_tool.infrastructure.server_settings as ss
    import echo_personal_tool.infrastructure.user_preferences as up

    test_id = os.environ.get("PYTEST_CURRENT_TEST", "default").split("::")[-1].split(" ")[0]
    org = "sonoforge-test"
    app = f"test-{test_id}"

    monkeypatch.setattr(ss, "_SETTINGS_ORG", org)
    monkeypatch.setattr(ss, "_SETTINGS_APP", app)
    monkeypatch.setattr(up, "_SETTINGS_ORG", org)
    monkeypatch.setattr(up, "_SETTINGS_APP", app)

    store = QSettings(org, app)
    store.clear()
    store.sync()
    yield store
    store.clear()
    store.sync()


# ═══════════════════════════════════════════════════════════════════
#  Widget creation helpers
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def make_viewer(qtbot):
    """Factory fixture: create a ViewerWidget with proper cleanup.

    Usage:
        viewer = make_viewer()
        viewer.show_frame(synthetic_image)
    """
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    def _factory(**kwargs):
        w = ViewerWidget(**kwargs)
        qtbot.addWidget(w)
        return w

    return _factory


@pytest.fixture
def make_main_window(qtbot):
    """Factory fixture: create a MainWindow with real AppController.

    Usage:
        window = make_main_window()
        assert window.isVisible() or True
    """
    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.main_window import MainWindow

    def _factory(controller=None, user_preferences=None, **kwargs):
        ctrl = controller or AppController()
        prefs = user_preferences or UserPreferences(layout_state_json="")
        w = MainWindow(controller=ctrl, user_preferences=prefs, **kwargs)
        qtbot.addWidget(w)
        return w

    return _factory


@pytest.fixture
def make_doppler_overlay(qtbot):
    """Factory fixture: create DopplerOverlayTools with a real PlotWidget."""
    import pyqtgraph as pg

    from echo_personal_tool.presentation.doppler_overlay import DopplerOverlayTools

    def _factory(parent=None):
        plot = pg.PlotWidget()
        qtbot.addWidget(plot)
        overlay = DopplerOverlayTools(plot, parent=parent)
        return overlay, plot

    return _factory


@pytest.fixture
def make_mmode_widget(qtbot):
    """Factory fixture: create MModeWidget with proper cleanup."""
    from echo_personal_tool.presentation.mmode_widget import MModeWidget

    def _factory(buffer_width=512, **kwargs):
        w = MModeWidget(buffer_width=buffer_width, **kwargs)
        qtbot.addWidget(w)
        return w

    return _factory
