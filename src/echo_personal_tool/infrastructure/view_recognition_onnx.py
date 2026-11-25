"""ONNX view-recognition inference (Infrastructure).

The ONNX-backed implementation of :class:`~echo_personal_tool.domain.ports.IViewRecognizer`
for a trained view classifier (#639 step 2). Mirrors
:class:`OnnxInferenceEngine`: model path and I/O names are resolved from
``model_manifest.json`` (its own ``view_recognition`` section), integrity is
verified against the manifest SHA256, and a clip is turned into a
``(N, 3, H, W)`` batch via the pure domain helpers
(:mod:`echo_personal_tool.domain.services.view_recognition_inference`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

import numpy as np

try:  # optional dependency — absent in the Presenter (lite) profile
    import onnxruntime as ort
except ImportError:  # pragma: no cover - depends on installed extras
    ort = None

from echo_personal_tool.domain.models.view_recognition import (
    EXTENDED_KNOWN_VIEWS,
    KNOWN_VIEWS,
    RecognizedView,
)
from echo_personal_tool.domain.services.view_recognition_inference import (
    ViewInferenceConfig,
    aggregate_predictions_with_ood,
    prepare_clip_for_view_model,
)
from echo_personal_tool.infrastructure.paths import models_dirs_for_read

#: Manifest section used by this adapter, so the classifier's slot does not
#: collide with the segmentation models' ``inference`` / ``la_inference``.
MANIFEST_SECTION = "view_recognition"

#: Output order of the published ONNX asset. The active set can be shorter
#: (SAX/TEE are not used); raw logits are subset to the active names before
#: aggregation. A future export trained directly on the active set needs no
#: subsetting because the column count then matches ``class_names``.
_TRAINED_CLASS_NAMES: tuple[str, ...] = ("A4C", "A2C", "A3C", "PLAX", "SAX", "PSAX", "TEE")


def _default_models_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        candidate = Path(meipass) / "models"
        if (candidate / "model_manifest.json").is_file():
            return candidate
    for user_models in models_dirs_for_read():
        if (user_models / "model_manifest.json").is_file():
            return user_models
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
        return cast(dict[str, Any], json.load(handle))


def _resolve_class_names(manifest: dict[str, Any] | None, default: Sequence[str]) -> tuple[str, ...]:
    if manifest is not None:
        section = manifest.get(MANIFEST_SECTION, {})
        if isinstance(section, dict):
            raw = section.get("class_names")
            if isinstance(raw, (list, tuple)) and raw:
                return tuple(str(name) for name in raw)
    return tuple(default)


def _resolve_model_path(models_dir: Path, manifest: dict[str, Any]) -> Path | None:
    section = manifest.get(MANIFEST_SECTION, {})
    active_model = section.get("active_model") if isinstance(section, dict) else None
    if not active_model:
        return None
    entry = (manifest.get("models", {}) or {}).get(str(active_model))
    if not isinstance(entry, dict):
        return None
    filename = entry.get("filename")
    if not filename:
        return None
    return models_dir / str(filename)


def _resolve_io_names(manifest: dict[str, Any]) -> tuple[str, str]:
    section = manifest.get(MANIFEST_SECTION, {})
    onnx_meta: dict[str, Any] = {}
    if isinstance(section, dict):
        active_model = section.get("active_model")
        if active_model:
            entry = (manifest.get("models", {}) or {}).get(str(active_model), {})
            onnx_meta = entry.get("onnx", {}) if isinstance(entry, dict) else {}
    return (
        str(onnx_meta.get("input_name", "input")),
        str(onnx_meta.get("output_name", "logits")),
    )


def _resolve_input_size(manifest: dict[str, Any]) -> int:
    section = manifest.get(MANIFEST_SECTION, {})
    onnx_meta: dict[str, Any] = {}
    if isinstance(section, dict):
        active_model = section.get("active_model")
        if active_model:
            entry = (manifest.get("models", {}) or {}).get(str(active_model), {})
            onnx_meta = entry.get("onnx", {}) if isinstance(entry, dict) else {}
    shape = onnx_meta.get("input_shape", [1, 3, 224, 224])
    if isinstance(shape, (list, tuple)) and len(shape) >= 3:
        return int(shape[2])
    return 224


def _resolve_sha256(manifest: dict[str, Any]) -> str | None:
    section = manifest.get(MANIFEST_SECTION, {})
    if not isinstance(section, dict):
        return None
    active_model = section.get("active_model")
    if not active_model:
        return None
    entry = (manifest.get("models", {}) or {}).get(str(active_model), {})
    if not isinstance(entry, dict):
        return None
    sha = entry.get("sha256")
    return str(sha) if sha else None


def _verify_model_integrity(model_path: Path, expected_sha256: str | None) -> None:
    """Check SHA256 of the ONNX model against the manifest entry."""
    if not expected_sha256:
        return
    actual = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(
            f"Model integrity check failed for {model_path.name}: expected {expected_sha256[:16]}…, got {actual[:16]}…"
        )


def _create_session(model_path: Path) -> Any:
    if ort is None:
        raise RuntimeError("onnxruntime is not available in this build")
    return ort.InferenceSession(
        str(model_path),
        providers=["CPUExecutionProvider"],
    )


class OnnxViewRecognizer:
    """Infrastructure implementation of :class:`IViewRecognizer` over ONNX.

    When the model section is missing, the model file is absent, or the
    manifest checksum does not match, construction still succeeds with
    ``is_available() == False`` so the caller can fall back to
    :class:`DisabledViewRecognizer`; only an actual inference call on an
    unavailable model raises.
    """

    def __init__(
        self,
        *,
        models_dir: Path | None = None,
        session: Any | None = None,
        class_names: Sequence[str] = KNOWN_VIEWS,
    ) -> None:
        self._models_dir = models_dir or _default_models_dir()
        self._manifest = _load_manifest(self._models_dir)
        self._class_names = _resolve_class_names(self._manifest, class_names)
        self._model_path = _resolve_model_path(self._models_dir, self._manifest) if self._manifest is not None else None
        if self._manifest is not None:
            self._input_name, self._output_name = _resolve_io_names(self._manifest)
            self._input_size = _resolve_input_size(self._manifest)
            raw_section = self._manifest.get(MANIFEST_SECTION)
            section = raw_section if isinstance(raw_section, dict) else None
            self._inference_config = ViewInferenceConfig.from_manifest_section(
                section,
                input_size=self._input_size,
            )
        else:
            self._input_name, self._output_name = "input", "logits"
            self._input_size = 224
            self._inference_config = ViewInferenceConfig(input_size=self._input_size)

        if session is not None:
            self._session = session
        elif ort is not None and self._model_path is not None and self._model_path.is_file():
            expected_sha256 = _resolve_sha256(self._manifest) if self._manifest else None
            _verify_model_integrity(self._model_path, expected_sha256)
            self._session = _create_session(self._model_path)
        else:
            self._session = None

    def is_available(self) -> bool:
        return (
            ort is not None
            and self._manifest is not None
            and self._model_path is not None
            and self._model_path.is_file()
            and self._session is not None
        )

    @property
    def input_size(self) -> int:
        return self._input_size

    def recognize(self, frames: Sequence[np.ndarray]) -> RecognizedView:
        """Classify a cine clip's frames into a single :class:`RecognizedView`."""
        if self._session is None:
            raise RuntimeError("ONNX view-recognition model is not available")
        batch = prepare_clip_for_view_model(frames, config=self._inference_config)
        logits = self._run_logits(batch)
        probs = self._select_active_columns(self._logits_to_probs(logits))
        cosine_sims: np.ndarray | None = None
        scale = self._inference_config.logit_scale
        if scale is not None and scale > 0.0:
            cosine_sims = self._select_active_columns(logits / float(scale))
        return aggregate_predictions_with_ood(
            probs,
            self._class_names,
            cosine_similarities=cosine_sims,
            min_cosine=self._inference_config.ood_min_cosine,
            max_entropy_ratio=self._inference_config.ood_max_entropy_ratio,
            min_confidence=self._inference_config.ood_min_confidence,
        )

    def _select_active_columns(self, probs: np.ndarray) -> np.ndarray:
        """Drop logits of classes that are not in the active manifest set."""
        trained_names = _TRAINED_CLASS_NAMES
        explicit_order = False
        if self._manifest is not None:
            section = self._manifest.get(MANIFEST_SECTION)
            if isinstance(section, dict):
                raw_trained = section.get("trained_class_names")
                if isinstance(raw_trained, (list, tuple)) and len(raw_trained) == probs.shape[1]:
                    trained_names = tuple(str(name) for name in raw_trained)
                    explicit_order = True
        if not explicit_order and probs.shape[1] == len(self._class_names):
            return probs
        if probs.shape[1] != len(trained_names) and probs.shape[1] == len(EXTENDED_KNOWN_VIEWS):
            trained_names = EXTENDED_KNOWN_VIEWS
        if probs.shape[1] != len(trained_names):
            raise RuntimeError("model output width does not match the trained class order")
        indices: list[int] = []
        for name in self._class_names:
            if name not in trained_names:
                raise RuntimeError(f"class {name!r} is not in the published model output")
            indices.append(trained_names.index(name))
        return probs[:, indices]

    def _run_logits(self, batch: np.ndarray) -> np.ndarray:
        outputs = self._session.run(
            [self._output_name],
            {self._input_name: batch},
        )
        logits = np.asarray(outputs[0], dtype=np.float64)
        if logits.ndim == 1:
            logits = logits[np.newaxis, :]
        return logits

    @staticmethod
    def _logits_to_probs(logits: np.ndarray) -> np.ndarray:
        shifted = logits - logits.max(axis=1, keepdims=True)
        exp = np.exp(shifted)
        probs: np.ndarray = exp / exp.sum(axis=1, keepdims=True)
        return probs
