"""Headless loading audit using production DicomSession, with no patient data in JSON.

Run with the project's environment. Defaults avoid full-cine allocation; --bulk is opt-in.
The pre-fix fallback was O(N²); counters also work with the corrected indexed fallback.
--synthetic creates temporary, non-clinical fixtures.
Private decoder entry points are used deliberately to separate setup from codec cost.
Do not import/run concurrently with the GUI: instrumentation patches a class temporarily.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cv2
import numpy as np
import psutil
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.uid import (
    ExplicitVRLittleEndian,
    JPEG2000Lossless,
    JPEGBaseline8Bit,
    RLELossless,
    SecondaryCaptureImageStorage,
    generate_uid,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from echo_personal_tool.infrastructure import dicom_session as impl


@contextmanager
def fallback_counter():
    counts = Counter()
    lock = threading.Lock()
    original = impl.DicomSession._decode_pydicom_fallback

    def counted(self, index):
        with lock:
            counts["calls"] += 1
        return original(self, index)

    with patch.object(impl.DicomSession, "_decode_pydicom_fallback", counted):
        yield counts


def measure(operation):
    """Wall/CPU timings are disjoint between phases; RSS is NOT a sampled peak."""
    proc = psutil.Process()
    rss_before = proc.memory_info().rss
    with fallback_counter() as counts:
        cpu0, t0 = time.process_time(), time.perf_counter()
        result = operation()
        wall, cpu = time.perf_counter() - t0, time.process_time() - cpu0
    return result, {
        "wall_ms": round(wall * 1000, 3),
        "cpu_ms": round(cpu * 1000, 3),
        "rss_after_mb": round(proc.memory_info().rss / 1e6, 3),
        "rss_delta_mb": round((proc.memory_info().rss - rss_before) / 1e6, 3),
        "fallback_calls": counts["calls"],
    }


def ndarray_backing_bytes(frame):
    """Largest ndarray in the base chain, not a measurement of resident physical pages."""
    size = frame.nbytes
    while isinstance(frame.base, np.ndarray):
        frame = frame.base
        size = max(size, frame.nbytes)
    return size


def compare_j2k(session, indices, workers):
    """Candidate fast path: report sampled pixel equality, never change production routing."""
    ds = session._metadata
    references = {i: session._decode_single_frame(i) for i in indices}
    results = {}

    def candidate(index):
        frame = impl._decode_fragment_cv2(session._encapsulated_frame_bytes(index), int(ds.Rows), int(ds.Columns))
        if frame is None:
            return "failed"
        ref = references[index]
        return "equal" if frame.dtype == ref.dtype and np.array_equal(frame, ref) else "different"

    for count in workers:

        def run(count=count):
            if count == 1:
                return Counter(candidate(i) for i in indices)
            with ThreadPoolExecutor(max_workers=count) as executor:
                return Counter(executor.map(candidate, indices))

        equality, timing = measure(run)
        results[str(count)] = {"sample_equality": dict(equality), **timing}
    return results


def audit_file(
    path: Path, *, samples: int, workers: list[int], bulk: bool, reference: bool, alternatives: bool = False
):
    session = impl.DicomSession()
    phases = {}
    try:
        ds, phases["header_only"] = measure(lambda: pydicom.dcmread(path, stop_before_pixels=True, force=True))
        _, phases["session_open"] = measure(lambda: session.open(path))
        _, phases["pixel_setup"] = measure(session._ensure_pixel_data)
        first, phases["first_frame_codec"] = measure(session.decode_first_frame)
        n = session.frame_count
        indices = np.linspace(0, n - 1, min(samples, n), dtype=int).tolist()
        frame_bytes = first.nbytes
        backing_bytes = ndarray_backing_bytes(first)
        first = None
        _, phases["middle_frame_warm"] = measure(lambda: session.decode_single_frame((n - 1) // 2))

        # This is a warm codec test, NOT end-to-end GUI latency. Discard decoded arrays
        # promptly; do not use list(executor.map(...)), which retains all decoded pixels.
        for count in workers:

            def decode(index):
                return session._decode_single_frame(index).nbytes

            def run(count=count):
                if count == 1:
                    return sum(decode(index) for index in indices)
                with ThreadPoolExecutor(max_workers=count) as executor:
                    return sum(executor.map(decode, indices))

            _, phases[f"warm_codec_threads_{count}"] = measure(run)
        if reference:
            _, phases["pydicom_indexed_middle"] = measure(lambda: pydicom.pixels.pixel_array(path, index=(n - 1) // 2))
        candidate_results = {}
        if alternatives and session._transfer_syntax_uid in impl._JPEG2000_SYNTAXES:
            candidate_results = compare_j2k(session, indices, workers)
        if bulk:
            # Fresh state: include its own open/setup, but split from full decode time.
            session.release()
            _, phases["bulk_open"] = measure(lambda: session.open(path))
            _, phases["bulk_setup"] = measure(session._ensure_pixel_data)
            decoded, phases["bulk_decode"] = measure(session.decode_all_frames)
            del decoded
        return {
            "size_mb": round(path.stat().st_size / 1e6, 3),
            "transfer_syntax": str(ds.file_meta.TransferSyntaxUID),
            "frames": n,
            "rows": int(ds.Rows),
            "columns": int(ds.Columns),
            "samples_per_pixel": int(getattr(ds, "SamplesPerPixel", 1)),
            "bits_allocated": int(ds.BitsAllocated),
            "photometric_interpretation": str(ds.PhotometricInterpretation),
            "decoded_cine_mb": round(frame_bytes * n / 1e6, 3),
            "first_frame_ndarray_backing_mb": round(backing_bytes / 1e6, 3),
            "sampled_frames": len(indices),
            "first_frame_pipeline_ms": round(
                sum(phases[k]["wall_ms"] for k in ("session_open", "pixel_setup", "first_frame_codec")), 3
            ),
            "phases": phases,
            "j2k_cv2_candidate": candidate_results,
        }
    finally:
        session.release()


def make_synthetic(root: Path) -> list[Path]:
    """Deterministic noise stresses the codec; NOT representative ultrasound entropy."""
    rng = np.random.default_rng(20260909)
    files = []
    for kind in ("native", "jpeg", "j2k", "rle"):
        n, side = (24, 128) if kind == "rle" else (60, 512)
        pixels = rng.integers(0, 256, (n, side, side), dtype=np.uint8)
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        path = root / f"{kind}.dcm"
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID = meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID = generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.Rows = ds.Columns = side
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = ds.BitsStored = 8
        ds.HighBit = 7
        ds.PixelRepresentation = 0
        ds.NumberOfFrames = n
        ds.PixelData = pixels.tobytes()
        if kind in ("jpeg", "j2k"):
            if kind == "j2k":
                import openjpeg

                fragments = [openjpeg.encode(frame) for frame in pixels]
                meta.TransferSyntaxUID = JPEG2000Lossless
            else:
                fragments = []
                for frame in pixels:
                    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    if not ok:
                        raise RuntimeError("JPEG encoder failed")
                    fragments.append(encoded.tobytes())
                meta.TransferSyntaxUID = JPEGBaseline8Bit
            ds.PixelData = encapsulate(fragments)
            ds["PixelData"].is_undefined_length = True
        elif kind == "rle":
            ds.compress(RLELossless)
        ds.save_as(path, enforce_file_format=True)
        files.append(path)
    return files


def cross_session_probe(a_path: Path, b_path: Path):
    """Deterministic interleaving of a batch on A and a thumbnail open on B.

    No artificial codec failure is injected. A normal batch opens once and reads multiple
    frames, so B can release A's heavy buffers between those calls in production.
    """
    impl._cleanup_all_sessions()
    try:
        a = impl.get_dicom_session(a_path)
        a.open(a_path)
        a.decode_first_frame()
        warm_before = a._has_loadable_pixels()
        b = impl.get_dicom_session(b_path)
        b.open(b_path)
        warm_after = a._has_loadable_pixels()
        _, result = measure(lambda: a.decode_single_frame(1))
        return {"a_warm_before_b": warm_before, "a_warm_after_b": warm_after, "a_next_frame": result}
    finally:
        impl._cleanup_all_sessions()


def discover(paths: list[Path]):
    """Directories: DICM signature, including extensionless files. Explicit files: any."""
    seen = set()
    for root in paths:
        for path in sorted(root.rglob("*")) if root.is_dir() else [root]:
            if not path.is_file() or path.resolve() in seen:
                continue
            if root.is_dir():
                with path.open("rb") as stream:
                    if stream.read(132)[128:132] != b"DICM":
                        continue
            seen.add(path.resolve())
            yield path


def environment():
    packages = {}
    for name in ("numpy", "pydicom", "opencv-python-headless", "pylibjpeg", "pylibjpeg-openjpeg", "pylibjpeg-libjpeg"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {
        "python": platform.python_version(),
        "platform": platform.system(),
        "logical_cpus": os.cpu_count(),
        "opencv_threads": cv2.getNumThreads(),
        "packages": packages,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--workers", nargs="+", type=int, default=[1, 2, 4])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--bulk", action="store_true", help="Can be very slow and use substantial RAM")
    parser.add_argument("--reference", action="store_true", help="Also time pydicom 3 indexed frame API")
    parser.add_argument("--alternatives", action="store_true", help="Compare cv2 J2K speed and sampled pixel equality")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.limit, args.samples, args.repeats, *args.workers) < 1:
        parser.error("numeric arguments must be positive")
    if args.synthetic == bool(args.paths):
        parser.error("choose either --synthetic or input paths")
    report = {"environment": environment(), "synthetic": args.synthetic, "files": []}
    with TemporaryDirectory(prefix="sonoforge-audit-") as tmp:
        paths = make_synthetic(Path(tmp)) if args.synthetic else list(discover(args.paths))[: args.limit]
        if not paths:
            parser.error("no DICOM files found (directory discovery requires DICM preamble)")
        for repeat in range(args.repeats):
            for index, path in enumerate(paths):
                print(f"Auditing file {index + 1}/{len(paths)}, repeat {repeat + 1}", file=sys.stderr)
                entry = {"file_id": index + 1, "repeat": repeat + 1}
                if args.synthetic:
                    entry["fixture"] = path.stem
                try:
                    entry.update(
                        audit_file(
                            path,
                            samples=args.samples,
                            workers=args.workers,
                            bulk=args.bulk,
                            reference=args.reference,
                            alternatives=args.alternatives,
                        )
                    )
                except Exception as exc:
                    # Exception messages can contain paths or DICOM identifiers.
                    entry["error_type"] = type(exc).__name__
                report["files"].append(entry)
        if args.synthetic:
            report["cross_session_probe"] = cross_session_probe(paths[1], paths[2])
    times = [f["first_frame_pipeline_ms"] for f in report["files"] if "first_frame_pipeline_ms" in f]
    report["summary"] = {
        "successful_runs": len(times),
        "failed_runs": len(report["files"]) - len(times),
        "first_frame_pipeline_median_ms": statistics.median(times) if times else None,
        "first_frame_pipeline_p95_ms": float(np.percentile(times, 95)) if times else None,
        "note": "Warm OS cache is uncontrolled; no GUI/queue/paint times or sampled RSS peak.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 1 if report["summary"]["failed_runs"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
