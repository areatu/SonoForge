"""Verified, opt-in ML.3 ONNX bundle adapter; legacy segmenters are unchanged."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from echo_personal_tool.domain.services.cardiac_atlas import CoupledShapeModel
from echo_personal_tool.domain.services.echo_template_contract import (
    TEMPLATE_OUTPUTS,
    TEMPLATE_SCHEMA,
    TEMPLATE_VIEWS,
    TemplatePrediction,
    prepare_template_input,
    validate_atlases,
)
from echo_personal_tool.domain.services.echo_template_service import decode_template_prediction


def verified_bundle_file(root: Path, record: dict[str, Any], *, max_bytes: int) -> Path:
    relative = Path(str(record["path"]))
    path = (root / relative).resolve()
    if relative.is_absolute() or root.resolve() not in path.parents:
        raise ValueError("bundle path escapes model directory")
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError("missing or oversized model artifact")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != record.get("sha256"):
        raise ValueError("model artifact SHA-256 mismatch")
    return path


class EchoTemplateEngine:
    """One CPU session per immutable bundle, no downloads or random fallback weights."""

    def __init__(self, models_dir: Path, *, allow_unvalidated: bool = False) -> None:
        root = models_dir.resolve()
        manifest_path = root / "model_manifest.json"
        if manifest_path.stat().st_size > 1024 * 1024:
            raise ValueError("oversized model manifest")
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))["echo_template"]
        data = self.manifest
        if data.get("schema_version") != TEMPLATE_SCHEMA or tuple(data.get("class_names", ())) != TEMPLATE_VIEWS:
            raise ValueError("unsupported template schema/taxonomy")
        if data.get("preprocessing") != "sector_ecg_iyx_v1":
            raise ValueError("unsupported template preprocessing")
        if not data.get("clinical_validated", False) and not allow_unvalidated:
            raise ValueError("experimental template bundle requires explicit opt-in")
        self.input_size = int(data["input_size"])
        if not 64 <= self.input_size <= 512 or self.input_size % 32:
            raise ValueError("invalid template input size")
        path = verified_bundle_file(root, data["model"], max_bytes=64 * 1024 * 1024)
        self.atlases = {
            view: CoupledShapeModel.from_dict(
                json.loads(verified_bundle_file(root, entry, max_bytes=8 * 1024 * 1024).read_text())
            )
            for view, entry in data["atlases"].items()
        }
        validate_atlases(self.atlases)
        self.ood = {key: float(data["ood"][key]) for key in ("min_cosine", "min_confidence", "max_entropy")}
        if not all(np.isfinite(value) and 0 <= value <= 1 for value in self.ood.values()):
            raise ValueError("invalid OOD thresholds")
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        model_bytes = path.read_bytes()
        if hashlib.sha256(model_bytes).hexdigest() != data["model"]["sha256"]:
            raise ValueError("model artifact SHA-256 mismatch")
        # Bytes-only loading cannot resolve unhashed external tensor files.
        self.session = ort.InferenceSession(model_bytes, sess_options=options, providers=["CPUExecutionProvider"])
        if [x.name for x in self.session.get_outputs()] != list(TEMPLATE_OUTPUTS):
            raise ValueError("incompatible ONNX output names")
        inputs = self.session.get_inputs()
        if (
            len(inputs) != 1
            or inputs[0].name != "image"
            or inputs[0].shape[1:] != [3, self.input_size, self.input_size]
        ):
            raise ValueError("incompatible ONNX input")

    def raw(self, frame: np.ndarray) -> tuple[dict[str, np.ndarray], Any]:
        tensor, transform = prepare_template_input(frame, input_size=self.input_size)
        values = self.session.run(list(TEMPLATE_OUTPUTS), {"image": tensor})
        return dict(zip(TEMPLATE_OUTPUTS, values)), transform

    def predict(
        self,
        frame: np.ndarray,
        *,
        phase: str,
        frame_index: int,
        pixel_spacing: tuple[float, float] | None,
        sector_mask: np.ndarray | None,
        requested_view: str | None = None,
        refine_rv: bool = True,
    ) -> TemplatePrediction:
        outputs, transform = self.raw(frame)
        return decode_template_prediction(
            outputs,
            self.atlases,
            transform,
            frame,
            phase=phase,
            frame_index=frame_index,
            pixel_spacing=pixel_spacing,
            sector_mask=sector_mask,
            requested_view=requested_view,
            refine_rv=refine_rv,
            min_cosine=self.ood["min_cosine"],
            min_confidence=self.ood["min_confidence"],
            max_entropy=self.ood["max_entropy"],
        )
