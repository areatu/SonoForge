"""Local RAM-only raw cine input for ML.4. Never persist source identities/pixels."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pydicom

from echo_personal_tool.domain.services.echo_template_contract import TEMPLATE_VIEWS, prepare_template_input
from echo_personal_tool.domain.services.phase_field import build_phase_field
from echo_personal_tool.domain.services.segmentation_preprocess import mask_burned_ecg_for_segmentation


def clean_raw_sector(frames):
    """Suppress disconnected overlays with one clip-wide tissue mask in RAM.

    Not an anonymizer: text inside connected tissue cannot reliably be removed.
    This is why neither the cleaned pixels nor crops are ever persisted.
    """
    from scipy import ndimage

    from echo_personal_tool.domain.services.segment_roi import detect_view_sector_crop_box

    y0, x0, y1, x1 = detect_view_sector_crop_box(frames, pad_ratio=0)
    sample = np.stack([frames[i] for i in np.linspace(0, len(frames) - 1, min(len(frames), 8), dtype=int)])
    active = np.max(sample, axis=0) > 0.05
    active[:y0] = active[y1:] = False
    active[:, :x0] = active[:, x1:] = False
    opened = ndimage.binary_opening(active, structure=np.ones((3, 3), bool))
    labels, count = ndimage.label(opened)
    if not count:
        return [np.zeros_like(f) for f in frames]
    counts = np.bincount(labels.ravel())
    counts[0] = 0
    mask = ndimage.binary_fill_holes(labels == np.argmax(counts))
    # Preserve edge speckle without reconnecting distant text/rulers.
    mask = ndimage.binary_dilation(mask, iterations=1)
    return [np.where(mask, f, 0).astype(np.float32) for f in frames]


@dataclass(frozen=True)
class RawClip:
    path: Path = field(repr=False)
    group: str = field(repr=False)
    split: str = "train"
    view: str | None = None
    instance: str = field(default="", repr=False)
    patient_key: str = field(default="", repr=False)


def load_raw_inventory(*, manifest: Path | None, dicom_dir: Path | None, seed=0, max_clips=64):
    if (manifest is None) == (dicom_dir is None) or not 1 <= max_clips <= 1024:
        raise ValueError("choose one bounded local raw source")
    if manifest is not None:
        data = json.loads(manifest.read_text())
        if data.get("schema_version") != 1:
            raise ValueError("unsupported raw manifest")
        records = data["clips"]
        if len(records) > max_clips:
            raise ValueError("too many raw clips; curate or raise explicit limit")
        root = manifest.resolve().parent
    else:
        root = dicom_dir.resolve()
        # Stop rather than silently selecting a biased filesystem prefix.
        records = []
        for path in root.rglob("*.dcm"):
            records.append({"path": str(path)})
            if len(records) > max_clips:
                raise ValueError("too many raw clips; curate or raise explicit limit")
        records.sort(key=lambda record: record["path"])
    clips = []
    groups, instances, patients = {}, {}, {}
    for record in records:
        path = Path(record["path"])
        path = (root / path).resolve() if not path.is_absolute() else path.resolve()
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        # These identifiers live only in RAM. Missing patient identity is one
        # common group, NOT one unrelated patient per filename/study.
        patient = str(getattr(ds, "PatientID", ""))
        patient_key = str(getattr(ds, "IssuerOfPatientID", "")) + ":" + patient if patient else ""
        group = str(
            record.get("patient_group_id")
            or (str(getattr(ds, "IssuerOfPatientID", "")) + ":" + patient if patient else "unidentified")
        )
        bucket = int(hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()[:8], 16) % 10
        split = str(record.get("split") or ("test" if bucket == 9 else "val" if bucket >= 7 else "train"))
        view = record.get("view")
        if split not in {"train", "val", "test"} or view is not None and view not in TEMPLATE_VIEWS:
            raise ValueError("invalid raw split/view")
        uid = str(getattr(ds, "SOPInstanceUID", ""))
        if not uid:
            raise ValueError("raw cine needs instance identity")
        if patient_key and patient_key in patients and patients[patient_key] != split:
            raise ValueError("raw patient identity leakage")
        if patient_key:
            patients[patient_key] = split
        if group in groups and groups[group] != split:
            raise ValueError("raw patient leakage")
        if uid in instances:
            raise ValueError("duplicate raw DICOM instance")
        groups[group], instances[uid] = split, (group, split)
        clips.append(RawClip(path, group, split, view, uid, patient_key))
    if not clips:
        raise ValueError("no raw DICOM clips")
    return clips


def check_gold_separation(clips, gold_samples):
    """Use real SOP identities as well as paths/groups; copies cannot bypass split."""
    identities = {clip.instance: clip for clip in clips}
    paths = {clip.path: clip for clip in clips}
    groups = {clip.group: clip.split for clip in clips}
    patients = {clip.patient_key: clip.split for clip in clips if clip.patient_key}
    gold_instances = {}
    for sample in gold_samples:
        if sample.split not in {"train", "val", "test"}:
            raise ValueError("gold needs explicit curated splits")
        ds = pydicom.dcmread(sample.path, stop_before_pixels=True)
        patient = str(getattr(ds, "PatientID", ""))
        patient_key = str(getattr(ds, "IssuerOfPatientID", "")) + ":" + patient if patient else ""
        if patient_key in patients and patients[patient_key] != sample.split:
            raise ValueError("raw/gold patient identity leakage")
        if patient_key:
            patients[patient_key] = sample.split
        if sample.group_id in groups and groups[sample.group_id] != sample.split:
            raise ValueError("raw/gold patient leakage")
        groups[sample.group_id] = sample.split
        uid = str(getattr(ds, "SOPInstanceUID", ""))
        identity = (sample.group_id, sample.split)
        if not uid or uid in gold_instances and gold_instances[uid] != identity:
            raise ValueError("gold instance leakage")
        gold_instances[uid] = identity
        match = identities.get(uid) or paths.get(sample.path.resolve())
        if match is not None and (match.split != sample.split or match.group != sample.group_id):
            raise ValueError("raw/gold instance leakage")


def read_raw_clip(clip, *, input_size, max_frames=96, max_dimension=384, max_decoded_mb=128):
    if not 4 <= max_frames <= 96 or not 32 <= max_dimension <= 512 or not 0 < max_decoded_mb <= 256:
        raise ValueError("invalid bounded raw decoder configuration")
    header = pydicom.dcmread(clip.path, stop_before_pixels=True)
    frames_count = int(getattr(header, "NumberOfFrames", 1))
    rows, columns = int(header.Rows), int(header.Columns)
    samples = int(getattr(header, "SamplesPerPixel", 1))
    bytes_estimate = frames_count * rows * columns * samples * max(1, int(header.BitsAllocated) // 8)
    if (
        not 4 <= frames_count <= 10000
        or not 16 <= rows <= 8192
        or not 16 <= columns <= 8192
        or int(header.BitsAllocated) not in {8, 16}
        or samples not in {1, 3}
        or str(header.PhotometricInterpretation) not in {"MONOCHROME2", "RGB", "YBR_FULL", "YBR_FULL_422"}
        or bytes_estimate > max_decoded_mb * 1024**2
    ):
        raise ValueError("raw cine outside memory/format limits")
    ds = pydicom.dcmread(clip.path)
    pixels = ds.pixel_array[:max_frames]
    frame_time = float(getattr(ds, "FrameTime", 0)) or None
    gray, tensors, transforms = [], [], []
    for pixel in pixels:
        cleaned = mask_burned_ecg_for_segmentation(pixel)
        if cleaned.ndim == 3:
            chroma = np.ptp(cleaned.astype(float), axis=-1)
            cleaned = np.where((chroma > 25)[..., None], 0, cleaned)
        image = cleaned.mean(axis=-1) if cleaned.ndim == 3 else cleaned.astype(float)
        factor = min(1.0, max_dimension / max(image.shape))
        if factor < 1:
            image = cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        image = np.asarray((image - image.min()) / max(float(np.ptp(image)), 1e-8), np.float32)
        gray.append(image)
    gray = clean_raw_sector(gray)
    for image in gray:
        tensor, transform = prepare_template_input(image, input_size=input_size)
        tensors.append(tensor[0])
        transforms.append(transform)
    phase_frames = [cv2.resize(f, (96, 96), interpolation=cv2.INTER_AREA) for f in gray]
    phase = build_phase_field(frames=phase_frames, frame_time_ms=frame_time, min_confidence=0.6)
    return np.stack(gray), np.stack(tensors), transforms, phase
