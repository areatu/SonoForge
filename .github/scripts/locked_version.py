"""Print the version a distribution is pinned to in ``uv.lock``.

``uv.lock`` is the single source of truth for the toolchain (QH-2a.1).  Jobs
that cannot afford a full ``uv sync`` (lint, coverage combine) still install
their one tool at the locked version instead of a floating ``pip install``::

    pip install "ruff==$(python .github/scripts/locked_version.py ruff)"

The script fails loudly when the distribution is absent from the lock or when
it resolves to several versions (marker-dependent pins such as onnxruntime),
so a typo cannot silently fall back to "latest".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    print("locked_version.py needs Python 3.11+ (tomllib)", file=sys.stderr)
    raise SystemExit(2)


def locked_versions(lock_path: Path, name: str) -> list[str]:
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    wanted = name.lower().replace("_", "-")
    return sorted({pkg["version"] for pkg in data.get("package", []) if pkg.get("name", "").lower() == wanted})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="distribution name as it appears on PyPI, e.g. ruff")
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"), help="path to uv.lock (default: ./uv.lock)")
    args = parser.parse_args(argv)

    try:
        versions = locked_versions(args.lock, args.name)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"locked_version: cannot read {args.lock}: {exc}", file=sys.stderr)
        return 1
    if not versions:
        print(f"locked_version: {args.name!r} is not pinned in {args.lock}", file=sys.stderr)
        return 1
    if len(versions) > 1:
        print(
            f"locked_version: {args.name!r} resolves to several versions in {args.lock}: {', '.join(versions)}; "
            "the pin is marker-dependent and must be chosen explicitly",
            file=sys.stderr,
        )
        return 1
    print(versions[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
