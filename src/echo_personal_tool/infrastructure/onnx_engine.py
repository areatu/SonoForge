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


def _resolve_model_path(
    models_dir: Path,
    manifest: dict[str, Any],
    *,
    manifest_section: str = "inference",
) -> Path | None:
    section = manifest.get(manifest_section, {})
    active_model = section.get("active_model") if isinstance(section, dict) else None
    if not active_model:
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


def _resolve_io_names(
    manifest: dict[str, Any],
    *,
    manifest_section: str = "inference",
) -> tuple[str, str]:
    section = manifest.get(manifest_section, {})
    active_model = section.get("active_model") if isinstance(section, dict) else None
    if not active_model:
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
    upscaled = ndimage.zoom(mask.astype(np.float32), (zoom_y, zoom_x), order=1)
    return (upscaled >= 0.5).astype(np.uint8)


class OnnxInferenceEngine:
    """Infrastructure implementation of IOnnxSegmenter."""

    def __init__(
        self,
        *,
        models_dir: Path | None = None,
        session: Any | None = None,
        manifest_section: str = "inference",
    ) -> None:
        self._models_dir = models_dir or _default_models_dir()
        self._manifest = _load_manifest(self._models_dir)
        self._manifest_section = manifest_section
        self._model_path = (
            _resolve_model_path(
                self._models_dir, self._manifest, manifest_section=manifest_section,
            )
            if self._manifest is not None
            else None
        )
        if self._manifest is not None:
            self._input_name, self._output_name = _resolve_io_names(
                self._manifest, manifest_section=manifest_section,
            )
        else:
            self._input_name, self._output_name = "input", "logits"
        self._input_size = self._resolve_input_size()

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

        fixed_mean, fixed_std = self._resolve_normalization_params()
        tensor = prepare_tensor(cropped, target_size=self._input_size, fixed_mean=fixed_mean, fixed_std=fixed_std)
        outputs = self._session.run(
            [self._output_name],
            {self._input_name: tensor},
        )

        logit_threshold = self._resolve_logit_threshold()
        mask = logits_to_mask(outputs[0], threshold=logit_threshold)
        embedded = embed_echonet_mask(mask, transform)
        if embedded.shape != original_shape:
            return _upscale_mask(embedded, original_shape)
        return embedded

    def _resolve_normalization_params(
        self,
    ) -> tuple[list[float] | None, list[float] | None]:
        """Resolve fixed mean/std from manifest preprocessing config."""
        if self._manifest is None:
            return None, None
        preprocessing = self._manifest.get("preprocessing", {})
        if not isinstance(preprocessing, dict):
            return None, None
        mode = preprocessing.get("normalization_mode", "per_frame")
        if mode == "per_frame":
            return None, None
        fixed_mean = preprocessing.get("fixed_mean")
        fixed_std = preprocessing.get("fixed_std")
        if fixed_mean is None or fixed_std is None:
            return None, None
        return list(fixed_mean), list(fixed_std)

    def _resolve_logit_threshold(self) -> float | None:
        """Resolve logit threshold from manifest inference config."""
        if self._manifest is None:
            return None
        inference = self._manifest.get("inference", {})
        if not isinstance(inference, dict):
            return None
        threshold = inference.get("logit_threshold")
        if threshold is None:
            return None
        return float(threshold)

    def _resolve_input_size(self) -> int:
        """Resolve model input spatial size from manifest, default 112."""
        if self._manifest is None:
            return 112
        models = self._manifest.get("models", {})
        manifest_section = getattr(self, "_manifest_section", "inference")
        section = self._manifest.get(manifest_section, {})
        active = None
        if isinstance(section, dict):
            active = section.get("active_model")
        if not active:
            active = self._manifest.get("active_model", "")
        entry = models.get(active, {}) if isinstance(models, dict) else {}
        onnx_meta = entry.get("onnx", {}) if isinstance(entry, dict) else {}
        shape = onnx_meta.get("input_shape", [1, 3, 112, 112])
        if isinstance(shape, (list, tuple)) and len(shape) >= 3:
            return int(shape[2])
        return 112
