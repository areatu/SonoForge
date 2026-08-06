"""Background worker for ONNX segmentation inference."""

from __future__ import annotations

import atexit
import json
import logging
import multiprocessing
import signal
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine

_log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SEC = 2.0
_pool: multiprocessing.pool.Pool | None = None
_pool_lock = threading.Lock()
_pool_shutting_down = False


def _default_models_dir() -> Path:
    # User data dir (installed mode: downloaded by launcher/runtime_setup)
    user_models = Path.home() / ".local" / "share" / "sonoforge" / "models"
    if (user_models / "model_manifest.json").is_file():
        return user_models
    # Ancestor traversal (dev mode)
    for ancestor in Path(__file__).resolve().parents:
        manifest_path = ancestor / "models" / "model_manifest.json"
        if manifest_path.is_file():
            return manifest_path.parent
    return Path(__file__).resolve().parents[4] / "models"


def _load_timeout_sec(models_dir: Path) -> float:
    manifest_path = models_dir / "model_manifest.json"
    if not manifest_path.is_file():
        return _DEFAULT_TIMEOUT_SEC
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    inference = manifest.get("inference", {})
    timeout = inference.get("timeout_sec")
    if timeout is None:
        return _DEFAULT_TIMEOUT_SEC
    return float(timeout)


def _init_worker() -> None:
    """Suppress SIGINT in worker processes so parent can shut down cleanly."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _shutdown_pool() -> None:
    global _pool, _pool_shutting_down
    with _pool_lock:
        if _pool is None or _pool_shutting_down:
            return
        _pool_shutting_down = True
        pool = _pool
    try:
        pool.terminate()
        pool.join(timeout=5)
    except Exception:  # noqa: BLE001
        _log.debug("pool shutdown error", exc_info=True)


atexit.register(_shutdown_pool)


def _get_pool() -> multiprocessing.pool.Pool:
    global _pool
    with _pool_lock:
        if _pool is None:
            ctx = multiprocessing.get_context("spawn")
            _pool = ctx.Pool(
                processes=2,
                initializer=_init_worker,
            )
        return _pool


def run_segment_in_subprocess(
    frame_bytes: bytes,
    shape: tuple[int, ...],
    dtype_str: str,
    models_dir_str: str,
    roi_xyxy: tuple[float, float, float, float] | None = None,
    crop_mode: str = "center_square",
    manifest_section: str = "inference",
) -> bytes:
    """Picklable entry point for multiprocessing.Pool subprocess inference."""
    frame = np.frombuffer(frame_bytes, dtype=np.dtype(dtype_str)).reshape(shape)
    engine = OnnxInferenceEngine(
        models_dir=Path(models_dir_str),
        manifest_section=manifest_section,
    )
    mask = engine.segment(frame, roi_xyxy=roi_xyxy, crop_mode=crop_mode)
    return np.ascontiguousarray(mask).tobytes()


class OnnxWorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    timed_out = Signal()


class OnnxWorker(QRunnable):
    """Run ONNX segmentation in a spawn-based process pool."""

    def __init__(
        self,
        frame: np.ndarray,
        *,
        roi_xyxy: tuple[float, float, float, float] | None = None,
        crop_mode: str = "center_square",
        models_dir: Path | None = None,
        manifest_section: str = "inference",
        timeout_sec: float | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._frame = np.ascontiguousarray(frame)
        self._roi_xyxy = roi_xyxy
        self._crop_mode = crop_mode
        self._models_dir = Path(models_dir) if models_dir is not None else _default_models_dir()
        self._manifest_section = manifest_section
        self._timeout_sec = float(timeout_sec) if timeout_sec is not None else _load_timeout_sec(self._models_dir)
        self.signals = OnnxWorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        frame = self._frame
        mask_shape = (int(frame.shape[0]), int(frame.shape[1]))
        try:
            pool = _get_pool()
            async_result = pool.apply_async(
                run_segment_in_subprocess,
                args=(
                    frame.tobytes(),
                    frame.shape,
                    frame.dtype.str,
                    str(self._models_dir),
                    self._roi_xyxy,
                    self._crop_mode,
                    self._manifest_section,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - surface to UI
            self.signals.failed.emit(str(exc))
            return

        # Poll without blocking the QThreadPool so other workers (FrameLoader,
        # VideoDecode) keep running — fixes playback/scroll freezes.
        deadline = time.monotonic() + self._timeout_sec
        while True:
            if async_result.ready():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.signals.timed_out.emit()
                return
            time.sleep(min(0.05, remaining))

        try:
            mask_bytes = async_result.get(timeout=0)
            mask = np.frombuffer(mask_bytes, dtype=np.uint8).reshape(mask_shape)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(str(exc))
            return

        self.signals.finished.emit(mask.copy())
