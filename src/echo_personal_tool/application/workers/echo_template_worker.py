"""Explicit experimental ML.3 worker using the existing bounded spawn pool."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRunnable, Slot

from echo_personal_tool.application.workers.onnx_worker import OnnxWorkerSignals, _get_pool
from echo_personal_tool.domain.services.echo_template_contract import TemplatePrediction


def run_template_in_subprocess(
    frame: np.ndarray,
    models_dir: str,
    phase: str,
    frame_index: int,
    pixel_spacing: tuple[float, float] | None,
    sector_mask: np.ndarray | None,
    requested_view: str | None,
    allow_unvalidated: bool,
) -> TemplatePrediction:
    """No exception text or clinical pixels are logged or sent to UI diagnostics."""
    from echo_personal_tool.infrastructure.echo_template_engine import EchoTemplateEngine

    engine = EchoTemplateEngine(Path(models_dir), allow_unvalidated=allow_unvalidated)
    return engine.predict(
        frame,
        phase=phase,
        frame_index=frame_index,
        pixel_spacing=pixel_spacing,
        sector_mask=sector_mask,
        requested_view=requested_view,
    )


class EchoTemplateWorker(QRunnable):
    """Snapshot inputs on construction; timeout and late delivery never auto-accept."""

    def __init__(
        self,
        frame: np.ndarray,
        *,
        models_dir: Path,
        phase: str,
        frame_index: int,
        pixel_spacing: tuple[float, float] | None,
        sector_mask: np.ndarray | None,
        requested_view: str | None = None,
        allow_unvalidated: bool = False,
        timeout_sec: float = 5.0,
    ) -> None:
        super().__init__()
        if not np.isfinite(timeout_sec) or not 0 < timeout_sec <= 30:
            raise ValueError("invalid template worker timeout")
        self._arguments = (
            np.ascontiguousarray(frame).copy(),
            str(models_dir.resolve()),
            phase,
            frame_index,
            pixel_spacing,
            None if sector_mask is None else np.asarray(sector_mask).copy(),
            requested_view,
            allow_unvalidated,
        )
        self._timeout_sec = timeout_sec
        self.signals = OnnxWorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = _get_pool().apply_async(run_template_in_subprocess, args=self._arguments)
            prediction = result.get(timeout=self._timeout_sec)
        except multiprocessing.TimeoutError:
            self.signals.timed_out.emit()
            return
        except Exception:  # noqa: BLE001 - hard boundary: never expose paths/PHI in worker failures
            self.signals.failed.emit("template_inference")
            return
        self.signals.finished.emit(prediction)
