"""Export compact, analysis-ready fixtures from the LFS study clips.

Why this exists: the clips in ``data/dicom/For_pero`` are stored with Git LFS, and
some sandboxes (including the one this module was developed in) can reach the Git
host but not the LFS content host. GitHub Actions runners *can* read LFS, so this
script is run there and commits a compact derivative back into the repository:

* ``tests/fixtures/for_pero/<clip>.npz`` — every frame of the clip, JPEG-encoded,
  plus the measurements the analysis needs (frames, fps, pixel spacing). Full
  spatial resolution, quality chosen per clip to keep the bundle small; this is
  what real-clip regression runs read.
* ``tests/fixtures/for_pero/<clip>.json`` — the DICOM header summary with
  patient-identifying fields removed, including any private tags that look like
  vendor strain results (that is how the module gets reference numbers to compare
  against).
* ``tests/fixtures/for_pero/ui_reference/*.png`` — stills from the vendor screen
  captures (Samsung/Philips STE), used as UI references.
* ``tests/fixtures/for_pero/index.json`` — the inventory of everything above.

Run (in CI, or locally when LFS content is present)::

    python tools/ste_fixture_export.py --source data/dicom/For_pero --out tests/fixtures/for_pero
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

import numpy as np

# Fields removed from the exported header: the derivative travels through the
# repository, and it should not be more identifiable than the source clip.
SCRUBBED = {
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientSex",
    "PatientAge",
    "PatientWeight",
    "OtherPatientIDs",
    "OtherPatientNames",
    "AccessionNumber",
    "InstitutionName",
    "InstitutionAddress",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
    "StudyID",
    "IssuerOfPatientID",
    "RequestingPhysician",
    "DeviceSerialNumber",
}

# Private tags whose keyword suggests a vendor strain/STE result — the numbers to
# compare our GLS with. Kept even when they live in a private block.
STRAIN_HINTS = ("strain", "ste", "gls", "afi", "deform", "speckle", "auto", "long")

MAX_CLIP_MB = 3.0
STILL_WIDTH = 1100


def _load_dataset(path: pathlib.Path):
    import pydicom

    try:
        return pydicom.dcmread(path, force=True)
    except Exception:  # noqa: BLE001 - not a DICOM file at all
        return None


def _fps(dataset) -> float:
    frame_time = getattr(dataset, "FrameTime", None)
    if frame_time:
        try:
            return 1000.0 / float(frame_time)
        except (TypeError, ZeroDivisionError):
            pass
    vector = getattr(dataset, "FrameTimeVector", None)
    if vector is not None and len(vector) > 1:
        try:
            return 1000.0 / float(np.mean([float(v) for v in vector]))
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    cine = getattr(dataset, "CineRate", None)
    return float(cine) if cine else 0.0


def _header_summary(dataset, path: pathlib.Path) -> dict:
    summary: dict = {"file": path.name, "kind": "dicom"}
    for keyword in (
        "Modality",
        "Manufacturer",
        "ManufacturerModelName",
        "SoftwareVersions",
        "Rows",
        "Columns",
        "NumberOfFrames",
        "SamplesPerPixel",
        "PhotometricInterpretation",
        "BitsAllocated",
        "TransferSyntaxUID",
        "PixelSpacing",
        "UltrasoundColorDataPresent",
        "SequenceOfUltrasoundRegions",
    ):
        value = getattr(dataset, keyword, None)
        if value is None:
            continue
        if keyword == "SequenceOfUltrasoundRegions":
            regions = []
            for region in value:
                regions.append(
                    {
                        "origin": [
                            float(getattr(region, "RegionLocationMinX0", 0)),
                            float(getattr(region, "RegionLocationMinY0", 0)),
                        ],
                        "size": [
                            float(getattr(region, "RegionLocationMaxX1", 0))
                            - float(getattr(region, "RegionLocationMinX0", 0)),
                            float(getattr(region, "RegionLocationMaxY1", 0))
                            - float(getattr(region, "RegionLocationMinY0", 0)),
                        ],
                        "physical_delta_mm": [
                            float(getattr(region, "PhysicalDeltaX", 0)) * 10.0,
                            float(getattr(region, "PhysicalDeltaY", 0)) * 10.0,
                        ],
                    }
                )
            summary[keyword] = regions
            continue
        try:
            summary[keyword] = list(value) if hasattr(value, "__iter__") and not isinstance(value, str) else str(value)
        except Exception:  # noqa: BLE001
            summary[keyword] = str(value)

    summary["frames"] = int(getattr(dataset, "NumberOfFrames", 1) or 1)
    summary["fps"] = round(_fps(dataset), 2)

    # ECG: waveform data is stored per channel in (5400,xxxx) blocks.
    waveform_sequences = getattr(dataset, "WaveformSequence", None)
    summary["ecg"] = bool(waveform_sequences)
    if waveform_sequences:
        try:
            channel = waveform_sequences[0]
            samples = np.asarray(channel.WaveformData, dtype=float)
            summary["ecg_samples"] = int(samples.size)
            summary["ecg_channel"] = str(getattr(channel, "ChannelSourceSequence", [{}])[0].get("CodeMeaning", ""))
            summary["ecg_sampling_hz"] = float(getattr(channel, "SamplingFrequency", 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            pass
    summary["ecg_burn_in_hint"] = bool(getattr(dataset, "NumberOfFrames", 0)) and "ECG" in path.name.upper()

    private = {}
    for element in dataset:
        keyword = element.keyword or ""
        name = str(element.name)
        if element.tag.is_private or any(hint in name.lower() for hint in STRAIN_HINTS):
            try:
                text = str(element.value)
            except Exception:  # noqa: BLE001
                continue
            if len(text) > 400:
                text = text[:400] + "…"
            private[f"{element.tag} {name}"] = text
        if keyword in SCRUBBED:
            private.pop(f"{element.tag} {name}", None)
    summary["private_or_strain_tags"] = private
    return summary


def _frames_from_pixels(dataset) -> np.ndarray:
    array = np.asarray(dataset.pixel_array)
    if array.ndim == 2:
        return array[None, ...]
    if array.ndim == 4:  # colour cine
        array = array[..., :3].mean(axis=-1)
    return array.astype(np.float32, copy=False)


def _encode_frames(frames: np.ndarray, quality: int) -> np.ndarray:
    import cv2

    encoded = []
    for frame in frames:
        frame = np.asarray(frame)
        low, high = float(np.min(frame)), float(np.max(frame))
        scaled = (frame - low) / (high - low) * 255.0 if high > low else np.zeros_like(frame)
        ok, buffer = cv2.imencode(".jpg", scaled.astype(np.uint8), [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if ok:
            encoded.append(buffer.tobytes())
    return np.array(encoded, dtype=object)


def _export_clip(path: pathlib.Path, out_dir: pathlib.Path) -> dict | None:
    dataset = _load_dataset(path)
    if dataset is None or not hasattr(dataset, "pixel_array"):
        return None
    summary = _header_summary(dataset, path)
    frames = _frames_from_pixels(dataset)
    name = path.stem if path.suffix else path.name

    quality = 92
    for attempt in range(4):
        encoded = _encode_frames(frames, quality)
        bundle = {
            "frames_jpeg": encoded,
            "frame_min": np.array([float(np.min(f)) for f in frames]),
            "frame_max": np.array([float(np.max(f)) for f in frames]),
            "fps": np.float64(summary["fps"]),
            "pixel_spacing_mm": np.array([float(v) for v in (summary.get("PixelSpacing") or [1.0, 1.0])]),
        }
        target = out_dir / f"{name}.npz"
        np.savez_compressed(target, **bundle)
        size_mb = target.stat().st_size / 1048576
        if size_mb <= MAX_CLIP_MB or quality <= 70:
            break
        quality -= 8

    summary.update(
        {
            "npz": target.name,
            "npz_mb": round(target.stat().st_size / 1048576, 2),
            "jpeg_quality": quality,
            "size_mb": round(path.stat().st_size / 1048576, 2),
            "shape": [int(v) for v in frames.shape],
        }
    )
    (out_dir / f"{name}.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"  ✓ {name:20} {frames.shape[0]:3d} кадров {frames.shape[2]}×{frames.shape[1]} "
        f"fps {summary['fps']:5.1f} ECG={summary['ecg']} → {summary['npz_mb']:5.2f} МБ (q{quality})"
    )
    return summary


def _export_stills(path: pathlib.Path, out_dir: pathlib.Path) -> dict:
    import cv2

    capture = cv2.VideoCapture(str(path))
    summary: dict = {"file": path.name, "kind": "media"}
    if not capture.isOpened():
        summary["error"] = "не открывается как видео"
        size_mb = path.stat().st_size / 1048576
        summary["size_mb"] = round(size_mb, 2)
        # Not a video: still useful — take the raw bytes as one still so the UI
        # reference can be inspected.
        summary["stills"] = []
        print(f"  ~ {path.name:22} не видео ({size_mb:.1f} МБ)")
        return summary

    fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    summary.update(
        {"fps": round(float(fps), 2), "frames": total, "size_px": [width, height],
         "size_mb": round(path.stat().st_size / 1048576, 2)}
    )

    stills: list[str] = []
    picks = np.linspace(0, max(total - 1, 0), num=6, dtype=int) if total else []
    for index in picks:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, frame = capture.read()
        if not ok:
            continue
        if frame.shape[1] > STILL_WIDTH:
            scale = STILL_WIDTH / frame.shape[1]
            frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        still_name = f"{path.stem if path.suffix else path.name}_f{int(index):04d}.png"
        cv2.imwrite(str(out_dir / "ui_reference" / still_name), frame)
        stills.append(f"ui_reference/{still_name}")
    capture.release()
    summary["stills"] = stills
    print(f"  ✓ {path.name:22} видео {total} кадров {width}×{height} @ {fps:.1f} fps → {len(stills)} стоп-кадров")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=pathlib.Path, default=pathlib.Path("data/dicom/For_pero"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("tests/fixtures/for_pero"))
    args = parser.parse_args()

    if not args.source.exists():
        print(f"нет каталога {args.source} — LFS-контент не выкачан", file=sys.stderr)
        return 2

    if args.out.exists():
        shutil.rmtree(args.out)
    (args.out / "ui_reference").mkdir(parents=True, exist_ok=True)

    entries = []
    for path in sorted(args.source.iterdir()):
        if not path.is_file():
            continue
        if path.stat().st_size < 1024:  # still an LFS pointer
            print(f"  ! {path.name}: LFS-указатель, контент не выкачан")
            continue
        clip = _export_clip(path, args.out)
        if clip is None:
            clip = _export_stills(path, args.out)
        entries.append(clip)

    index = {
        "source": str(args.source),
        "clips": entries,
        "total_mb": round(
            sum(e.get("npz_mb", 0.0) + 6 * 0.15 for e in entries), 2
        ),
    }
    (args.out / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nиндекс: {args.out / 'index.json'} ({len(entries)} файлов)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
