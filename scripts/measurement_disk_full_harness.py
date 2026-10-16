"""Opt-in native ENOSPC exercise on an EMPTY, small, disposable mounted volume.

Never point this at a profile/cache or ordinary filesystem. See
 docs/reviews/2026-10-16-qh-1c-remap-faults-ru.md for an isolated tmpfs recipe.
No injected OSError, no repository quota: the OS must actually return ENOSPC.
"""

from __future__ import annotations

import argparse
import errno
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_VOLUME_BYTES = 128 * 1024 * 1024


def validate_volume(volume: Path, confirmed: bool) -> None:
    if not confirmed:
        raise ValueError("explicit_disposable_volume_confirmation_required")
    if volume.is_symlink() or not volume.is_dir():
        raise ValueError("dedicated_mount_required")
    try:
        mounted = volume.is_mount()
    except NotImplementedError as exc:
        # Python 3.10/3.11 WindowsPath cannot check mount points. Fail closed:
        # never treat an unchecked directory as a disposable bounded volume.
        raise ValueError("dedicated_mount_required") from exc
    if not mounted:
        raise ValueError("dedicated_mount_required")
    if volume.resolve() == Path(volume.anchor) or any(volume.iterdir()):
        raise ValueError("empty_non_root_mount_required")
    if not 0 < shutil.disk_usage(volume).total <= MAX_VOLUME_BYTES:
        raise ValueError("volume_exceeds_128_mib_safety_limit")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def exercise(volume: Path, *, confirmed: bool = False) -> dict:
    validate_volume(volume, confirmed)
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
    from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository

    uid = "1.2.826.0.1.3680043.10.999.1"
    with tempfile.TemporaryDirectory(prefix="sonoforge-fault-", dir=volume) as directory:
        root = Path(directory)
        repo = MeasurementRepository(root / "records")
        filler = root / "filler.bin"
        try:
            initial = StudyMeasurementData(height_cm=170.0, height_source="manual")
            changed = StudyMeasurementData(height_cm=180.0, height_source="manual")
            first = repo.save(uid, initial, {}, 0)
            before = repo.entries()[0].read_bytes()
            filled = 0
            with filler.open("wb", buffering=0) as file:
                try:
                    while filled <= MAX_VOLUME_BYTES:
                        written = file.write(b"\0" * 4096)
                        require(bool(written), "zero_length_fill_write")
                        filled += written
                    raise RuntimeError("fill_safety_limit_reached")
                except OSError as exc:
                    require(exc.errno == errno.ENOSPC, "fill_did_not_return_enospc")
            try:
                repo.save(uid, changed, {}, first["revision"])
            except OSError as exc:
                require(exc.errno == errno.ENOSPC, "save_did_not_return_enospc")
            else:
                raise RuntimeError("save_unexpectedly_acknowledged_on_full_volume")
            require(repo.entries()[0].read_bytes() == before, "committed_bytes_changed")
            require(not list(repo.root.glob(".pending-*")), "temporary_file_leaked")
            filler.unlink()
            retry = repo.save(uid, changed, {}, first["revision"])
            require(retry["revision"] == 2, "retry_revision_mismatch")
            repo.close()
            # A new process, not the writer's in-memory record, proves reopen.
            code = (
                "import sys; from pathlib import Path; "
                "from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository; "
                "r=MeasurementRepository(Path(sys.argv[1])); d=r.load(sys.argv[2]); "
                "sys.exit(0 if d['revision']==2 and d['data'].height_cm==180.0 else 1)"
            )
            result = subprocess.run(
                [sys.executable, "-c", code, str(repo.root), uid],
                capture_output=True,
                timeout=30,
                check=False,
            )
            require(result.returncode == 0, "fresh_process_restore_failed")
            return {
                "status": "PASS",
                "platform": sys.platform,
                "failure": "ENOSPC",
                "failed_write_acknowledged": False,
                "old_bytes_intact": True,
                "pending_files": 0,
                "retry_revision": 2,
                "fresh_process_restore": True,
                "filled_bytes": filled,
            }
        finally:
            repo.close()
            filler.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume", type=Path, required=True)
    parser.add_argument("--confirm-disposable-volume", action="store_true")
    args = parser.parse_args()
    try:
        report = exercise(args.volume, confirmed=args.confirm_disposable_volume)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        # No volume paths or OS exception messages in the report.
        report = {"status": "FAIL", "error_type": type(exc).__name__}
    print(json.dumps(report, sort_keys=True))  # noqa: T201 - CLI evidence
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
