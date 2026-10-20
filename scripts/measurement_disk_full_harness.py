"""Opt-in native ENOSPC exercise on an EMPTY, small, disposable mounted volume.

Never point this at a profile/cache or ordinary filesystem. See
 docs/reviews/2026-10-16-qh-1c-remap-faults-ru.md for an isolated tmpfs recipe.
No injected OSError, no repository quota: the OS must actually return ENOSPC.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_VOLUME_BYTES = 128 * 1024 * 1024


def _windows_volume_root(volume: Path) -> str:
    """Return the volume root containing ``volume`` using the native Win32 API."""
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    get_volume_path = ctypes.windll.kernel32.GetVolumePathNameW
    get_volume_path.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_wchar), ctypes.c_uint32)
    get_volume_path.restype = ctypes.c_int
    if not get_volume_path(str(volume), buffer, len(buffer)):
        raise OSError("volume_root_probe_failed")
    return buffer.value


def _is_mount_root(volume: Path) -> bool:
    if sys.platform != "win32":
        return volume.is_mount()
    # pathlib.Path.is_mount() is unavailable on the supported Python 3.10/3.11
    # Windows builds.  GetVolumePathNameW lets us prove this path is the root
    # of a mounted volume (e.g. X:\\), not an ordinary directory on C:.
    root = _windows_volume_root(volume)
    return os.path.normcase(os.path.abspath(str(volume))).rstrip("\\\\/") == os.path.normcase(
        os.path.abspath(root)
    ).rstrip("\\\\/")


def _only_os_volume_metadata(volume: Path) -> bool:
    """Allow only known OS-created metadata folders at a freshly mounted root."""
    names = {
        "win32": {"system volume information", "$recycle.bin"},
        "darwin": {".fseventsd", ".spotlight-v100", ".trashes", ".temporaryitems"},
    }.get(sys.platform, set())
    for entry in volume.iterdir():
        if entry.name.casefold() not in names or entry.is_symlink() or not entry.is_dir():
            return False
    return True


def validate_volume(volume: Path, confirmed: bool) -> None:
    if not confirmed:
        raise ValueError("explicit_disposable_volume_confirmation_required")
    if volume.is_symlink() or not volume.is_dir():
        raise ValueError("dedicated_mount_required")
    try:
        mounted = _is_mount_root(volume)
    except (NotImplementedError, OSError) as exc:
        # Unsupported/failed mount probes fail closed; never downgrade to an
        # unchecked ordinary directory, especially on Windows.
        raise ValueError("dedicated_mount_required") from exc
    if not mounted:
        raise ValueError("dedicated_mount_required")
    resolved = volume.resolve()
    # ``volume.resolve() == Path(volume.anchor)`` never holds on Windows:
    # ``Path("/").anchor`` is ``"\\"`` (drive-less) while ``resolve()`` yields
    # the current drive root (e.g. ``C:\\``).  ``parent == self`` detects a
    # filesystem root on every supported platform.
    is_filesystem_root = resolved.parent == resolved
    if is_filesystem_root:
        if sys.platform != "win32":
            raise ValueError("empty_non_root_mount_required")
        system_drive = os.environ.get("SystemDrive", "")
        volume_drive = os.path.splitdrive(str(resolved))[0]
        if not system_drive or os.path.normcase(volume_drive) == os.path.normcase(system_drive):
            raise ValueError("empty_non_root_mount_required")
    if not _only_os_volume_metadata(volume):
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
