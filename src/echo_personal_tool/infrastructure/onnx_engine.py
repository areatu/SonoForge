"""ONNX segmentation inference (Infrastructure)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy import ndimage

from echo_personal_tool.domain.services.segmentation_service import (
    crop_frame_for_echonet,
    embed_echonet_mask,
    logits_to_mask,
    prepare_tensor,
)

if TYPE_CHECKING:
    pass

_ort_module: Any | None = None
_ort_import_failed = False


def _get_ort() -> Any | None:
    """Return onnxruntime module if phase2 extra is installed."""
    global _ort_module, _ort_import_failed
    if _ort_import_failed:
        return None
    if _ort_module is None:
        try:
            import onnxruntime as ort
        except ImportError:
            _ort_import_failed = True
            return None
        _ort_module = ort
    return _ort_module


def _default_models_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        candidate = Path(meipass) / "models"
        if (candidate / "model_manifest.json").is_file():
            return candidate
    for ancestor in Path(__file__).resolve().parents:
        manifest_path = ancestor / "models" / "model_manifest.json"
        if manifest_path.is_file():
            return manifest_path.parent
    return Path(__file__).resolve().parents[3] / "models"


def _load_manifest(models_dir: Path) -> dict[str, Any] | None:
    manifest_path = models_dir / "model_manifest.json"
    if not manifest_path.is_file():
        return None
    with manifest_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_model_path(models_dir: Path, manifest: dict[str, Any]) -> Path | None:
    active_model = manifest.get("active_model")
    if not active_model:
        return None
    models = manifest.get("models", {})
    entry = models.get(active_model)
    if not isinstance(entry, dict):
        return None
    filename = entry.get("filename")
    if not filename:
        return None
    return models_dir / str(filename)


def _resolve_io_names(manifest: dict[str, Any]) -> tuple[str, str]:
    active_model = manifest.get("active_model")
    models = manifest.get("models", {})
    entry = models.get(active_model, {}) if active_model else {}
    onnx_meta = entry.get("onnx", {}) if isinstance(entry, dict) else {}
    input_name = str(onnx_meta.get("input_name", "input"))
    output_name = str(onnx_meta.get("output_name", "logits"))
    return input_name, output_name


def _create_session(model_path: Path) -> Any:
    ort = _get_ort()
    if ort is None:
        msg = "onnxruntime is not installed (install with: uv sync --extra phase2)"
        raise RuntimeError(msg)
    return ort.InferenceSession(
        str(model_path),
        providers=["CPUExecutionProvider"],
    )


def _upscale_mask(mask: np.ndarray, target_shape: tuple[int, int]) -> np.ndarray:
    target_height, target_width = target_shape
    if mask.shape == (target_height, target_width):
        return mask

    zoom_y = target_height / mask.shape[0]
    zoom_x = target_width / mask.shape[1]
    upscaled = ndimage.zoom(mask.astype(np.float32), (zoom_y, zoom_x), order=0)
    return (upscaled >= 0.5).astype(np.uint8)


class OnnxInferenceEngine:
    """Infrastructure implementation of IOnnxSegmenter."""

    def __init__(
        self,
        *,
        models_dir: Path | None = None,
        session: Any | None = None,
    ) -> None:
        self._models_dir = models_dir or _default_models_dir()
        self._manifest = _load_manifest(self._models_dir)
        self._model_path = (
            _resolve_model_path(self._models_dir, self._manifest)
            if self._manifest is not None
            else None
        )
        if self._manifest is not None:
            self._input_name, self._output_name = _resolve_io_names(self._manifest)
        else:
            self._input_name, self._output_name = "input", "logits"

        if session is not None:
            self._session = session
        elif self._model_path is not None and self._model_path.is_file() and _get_ort() is not None:
            self._session = _create_session(self._model_path)
        else:
            self._session = None

    def is_available(self) -> bool:
        return (
            _get_ort() is not None
            and self._manifest is not None
            and self._model_path is not None
            and self._model_path.is_file()
        )

    def segment(
        self,
        frame: np.ndarray,
        *,
        roi_xyxy: tuple[float, float, float, float] | None = None,
        crop_mode: str = "center_square",
    ) -> np.ndarray:
        if self._session is None:
            msg = "ONNX segmentation model is not available"
            raise RuntimeError(msg)

        array = np.asarray(frame)
        if array.ndim == 2:
            original_shape = (int(array.shape[0]), int(array.shape[1]))
        elif array.ndim == 3 and array.shape[2] == 3:
            original_shape = (int(array.shape[0]), int(array.shape[1]))
        else:
            msg = "frame must be grayscale H×W or color H×W×3"
            raise ValueError(msg)

        cropped, transform = crop_frame_for_echonet(
            array,
            roi_xyxy=roi_xyxy,
            crop_mode=crop_mode,
        )
        tensor = prepare_tensor(cropped)
        outputs = self._session.run(
            [self._output_name],
            {self._input_name: tensor},
        )
        mask = logits_to_mask(outputs[0])
        embedded = embed_echonet_mask(mask, transform)
        if embedded.shape != original_shape:
            return _upscale_mask(embedded, original_shape)
        return embedded
