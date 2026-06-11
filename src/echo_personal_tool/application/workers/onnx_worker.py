"""Background worker for ONNX segmentation inference."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine

_DEFAULT_TIMEOUT_SEC = 2.0
_executor: ProcessPoolExecutor | None = None
_executor_lock = threading.Lock()


def _default_models_dir() -> Path:
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


def _get_executor() -> ProcessPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ProcessPoolExecutor(max_workers=1)
        return _executor


def run_segment_in_subprocess(
    frame_bytes: bytes,
    shape: tuple[int, ...],
    dtype_str: str,
    models_dir_str: str,
) -> bytes:
    """Picklable entry point for ProcessPoolExecutor subprocess inference."""
    frame = np.frombuffer(frame_bytes, dtype=np.dtype(dtype_str)).reshape(shape)
    engine = OnnxInferenceEngine(models_dir=Path(models_dir_str))
    mask = engine.segment(frame)
    return np.ascontiguousarray(mask).tobytes()


class OnnxWorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    timed_out = Signal()


class OnnxWorker(QRunnable):
    """Run ONNX segmentation in a single-worker process pool."""

    def __init__(
        self,
        frame: np.ndarray,
        *,
        models_dir: Path | None = None,
        timeout_sec: float | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._frame = np.ascontiguousarray(frame)
        self._models_dir = Path(models_dir) if models_dir is not None else _default_models_dir()
        self._timeout_sec = (
            float(timeout_sec) if timeout_sec is not None else _load_timeout_sec(self._models_dir)
        )
        self.signals = OnnxWorkerSignals(parent)
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        frame = self._frame
        mask_shape = (int(frame.shape[0]), int(frame.shape[1]))
        try:
            future = _get_executor().submit(
                run_segment_in_subprocess,
                frame.tobytes(),
                frame.shape,
                frame.dtype.str,
                str(self._models_dir),
            )
            mask_bytes = future.result(timeout=self._timeout_sec)
        except FuturesTimeoutError:
            future.cancel()
            self.signals.timed_out.emit()
            return
        except Exception as exc:  # noqa: BLE001 - surface to UI
            self.signals.failed.emit(str(exc))
            return

        mask = np.frombuffer(mask_bytes, dtype=np.uint8).reshape(mask_shape)
        self.signals.finished.emit(mask.copy())
