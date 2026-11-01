"""Packaged-artifact smoke: first launch → save → restart → export (QH-5a).

The plan (spec 2026-10-13 §9.1, A-16) is explicit that a release is confirmed by
the **packaged artifact**, not by importing the checkout: "first launch,
synthetic DICOM/cine, measurement/save/restart/restore, text/PDF export,
settings/privacy boundaries". This module is that scenario, written once and
executed in three places:

* from source in the required CI job (the smoke logic itself),
* through ``<artifact> --package-smoke save|restart`` on the frozen PyInstaller
  builds (Windows onedir/onefile, macOS ``.app``, Presenter),
* against the extracted payload of the lite ``.deb`` (``payload`` smoke level in
  ``.github/package-matrix.yml``).

Two stages run in **separate processes** — that is the restart. Stage ``save``
writes a synthetic cine, saves measurements through the real persistence layer
and exports text + PDF; stage ``restart`` is a fresh interpreter that restores
the record from disk, re-exports, and must produce the same text bytes.

Everything here is synthetic: the study UID, the patient header and the pixels
are generated locally, the data directory is a temporary directory handed in by
the caller (portable storage), and the JSON manifest carries no absolute paths.

CLI::

    python -m echo_personal_tool.application.package_smoke save \\
        --workdir /tmp/smoke --expect-profile full --json /tmp/smoke/save.json
    python -m echo_personal_tool.application.package_smoke restart \\
        --workdir /tmp/smoke --expect-profile full --expect /tmp/smoke/save.json \\
        --json /tmp/smoke/restart.json
    python -m echo_personal_tool.application.package_smoke compare \\
        /tmp/smoke/save.json /tmp/smoke/restart.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Deliberately not imported at runtime: the smoke must stay importable
    # before the application package is fully wired (#325).
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
    from echo_personal_tool.domain.models import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot

SCHEMA = 1
KIND = "sonoforge.package-smoke"
STAGE_SAVE = "save"
STAGE_RESTART = "restart"
STAGES = (STAGE_SAVE, STAGE_RESTART)

#: Synthetic identity — never a patient study, never a real accession number.
STUDY_UID = "1.2.826.0.1.3680043.10.999.1"
SOP_UID = "1.2.826.0.1.3680043.10.999.1.1"
SERIES_UID = "1.2.826.0.1.3680043.10.999.1.2"
CINE_FRAMES = 3
CINE_SPACING = (0.5, 0.6)
LINEAR_MEASUREMENTS = (("LVEDD", 48.0), ("LVESD", 32.0))
MANUAL_BSA_M2 = 1.9
#: Durable entries the application is allowed to create in its data directory.
DATA_DIR_ALLOWLIST = {
    "measurements",
    "cache",
    "logs",
    "models",
    "preferences.ini",
    "server.ini",
    "secrets.ini",
    "device.key",
    "report_phrases.json",
}
#: Profile capabilities that the packaged bytes must show (A-16/A-11).
PROFILE_MODULES = {
    "full": {"onnxruntime": True, "pymupdf": True, "openpyxl": True},
    "presenter": {"onnxruntime": False, "pymupdf": False, "openpyxl": False},
}


class SmokeFailure(RuntimeError):
    """A check failed; the message is safe to print (no paths, no content)."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _current_profile() -> str:
    from echo_personal_tool.infrastructure import profile

    return "presenter" if profile.is_presenter() else "full"


def _write_synthetic_cine(path: Path) -> None:
    """Minimal uncompressed multi-frame ultrasound DICOM (synthetic only)."""
    import numpy as np
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, UltrasoundImageStorage

    path.parent.mkdir(parents=True, exist_ok=True)
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = UltrasoundImageStorage
    meta.MediaStorageSOPInstanceUID = SOP_UID  # type: ignore
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = UltrasoundImageStorage
    dataset.SOPInstanceUID = SOP_UID
    dataset.StudyInstanceUID = STUDY_UID
    dataset.SeriesInstanceUID = SERIES_UID
    dataset.Modality = "US"
    dataset.SeriesDescription = "Synthetic cine (package smoke)"
    dataset.PatientName = "SYNTHETIC^SMOKE"
    dataset.PatientID = "SMOKE-0001"
    dataset.StudyDate = "20260101"
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.Rows = 64
    dataset.Columns = 64
    dataset.BitsAllocated = 8
    dataset.BitsStored = 8
    dataset.HighBit = 7
    dataset.PixelRepresentation = 0
    dataset.NumberOfFrames = CINE_FRAMES
    dataset.PixelSpacing = [str(CINE_SPACING[0]), str(CINE_SPACING[1])]
    frames = [np.full((64, 64), 20 + index * 10, dtype=np.uint8).tobytes() for index in range(CINE_FRAMES)]
    dataset.PixelData = b"".join(frames)
    pydicom.dcmwrite(str(path), dataset, enforce_file_format=True)


def _measurements() -> tuple[LinearMeasurement, ...]:
    from echo_personal_tool.domain.models import LinearMeasurement

    return tuple(
        LinearMeasurement(label, 100.0, value, 0, (10.0, 20.0), (60.0, 20.0), SOP_UID)
        for label, value in LINEAR_MEASUREMENTS
    )


def _save_record(workdir: Path) -> dict:
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
    from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository

    repository = MeasurementRepository(workdir / "portable" / "measurements")
    try:
        data = StudyMeasurementData(linear_measurements=_measurements(), manual_bsa_m2=MANUAL_BSA_M2)
        sources = {SOP_UID: {"fingerprint": "a" * 64, "frames": CINE_FRAMES, "spacing": list(CINE_SPACING)}}
        record = repository.save(STUDY_UID, data, sources, expected_revision=0)
        reloaded = repository.load(STUDY_UID)
    finally:
        repository.close()
    if reloaded is None:
        raise SmokeFailure("saved record is not readable back from disk")
    return record


def _restore_record(workdir: Path) -> dict:
    from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository

    repository = MeasurementRepository(workdir / "portable" / "measurements")
    try:
        record = repository.load(STUDY_UID)
    finally:
        repository.close()
    if record is None:
        raise SmokeFailure("restart did not find the saved record")
    return record


def _snapshot_from(data: StudyMeasurementData) -> MeasurementSnapshot:
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot

    return MeasurementSnapshot(linear_measurements=tuple(data.linear_measurements))


def _export(workdir: Path, snapshot: MeasurementSnapshot) -> tuple[dict[str, Any], str]:
    """PDF export plus the text rendering the application shows and prints.

    The PDF is the file the product exports. The text report is what the
    overlay and the report sheet render; the application has no
    "save the results as .txt" feature, so the smoke does not invent one — it
    verifies the rendering (non-empty, stable across the restart, free of
    filesystem paths) and only the PDF reaches the disk.
    """
    from echo_personal_tool.domain.services.measurement_results_formatter import format_results_overlay
    from echo_personal_tool.domain.services.report_builder import PatientInfo, build_report_document
    from echo_personal_tool.infrastructure.measurement_report_pdf import export_report_document_pdf

    export_dir = workdir / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    text = format_results_overlay(snapshot)
    if not text.strip():
        raise SmokeFailure("text export is empty")

    document = build_report_document(
        snapshot,
        PatientInfo(name="SYNTHETIC^SMOKE", patient_id="SMOKE-0001", sex="m", height_cm=175, weight_kg=70),
    )
    if not document.has_measurements:
        raise SmokeFailure("PDF document has no measured values")
    pdf_path = export_dir / "report.pdf"
    export_report_document_pdf(document, pdf_path)
    header = pdf_path.read_bytes()[:5]
    if header != b"%PDF-":
        raise SmokeFailure("PDF export did not produce a PDF file")
    if pdf_path.stat().st_size < 1000:
        raise SmokeFailure("PDF export produced a suspiciously small file")

    text_bytes = text.encode("utf-8")
    pdf_sha, pdf_size = _digest(pdf_path)
    export = {
        "text": {
            "name": "results-overlay.txt",
            "sha256": hashlib.sha256(text_bytes).hexdigest(),
            "size": len(text_bytes),
            "lines": len(text.strip().splitlines()),
            "written": False,
        },
        "pdf": {"name": pdf_path.name, "sha256": pdf_sha, "size": pdf_size, "written": True},
    }
    return export, text


def _record_summary(record: dict) -> dict:
    data = record["data"]
    return {
        "study_uid": record["study_uid"],
        "revision": int(record["revision"]),
        "measurements": [
            {"label": item.label, "millimeter_length": item.millimeter_length} for item in data.linear_measurements
        ],
        "manual_bsa_m2": data.manual_bsa_m2,
    }


def _check_profile(profile: str) -> list[dict]:
    checks: list[dict] = []
    from echo_personal_tool.infrastructure import profile as profile_module

    actual = _current_profile()
    checks.append({"name": "profile", "ok": actual == profile, "detail": f"running profile {actual}"})
    for module, expected in PROFILE_MODULES[profile].items():
        available = _module_available(module)
        checks.append(
            {
                "name": f"capability:{module}",
                "ok": available is expected,
                "detail": f"{module} {'present' if available else 'absent'}",
            }
        )
    checks.append(
        {
            "name": "reference_ui",
            "ok": profile_module.has_reference_ui() is (profile == "full"),
            "detail": f"reference UI {'available' if profile_module.has_reference_ui() else 'hidden'}",
        }
    )
    return checks


def _check_storage(workdir: Path) -> list[dict]:
    from echo_personal_tool.infrastructure import paths

    expected_root = (workdir / "portable").resolve()
    data_dir = paths.data_dir().resolve()
    checks = [
        {
            "name": "portable_storage",
            "ok": data_dir == expected_root,
            "detail": "data directory is the portable root handed to the smoke",
        }
    ]
    measurements = data_dir / "measurements"
    leftovers = (
        sorted(path.name for path in measurements.glob(".pending-*.tmp") if path.is_file())
        if measurements.is_dir()
        else []
    )
    checks.append(
        {
            "name": "no_temporary_leftovers",
            "ok": not leftovers,
            "detail": "no half-written record files" if not leftovers else f"{len(leftovers)} temp file(s) left",
        }
    )
    unknown = []
    if data_dir.is_dir():
        for entry in data_dir.iterdir():
            if entry.name not in DATA_DIR_ALLOWLIST:
                unknown.append(entry.name)
    checks.append(
        {
            "name": "storage_allowlist",
            "ok": not unknown,
            "detail": "only allowlisted data directories/files were created"
            if not unknown
            else f"unexpected entries: {', '.join(sorted(unknown))}",
        }
    )
    return checks


def _check_no_paths_leak(text: str, workdir: Path) -> dict:
    """The exported text must not gain filesystem paths from the smoke itself."""
    leaked = str(workdir) in text or str(workdir.resolve()) in text
    return {
        "name": "export_has_no_paths",
        "ok": not leaked,
        "detail": "exported text contains no filesystem path",
    }


def run(stage: str, workdir: Path, expect_profile: str | None = None, expect_manifest: Path | None = None) -> dict:
    """Execute one stage and return its manifest (also written by the CLI)."""
    if stage not in STAGES:
        raise SmokeFailure(f"unknown stage {stage!r}")
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    profile = expect_profile or _current_profile()

    from echo_personal_tool import __version__

    checks = _check_profile(profile)
    cine_path = workdir / "input" / "synthetic-cine.dcm"
    if stage == STAGE_SAVE:
        _write_synthetic_cine(cine_path)

    import pydicom

    if not cine_path.is_file():
        raise SmokeFailure("the synthetic cine of the first launch is missing")
    try:
        dataset = pydicom.dcmread(str(cine_path), force=False)
    except Exception:  # noqa: BLE001 - a corrupt cine is a smoke failure, not a traceback
        raise SmokeFailure("the synthetic cine is not readable") from None
    frames = int(getattr(dataset, "NumberOfFrames", 0) or 1)
    spacing = tuple(float(value) for value in (dataset.PixelSpacing or ()))
    checks.append(
        {
            "name": "synthetic_cine",
            "ok": frames == CINE_FRAMES and spacing == CINE_SPACING,
            "detail": f"{frames} frame(s), spacing {spacing}",
        }
    )

    if stage == STAGE_SAVE:
        record = _save_record(workdir)
    else:
        record = _restore_record(workdir)
    summary = _record_summary(record)
    expected_labels = [label for label, _ in LINEAR_MEASUREMENTS]
    checks.append(
        {
            "name": "measurements_round_trip",
            "ok": [item["label"] for item in summary["measurements"]] == expected_labels
            and summary["manual_bsa_m2"] == MANUAL_BSA_M2,
            "detail": f"revision {summary['revision']}, {len(summary['measurements'])} measurement(s)",
        }
    )
    if stage == STAGE_RESTART:
        checks.append(
            {
                "name": "restart_kept_revision",
                "ok": summary["revision"] == 1,
                "detail": "restart did not rewrite the record",
            }
        )

    export, rendered_text = _export(workdir, _snapshot_from(record["data"]))
    checks.append(
        {
            "name": "text_export",
            "ok": export["text"]["lines"] >= 1 and export["text"]["size"] > 0,
            "detail": f"{export['text']['lines']} line(s) rendered for the overlay and the report sheet",
        }
    )
    checks.append({"name": "pdf_export", "ok": export["pdf"]["size"] >= 1000, "detail": "report.pdf written"})
    checks.extend(_check_storage(workdir))
    checks.append(_check_no_paths_leak(rendered_text, workdir))

    if stage == STAGE_RESTART and expect_manifest is not None:
        previous = json.loads(Path(expect_manifest).read_text(encoding="utf-8"))
        same_text = previous.get("export", {}).get("text", {}).get("sha256") == export["text"]["sha256"]
        checks.append(
            {
                "name": "restored_text_identical",
                "ok": same_text,
                "detail": "the restored record renders the same text report",
            }
        )
        checks.append(
            {
                "name": "restart_same_build",
                "ok": previous.get("version") == __version__ and previous.get("profile") == _current_profile(),
                "detail": "both stages ran the same version and profile",
            }
        )

    manifest = {
        "schema": SCHEMA,
        "kind": KIND,
        "stage": stage,
        "created_at": _utc_now(),
        # Identity of the process that ran this stage: the restart claim is only
        # honest when the two manifests come from two processes.
        "process": {"pid": os.getpid()},
        "ok": all(check["ok"] for check in checks),
        "version": __version__,
        "profile": _current_profile(),
        "expected_profile": profile,
        "python": platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable_name": Path(sys.executable).name,
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "record": summary,
        "export": export,
        "data_dir": "portable",
        "checks": checks,
    }
    return manifest


def compare(save_manifest: dict, restart_manifest: dict) -> list[dict]:
    """Cross-stage checks — what "restart restored the saved work" means."""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    for label, manifest in (("save", save_manifest), ("restart", restart_manifest)):
        add(
            f"{label}_ok",
            bool(manifest.get("ok")),
            f"stage {label} reported {'ok' if manifest.get('ok') else 'failure'}",
        )
        add(
            f"{label}_stage",
            manifest.get("stage") == label,
            f"manifest stage is {manifest.get('stage')!r}",
        )
    add(
        "same_build",
        save_manifest.get("version") == restart_manifest.get("version")
        and save_manifest.get("profile") == restart_manifest.get("profile")
        and save_manifest.get("platform") == restart_manifest.get("platform"),
        "both stages ran the same version, profile and platform",
    )
    add(
        "record_identity",
        save_manifest.get("record") == restart_manifest.get("record"),
        "the restored record carries the saved measurements and revision",
    )
    add(
        "same_text_export",
        save_manifest.get("export", {}).get("text", {}).get("sha256")
        == restart_manifest.get("export", {}).get("text", {}).get("sha256"),
        "the restored record renders the same text report",
    )
    add(
        "pdf_exported_again",
        (restart_manifest.get("export", {}).get("pdf", {}).get("size") or 0) >= 1000,
        "the restart stage exported a PDF",
    )
    return checks


def _write_json(payload: dict, path: Path | None) -> None:
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for stage in STAGES:
        stage_parser = subparsers.add_parser(stage, help=f"run the {stage} stage")
        stage_parser.add_argument("--workdir", type=Path, required=True)
        stage_parser.add_argument("--expect-profile", choices=("full", "presenter"), default=None)
        stage_parser.add_argument("--json", type=Path, default=None)
        stage_parser.add_argument("--expect", type=Path, default=None, help="stage-1 manifest (restart only)")

    compare_parser = subparsers.add_parser("compare", help="compare the two stage manifests")
    compare_parser.add_argument("save", type=Path)
    compare_parser.add_argument("restart", type=Path)
    compare_parser.add_argument("--json", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.command == "compare":
        try:
            save_manifest = json.loads(Path(args.save).read_text(encoding="utf-8"))
            restart_manifest = json.loads(Path(args.restart).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"package_smoke: cannot read stage manifests ({type(exc).__name__})", file=sys.stderr)
            return 1
        checks = compare(save_manifest, restart_manifest)
        payload = {
            "schema": SCHEMA,
            "kind": f"{KIND}.comparison",
            "ok": all(check["ok"] for check in checks),
            "checks": checks,
        }
        _write_json(payload, args.json)
        for check in checks:
            print(f"[{'PASS' if check['ok'] else 'FAIL'}] {check['name']}: {check['detail']}")
        print("RESULT: " + ("PASS" if payload["ok"] else "FAIL"))
        return 0 if payload["ok"] else 1

    try:
        manifest = run(
            args.command,
            args.workdir,
            expect_profile=args.expect_profile,
            expect_manifest=args.expect,
        )
    except SmokeFailure as exc:
        print(f"package_smoke: {exc}", file=sys.stderr)
        return 1
    _write_json(manifest, args.json)
    for check in manifest["checks"]:
        print(f"[{'PASS' if check['ok'] else 'FAIL'}] {check['name']}: {check['detail']}")
    print(
        f"package smoke {manifest['stage']}: {'PASS' if manifest['ok'] else 'FAIL'} "
        f"({manifest['version']} {manifest['profile']} {manifest['platform']['system']})"
    )
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
