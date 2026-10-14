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

import gc
import hashlib
import importlib
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
#  Thread pool hygiene
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _drain_global_thread_pool():
    """Drain the global QThreadPool after every test.

    Tests start QRunnables on QThreadPool.globalInstance(); if a pool
    thread is still running when a test finishes, it can race with the
    next test's Qt event loop (or interpreter shutdown) and SIGSEGV.
    waitForDone() on an idle pool returns immediately.
    """
    yield
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(5000)


@pytest.fixture(autouse=True)
def _isolate_orthanc_cache_root(request, tmp_path, monkeypatch):
    """Keep MainWindow tests from inspecting or deleting a real user cache."""
    if request.module.__name__.endswith(("test_presenter_profile", "test_paths")):
        yield
        return

    from echo_personal_tool.infrastructure import profile

    monkeypatch.setattr(profile, "orthanc_cache_root", lambda: tmp_path / "orthanc-cache")
    yield


@pytest.fixture(autouse=True)
def _isolate_measurement_store(request, tmp_path, monkeypatch):
    if request.module.__name__.endswith(("test_presenter_profile", "test_paths")):
        return
    from echo_personal_tool.infrastructure import paths

    monkeypatch.setattr(paths, "measurements_dir", lambda: tmp_path / "measurements")


@pytest.fixture(autouse=True)
def _isolate_user_settings(request):
    """Run every unit test against a throwaway QSettings store.

    The app loads real user preferences from QSettings; without this a
    developer's saved preferences (for example a changed contour input mode)
    would leak into tests and make them environment-dependent.

    Portable-store tests exercise the real settings files and are left
    untouched, matching the other isolation fixtures in this file.
    """
    if request.module.__name__.endswith(("test_presenter_profile", "test_paths")):
        yield
        return
    store = request.getfixturevalue("isolated_qsettings")
    yield store


@pytest.fixture(autouse=True)
def _gc_per_test():
    """Freeze GC during each test; collect only between tests.

    Prevents segfaults when GC runs *inside* pytestqt._process_events:
    a pyqtgraph PlotCurveItem whose C++ backing is deleted can still be
    reached via pending Qt events → boundingRect() → SIGSEGV.
    """
    gc.disable()
    yield
    gc.enable()
    gc.collect()


#: First non-empty application stylesheet seen, treated as the canonical theme.
_CANONICAL_APP_SHEET: str | None = None


@pytest.fixture(autouse=True)
def _restore_canonical_app_sheet(_gc_per_test):
    """Undo global theme changes a test leaves behind.

    The suite keeps ~90k widgets alive (a C++/Python signal+event-filter cycle
    the Python GC cannot see), so an application-wide ``setStyleSheet`` that
    actually changes the sheet repolishes all of them. The theme tests in
    ``test_presentation_extended`` switched the sheet and left it changed, so
    the next ``MainWindow`` build (~``test_simpson_live_feedback``) paid that
    repolish: ~42s locally and ~62s on CI, past the 60s pytest timeout. Pinning
    the sheet back to the canonical theme keeps later builds a no-op.
    """
    global _CANONICAL_APP_SHEET
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        yield
        return
    yield
    sheet = app.styleSheet()
    if _CANONICAL_APP_SHEET is None:
        if sheet:
            _CANONICAL_APP_SHEET = sheet
    elif sheet != _CANONICAL_APP_SHEET:
        app.setStyleSheet(_CANONICAL_APP_SHEET)


# ═══════════════════════════════════════════════════════════════════
#  QtWebEngine isolation
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _stub_web_engine(request, monkeypatch):
    """Keep unit tests from spinning up a real QtWebEngine view.

    Every ``AseReferenceDialog`` builds a ``WebReferenceWidget`` — a real
    ``QWebEngineView``. ``test_ase_reference_dialog`` and
    ``test_presentation_ase_reference_dialog`` create ~16 of them per xdist
    worker and only ``close()`` them, so their engine pages accumulate and the
    offscreen renderer SIGSEGVs a later Qt test in the same worker
    ("Release of profile requested but WebEnginePage still not deleted").
    Unit tests assert dialog wiring, not web rendering, so swap in a
    lightweight stand-in. Opt back into the real view with
    ``@pytest.mark.real_webengine``.
    """
    if request.node.get_closest_marker("real_webengine"):
        yield
        return

    try:
        from PySide6.QtCore import Signal
        from PySide6.QtWidgets import QWidget

        module = importlib.import_module("echo_personal_tool.presentation.web_reference.web_reference_widget")
    except Exception:  # noqa: BLE001 — no PySide6/QtWebEngine: dialog falls back to Qt
        yield
        return

    class _StubWebReferenceWidget(QWidget):
        web_failed = Signal()

        def __init__(self, data_store=None, parent=None, **kwargs) -> None:
            super().__init__(parent)
            self._data_store = data_store

        def reload(self) -> None:
            pass

        def reload_page(self) -> None:
            pass

        def apply_theme(self) -> None:
            pass

        def set_maximized_mode(self, maximized: bool) -> None:  # noqa: ARG002
            pass

        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(module, "WebReferenceWidget", _StubWebReferenceWidget)
    yield


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
def isolated_qsettings(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Isolate QSettings to a temporary org/app so tests don't pollute real settings.

    The full node id (including module and parameter ids) is hashed so parallel
    workers cannot clear another test's settings when two modules use the same
    test function name.

    Usage:
        def test_something(isolated_qsettings):
            # QSettings now uses "sonoforge-test" / a unique "test-<hash>" app.
            ...
    """
    from PySide6.QtCore import QSettings

    import echo_personal_tool.infrastructure.server_settings as ss
    import echo_personal_tool.infrastructure.user_preferences as up

    test_id = hashlib.sha256(request.node.nodeid.encode("utf-8")).hexdigest()[:16]
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
def make_main_window(qtbot, tmp_path):
    """Factory fixture: create a MainWindow with real AppController.

    Usage:
        window = make_main_window()
        assert window.isVisible() or True
    """
    from unittest.mock import patch

    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.main_window import MainWindow

    def _factory(controller=None, user_preferences=None, **kwargs):
        ctrl = controller or AppController()
        prefs = user_preferences or UserPreferences(layout_state_json="")
        with patch(
            "echo_personal_tool.infrastructure.profile.orthanc_cache_root",
            return_value=tmp_path / "orthanc-cache",
        ):
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
