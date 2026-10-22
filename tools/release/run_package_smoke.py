#!/usr/bin/env python3
"""Run the packaged-artifact smoke in two processes and collect the evidence.

`echo_personal_tool.application.package_smoke` contains the scenario; this
runner is what the workflows call. It launches the same command three times —
stage ``save``, stage ``restart`` (a fresh process, which is the point) and
``compare`` — against one of three runners:

``artifact``  the shipped executable: ``<artifact> --package-smoke <stage> …``.
              Used for the Windows onedir/onefile builds, the macOS ``.app``
              binary and the Presenter AppImage, i.e. the bytes users download.
``payload``   the payload of an installed package (lite ``.deb``) executed with
              the locked interpreter: the files come from the package, not from
              the checkout, but the dependency bootstrap of the lite package is
              not exercised (declared gap, see the package matrix).
``module``    the checkout itself — the required CI job that keeps the smoke
              scenario honest without waiting for a full package build.

The evidence JSON is what ``tools/release/build_record.py`` records as the
``smoke`` block and what ``verify_release.py`` requires to be ``pass``.

CLI::

    python tools/release/run_package_smoke.py --runner artifact \\
        --artifact dist/SonoForge/SonoForge.exe --profile full \\
        --workdir package-smoke --evidence dist/package-smoke-full-windows-x64.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
KIND = "sonoforge.package-smoke-evidence"
RUNNERS = ("artifact", "payload", "module")
SMOKE_MODULE = "echo_personal_tool.application.package_smoke"


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _base_env(workdir: Path, payload_root: Path | None, profile: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "SONOFORGE_PORTABLE": "1",
            "SONOFORGE_PORTABLE_DIR": str((workdir / "portable").resolve()),
        }
    )
    if profile == "presenter":
        env["SONOFORGE_PROFILE"] = "presenter"
    if payload_root is not None:
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(payload_root) + (os.pathsep + existing if existing else "")
    return env


def _command(
    stage: str,
    *,
    runner: str,
    artifact: Path | None,
    interpreter: str,
    workdir: Path,
    profile: str,
    expect: Path | None,
    output: Path,
) -> list[str]:
    if runner == "artifact":
        assert artifact is not None
        command = [str(artifact), "--package-smoke", stage]
    else:
        command = [interpreter, "-m", SMOKE_MODULE, stage]
    command += ["--workdir", str(workdir), "--expect-profile", profile, "--json", str(output)]
    if expect is not None:
        command += ["--expect", str(expect)]
    return command


def _compare_command(
    *,
    runner: str,
    artifact: Path | None,
    interpreter: str,
    save: Path,
    restart: Path,
    output: Path,
) -> list[str]:
    if runner == "artifact":
        assert artifact is not None
        return [str(artifact), "--package-smoke", "compare", str(save), str(restart), "--json", str(output)]
    return [interpreter, "-m", SMOKE_MODULE, "compare", str(save), str(restart), "--json", str(output)]


def _run(command: list[str], env: dict[str, str], timeout: int, label: str) -> None:
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout, check=False)
    except OSError as exc:
        # The artifact exists but the OS refuses to execute it (wrong format,
        # missing loader, no permission). That is a failed smoke, not a crash of
        # the runner: Windows reports WinError 193 for a non-PE file here.
        reason = getattr(exc, "strerror", None) or exc.__class__.__name__
        raise SystemExit(f"package smoke {label} failed (could not start the artifact: {reason})") from None
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-15:])
        raise SystemExit(f"package smoke {label} failed (exit {result.returncode})" + (f"\n{tail}" if tail else ""))


def run(
    *,
    runner: str,
    profile: str,
    workdir: Path,
    artifact: Path | None = None,
    payload_root: Path | None = None,
    interpreter: str = sys.executable,
    timeout: int = 600,
    evidence: Path | None = None,
) -> dict:
    workdir = Path(workdir)
    if workdir.exists():
        for path in sorted(workdir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
    workdir.mkdir(parents=True, exist_ok=True)

    if runner == "artifact" and (artifact is None or not Path(artifact).is_file()):
        raise SystemExit(f"--artifact is required for the artifact runner: {artifact}")
    if runner == "payload" and (payload_root is None or not Path(payload_root).is_dir()):
        raise SystemExit(f"--payload-root is required for the payload runner: {payload_root}")

    env = _base_env(workdir, Path(payload_root) if payload_root else None, profile)
    save_json = workdir / "stage-save.json"
    restart_json = workdir / "stage-restart.json"
    compare_json = workdir / "comparison.json"

    _run(
        _command(
            "save",
            runner=runner,
            artifact=Path(artifact) if artifact else None,
            interpreter=interpreter,
            workdir=workdir,
            profile=profile,
            expect=None,
            output=save_json,
        ),
        env,
        timeout,
        "save",
    )
    _run(
        _command(
            "restart",
            runner=runner,
            artifact=Path(artifact) if artifact else None,
            interpreter=interpreter,
            workdir=workdir,
            profile=profile,
            expect=save_json,
            output=restart_json,
        ),
        env,
        timeout,
        "restart",
    )
    _run(
        _compare_command(
            runner=runner,
            artifact=Path(artifact) if artifact else None,
            interpreter=interpreter,
            save=save_json,
            restart=restart_json,
            output=compare_json,
        ),
        env,
        timeout,
        "compare",
    )

    save_manifest = json.loads(save_json.read_text(encoding="utf-8"))
    restart_manifest = json.loads(restart_json.read_text(encoding="utf-8"))
    comparison = json.loads(compare_json.read_text(encoding="utf-8"))
    # Only the runner knows whether the two stages were really two processes; the
    # comparison of the manifests cannot tell.
    process_checks = [
        {
            "name": "different_process",
            "ok": (save_manifest.get("process") or {}).get("pid") != (restart_manifest.get("process") or {}).get("pid"),
            "detail": f"save pid {(save_manifest.get('process') or {}).get('pid')}, "
            f"restart pid {(restart_manifest.get('process') or {}).get('pid')}",
        }
    ]
    artifact_info = None
    if artifact is not None and Path(artifact).is_file():
        digest, size = _digest(Path(artifact))
        artifact_info = {"name": Path(artifact).name, "sha256": digest, "size": size}

    payload = {
        "schema": SCHEMA,
        "kind": KIND,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": bool(
            comparison.get("ok")
            and save_manifest.get("ok")
            and restart_manifest.get("ok")
            and all(check["ok"] for check in process_checks)
        ),
        "runner": runner,
        "profile": profile,
        "artifact": artifact_info,
        "payload_root": Path(payload_root).name if payload_root else None,
        "stages": {"save": save_manifest, "restart": restart_manifest},
        "comparison": comparison,
        "runner_checks": process_checks,
    }
    if evidence is not None:
        evidence = Path(evidence)
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runner", choices=RUNNERS, default="module")
    parser.add_argument("--artifact", type=Path, default=None, help="shipped executable (artifact runner)")
    parser.add_argument("--payload-root", type=Path, default=None, help="package payload root (payload runner)")
    parser.add_argument("--profile", choices=("full", "presenter"), default="full")
    parser.add_argument("--workdir", type=Path, default=Path("package-smoke"), help="scratch directory")
    parser.add_argument("--interpreter", default=sys.executable, help="interpreter for module/payload runners")
    parser.add_argument("--timeout", type=int, default=600, help="seconds per subprocess")
    parser.add_argument("--evidence", type=Path, default=None, help="write the evidence JSON here")
    args = parser.parse_args(argv)

    payload = run(
        runner=args.runner,
        profile=args.profile,
        workdir=args.workdir,
        artifact=args.artifact,
        payload_root=args.payload_root,
        interpreter=args.interpreter,
        timeout=args.timeout,
        evidence=args.evidence,
    )
    print(
        f"package smoke evidence: {'PASS' if payload['ok'] else 'FAIL'} "
        f"({payload['runner']}, {payload['profile']}, artifact={payload['artifact']['name'] if payload['artifact'] else 'n/a'})"
    )
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
