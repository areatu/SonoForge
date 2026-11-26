#!/usr/bin/env python3
"""Offline ML.6 collection/transfer CLI. Packages contain PHI; no upload support."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from echo_personal_tool.application.ml_workbench import LocalMLWorkbench, configure_collection  # noqa: E402
from echo_personal_tool.domain.models.training_archive import ArchiveWriteError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--acknowledge-local-phi", required=True, action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for command in ("export", "import", "export-key", "initialize-key", "report"):
        p = sub.add_parser(command)
        p.add_argument("path", type=Path)
    config = sub.add_parser("configure")
    config.add_argument("--enable", action="store_true", help="Without this flag collection is disabled")
    config.add_argument("--quota-mib", type=int, default=4096)
    args = parser.parse_args(argv)
    try:
        bench = LocalMLWorkbench(args.workspace)
        if args.command == "status":
            result = bench.inventory()["report"]
        elif args.command == "configure":
            configure_collection(enabled=args.enable, directory=args.workspace, quota_bytes=args.quota_mib * 1024**2)
            result = {"saved": True, "restart_required": True}
        else:
            actions = {
                "export": bench.export_material,
                "import": bench.import_material,
                "export-key": bench.export_identity,
                "initialize-key": bench.import_identity,
                "report": bench.export_report,
            }
            actions[args.command](args.path)
            result = {"completed": True, "model_activated": False}
    except (OSError, ValueError, KeyError, TypeError, ArchiveWriteError):
        sys.stderr.write("Local ML operation failed; inspect local settings, integrity and available space.\n")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
