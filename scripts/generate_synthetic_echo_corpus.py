#!/usr/bin/env python3
"""Generate local synthetic DICOM cine, view manifest and chamber gold (#690).

No external datasets or patient media. Optional input: numeric local ML.1 atlas.
Output must be new, outside Git or ignored by Git.
Each synthetic subject's views share one split; UNKNOWN never enters gold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pydicom
import scipy
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, UltrasoundMultiFrameImageStorage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from echo_personal_tool.domain.models.view_recognition import (  # noqa: E402
    TTE_STANDARD_VIEWS,
    ViewRecognitionManifest,
    ViewRecognitionSample,
    ViewSampleMetadata,
)
from echo_personal_tool.domain.services.cardiac_atlas import CoupledShapeModel, build_cardiac_atlas  # noqa: E402
from echo_personal_tool.domain.services.gold_store import save_gold  # noqa: E402
from echo_personal_tool.domain.services.ultrasound_phantom import (  # noqa: E402
    PHANTOM_VIEWS,
    PhantomCine,
    PhantomConfig,
    generate_cine,
)


def synthetic_uid(key: str) -> str:
    return f"2.25.{int.from_bytes(hashlib.sha256(key.encode()).digest()[:16], 'big')}"


def instance_key(cine: PhantomCine, sample_id: str) -> str:
    payload = json.dumps(
        {
            "config": asdict(cine.config),
            "acoustics": asdict(cine.acoustics),
            "pixels_sha256": hashlib.sha256(cine.frames.tobytes()).hexdigest(),
        },
        sort_keys=True,
    )
    return f"atlas_phantom_v1:{sample_id}:{hashlib.sha256(payload.encode()).hexdigest()}"


def write_dicom(path: Path, cine: PhantomCine, subject: str, sample_id: str) -> None:
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = UltrasoundMultiFrameImageStorage
    meta.MediaStorageSOPInstanceUID = synthetic_uid(instance_key(cine, sample_id) + ":sop")
    meta.ImplementationClassUID = synthetic_uid("sonoforge:phantom:1")
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = synthetic_uid(subject)
    ds.SeriesInstanceUID = synthetic_uid(instance_key(cine, sample_id) + ":series")
    ds.PatientID = subject
    ds.PatientName = "SYNTHETIC^PHANTOM"
    ds.PatientIdentityRemoved = "YES"
    ds.Modality = "US"
    ds.ImageType = ["DERIVED", "SECONDARY", "SYNTHETIC"]
    ds.Manufacturer = "SonoForge synthetic phantom"
    ds.SeriesDescription = "SYNTHETIC - NOT FOR CLINICAL USE"
    ds.ProtocolName = cine.config.view
    ds.StudyDate = "20000101"
    ds.StudyTime = "000000"
    ds.InstanceNumber = 1
    ds.Rows = cine.config.size
    ds.Columns = cine.config.size
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.NumberOfFrames = len(cine.frames)
    ds.FrameTime = 1000 / cine.config.fps
    ds.FrameIncrementPointer = pydicom.tag.Tag(0x00181063)
    ds.CineRate = cine.config.fps
    ds.HeartRate = round(60 * cine.config.fps / cine.config.frames_per_cycle)
    ds.PixelSpacing = list(cine.pixel_spacing_mm)
    ds.LossyImageCompression = "00"
    ds.PixelData = cine.frames.tobytes()
    ds.save_as(path, enforce_file_format=True)


def write_ground_truth(path: Path, cine: PhantomCine) -> None:
    """All-frame geometry + masks before acoustic dropout; no object/pickle arrays."""
    arrays = {"phases": cine.phases, "sector_mask": cine.sector_mask}
    for prefix, mapping in (
        ("contour", cine.contours),
        ("mask", cine.masks),
        ("landmark", cine.landmarks),
        ("valve", cine.valves),
    ):
        arrays.update({f"{prefix}_{name}": value for name, value in mapping.items()})
    np.savez_compressed(path, **arrays)


def write_chamber_gold(
    directory: Path, cine: PhantomCine, source: Path, subject: str, sample_id: str, split: str
) -> None:
    if cine.config.view == "UNKNOWN":
        return  # OOD is not a standard-view segmentation label.
    for chamber in ("LV", "LA", "RV", "RA"):
        if chamber not in cine.contours:
            continue
        frames = []
        for phase, index in (("ED", cine.ed_frame), ("ES", cine.es_frame)):
            arc = cine.contours[chamber][index]
            record = {
                "frame_index": index,
                "phase": phase,
                "cycle_fraction": float(cine.phases[index]),
                "chamber": chamber,
                "view": cine.config.view,
                "points": arc.tolist(),
                "instance_path": str(source),
                "sop_instance_uid": synthetic_uid(instance_key(cine, sample_id) + ":sop"),
                "contour_closed": chamber in cine.closed_structures,
                "synthetic": True,
            }
            prefix = "MV" if chamber in {"LV", "LA"} else "TV"
            if f"{prefix}_septal" in cine.landmarks:
                record["mitral_annulus" if prefix == "MV" else "tricuspid_annulus"] = [
                    cine.landmarks[f"{prefix}_septal"][index].tolist(),
                    cine.landmarks[f"{prefix}_lateral"][index].tolist(),
                ]
            if f"{chamber}_apex" in cine.landmarks:
                record["apex_landmark"] = cine.landmarks[f"{chamber}_apex"][index].tolist()
            frames.append(record)
        save_gold(
            directory / f"{chamber.lower()}_{sample_id}.json",
            {
                "study_id": subject,
                "study_uid": synthetic_uid(subject),
                "chamber": chamber,
                "view": cine.config.view,
                "instance_path": str(source),
                "frames": frames,
                "pixel_spacing_mm": list(cine.pixel_spacing_mm),
                "split": split,
                "synthetic": True,
                "phase_reference": "ventricular_cycle",
            },
        )


def validate_output(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == ROOT or ROOT / ".git" == resolved or ROOT / ".git" in resolved.parents:
        raise ValueError("output must not be the repository or .git")
    if resolved == Path(resolved.anchor):
        raise ValueError("output must be a dedicated new directory")
    if resolved.exists():
        raise ValueError("output already exists; use a new directory (no overwriting)")
    if ROOT in resolved.parents:
        # Git pathspecs use forward slashes on every platform. Do not pass an
        # absolute Windows drive/backslash path to Git for Windows.
        relative = resolved.relative_to(ROOT).as_posix() + "/"
        result = subprocess.run(
            ["git", "check-ignore", "--verbose", "-z", "--stdin"],
            input=relative.encode("utf-8") + b"\0",
            capture_output=True,
            cwd=ROOT,
            check=False,
        )
        # Require positive, machine-readable evidence from a project .gitignore,
        # not only an exit code or a workstation-wide excludesFile rule.
        fields = result.stdout.split(b"\0")
        ignored = False
        if result.returncode == 0 and len(fields) == 5 and fields[-1] == b"":
            source, line, pattern, matched = (part.decode("utf-8", errors="surrogateescape") for part in fields[:4])
            rule = Path(source)
            rule = (ROOT / rule).resolve() if not rule.is_absolute() else rule.resolve()
            ignored = (
                matched == relative
                and line.isdigit()
                and bool(pattern)
                and not pattern.startswith("!")
                and rule.name == ".gitignore"
                and ROOT in rule.parents
            )
        if not ignored:
            raise ValueError(
                "output inside repository must be Git-ignored by a project .gitignore (e.g. .cache/phantom-run)"
            )
    return resolved


def load_atlases(paths: list[Path]) -> dict[str, CoupledShapeModel]:
    models = {}
    for path in paths:
        with path.open("rb") as handle:
            raw = handle.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("atlas artifact exceeds 8 MiB")
        model = CoupledShapeModel.from_dict(json.loads(raw))
        if model.view in models:
            raise ValueError("duplicate atlas view")
        models[model.view] = model
    return models


def generate_corpus(args: argparse.Namespace) -> Path:
    output = validate_output(args.output)
    models = load_atlases(args.atlas)
    # Validate bounded configuration before creating any directory.
    PhantomConfig(
        size=args.size, fps=args.fps, frames_per_cycle=args.frames_per_cycle, cycles=args.cycles, seed=args.seed
    )
    if not 1 <= args.subjects <= 1000:
        raise ValueError("subjects must be 1..1000; generate large corpora in bounded batches")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".phantom-", dir=output.parent) as temporary:
        staging = Path(temporary) / "corpus"
        (staging / "clips").mkdir(parents=True)
        (staging / "gold").mkdir()
        (staging / "truth").mkdir()
        (staging / "atlases").mkdir()
        atlas_hashes = {}
        for view in args.views:
            key = "A4C" if view in {"SUBCOSTAL", "UNKNOWN"} else view
            if key in atlas_hashes:
                continue
            if key not in models:
                models[key] = build_cardiac_atlas(key)
            model = models[key]
            payload = json.dumps(model.to_dict(), sort_keys=True).encode()
            atlas_hashes[key] = hashlib.sha256(payload).hexdigest()
            (staging / "atlases" / f"{key}.json").write_bytes(payload)
        samples = []
        records = []
        for subject_index in range(args.subjects):
            subject = f"phantom-{args.seed}-{subject_index:05d}"
            split = "val" if subject_index % 10 == 8 else "test" if subject_index % 10 == 9 else "train"
            seed = int(
                np.random.SeedSequence([args.seed, subject_index]).generate_state(1, dtype=np.uint64)[0] % (2**63)
            )
            for view in args.views:
                sample_id = f"{subject}-{view.lower()}"
                unknown_kind = (
                    ("off_axis", "foreshortened", "rib_occluded")[subject_index % 3]
                    if args.unknown_kind == "cycle"
                    else args.unknown_kind
                )
                config = PhantomConfig(
                    view=view,
                    seed=seed,
                    size=args.size,
                    fps=args.fps,
                    frames_per_cycle=args.frames_per_cycle,
                    cycles=args.cycles,
                    unknown_kind=unknown_kind,
                )
                atlas_view = "A4C" if view in {"SUBCOSTAL", "UNKNOWN"} else view
                cine = generate_cine(config, atlas_model=models.get(atlas_view))
                source = output / "clips" / f"{sample_id}.dcm"
                write_dicom(staging / "clips" / source.name, cine, subject, sample_id)
                write_ground_truth(staging / "truth" / f"{sample_id}.npz", cine)
                write_chamber_gold(staging / "gold", cine, source, subject, sample_id, split)
                samples.append(
                    ViewRecognitionSample(
                        sample_id,
                        str(source),
                        view,
                        split,
                        ViewSampleMetadata(protocol_name=view, vendor="SYNTHETIC", acquisition_note="atlas_phantom_v1"),
                    )
                )
                records.append(
                    {
                        "sample_id": sample_id,
                        "subject": subject,
                        "split": split,
                        "config": asdict(config),
                        "acoustics": asdict(cine.acoustics),
                        "atlas_provenance": cine.atlas_provenance,
                        "atlas_sha256": atlas_hashes[atlas_view],
                        "coefficients": cine.coefficients,
                        "ed_frame": cine.ed_frame,
                        "es_frame": cine.es_frame,
                        "closed_structures": cine.closed_structures,
                        "pixel_spacing_mm": cine.pixel_spacing_mm,
                    }
                )
        manifest = ViewRecognitionManifest(tuple(samples), class_names=TTE_STANDARD_VIEWS)
        (staging / "manifest.json").write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
        (staging / "generation.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "synthetic": True,
                    "generator": "atlas_phantom_v1",
                    "numpy_version": np.__version__,
                    "scipy_version": scipy.__version__,
                    "pydicom_version": pydicom.__version__,
                    "records": records,
                    "limitations": "Projected 2D surrogate; no clinical validation. No external datasets. ES is nearest sampled phase.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if output.exists():
            raise ValueError("output appeared during generation; refusing replacement")
        staging.rename(output)
    return output / "manifest.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--atlas", type=Path, action="append", default=[], help="Local ML.1 numeric JSON; repeat per view"
    )
    parser.add_argument("--subjects", type=int, default=1)
    parser.add_argument("--views", nargs="+", choices=PHANTOM_VIEWS, default=list(PHANTOM_VIEWS))
    parser.add_argument(
        "--unknown-kind", choices=("cycle", "off_axis", "foreshortened", "rib_occluded"), default="cycle"
    )
    parser.add_argument("--size", type=int, default=224)
    parser.add_argument("--fps", type=int, default=50)
    parser.add_argument("--frames-per-cycle", type=int, default=50)
    parser.add_argument("--cycles", type=int, default=1)
    args = parser.parse_args(argv)
    if len(set(args.views)) != len(args.views):
        parser.error("duplicate views are not allowed")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = generate_corpus(args)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        sys.stderr.write(f"generation failed: {exc}\n")
        return 2
    sys.stdout.write(f"Synthetic corpus ready: {manifest}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
