"""Print the version a distribution is pinned to in ``uv.lock``.

``uv.lock`` is the single source of truth for the toolchain (QH-2a.1).  Jobs
that cannot afford a full ``uv sync`` (lint, coverage combine) still install
their one tool at the locked version instead of a floating ``pip install``::

    pip install "ruff==$(python .github/scripts/locked_version.py ruff)"

The script fails loudly when the distribution is absent from the lock, so a
typo cannot silently fall back to "latest".

A marker-dependent pin (S3-02 / #311: numpy resolves to 2.4.6 below Python
3.12 and 2.5.4 from it) is resolved for the interpreter that will install it —
by default the running one, exactly what ``pip install`` targets, or the
explicit ``--python-version`` for cross-picks.  Each candidate's
``resolution-markers`` are evaluated for that Python on this platform and
exactly one candidate must remain; anything else fails loudly with the
ambiguous set listed.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import sys
from pathlib import Path

import tomllib

# Marker variables the evaluator knows.  Values are compared as versions for
# the python_* keys and as plain strings everywhere else.
_VERSION_VARS = frozenset({"python_full_version", "python_version"})
_KNOWN_VARS = _VERSION_VARS | frozenset(
    {
        "sys_platform",
        "platform_machine",
        "platform_system",
        "os_name",
        "implementation_name",
    }
)

_TOKEN_RE = re.compile(r"\s*(\(|\)|\b(?:and|or)\b|==|!=|<=|>=|<|>|[A-Za-z_][A-Za-z0-9_]*|'[^']*')")


class MarkerError(ValueError):
    """A resolution marker could not be evaluated against the target env."""


def _version_key(value: str) -> tuple[object, ...]:
    """Order ``'3.11.9'``/``'3.12'`` numerically, not lexically."""
    parts: list[object] = []
    for part in value.split("."):
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part)
    return tuple(parts)


def _compare(left: str, op: str, right: str, *, as_version: bool) -> bool:
    if as_version:
        lhs: object = _version_key(left)
        rhs: object = _version_key(right)
        if any(isinstance(a, int) != isinstance(b, int) for a, b in zip(lhs, rhs)):
            # Mixed numeric/non-numeric components cannot be ordered safely.
            raise MarkerError(f"cannot compare {left!r} {op} {right!r}")
    else:
        lhs, rhs = left, right
    if op == "==":
        return lhs == rhs
    if op == "!=":
        return lhs != rhs
    if op == "<":
        return lhs < rhs  # type: ignore[operator]
    if op == "<=":
        return lhs <= rhs  # type: ignore[operator]
    if op == ">":
        return lhs > rhs  # type: ignore[operator]
    if op == ">=":
        return lhs >= rhs  # type: ignore[operator]
    raise MarkerError(f"unknown operator {op!r}")


def _tokenize(marker: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    while pos < len(marker):
        match = _TOKEN_RE.match(marker, pos)
        if not match or match.end() == pos:
            raise MarkerError(f"cannot tokenise {marker!r} at offset {pos}")
        tokens.append(match.group(1))
        pos = match.end()
    return tokens


def marker_applies(marker: str, env: dict[str, str]) -> bool:
    """Evaluate a PEP 508-style marker subset against *env* (no extras/sets)."""
    tokens = _tokenize(marker.strip())
    pos = 0

    def parse_or() -> bool:
        nonlocal pos
        value = parse_and()
        while pos < len(tokens) and tokens[pos] == "or":
            pos += 1
            right = parse_and()
            value = value or right
        return value

    def parse_and() -> bool:
        nonlocal pos
        value = parse_atom()
        while pos < len(tokens) and tokens[pos] == "and":
            pos += 1
            right = parse_atom()
            value = value and right
        return value

    def parse_atom() -> bool:
        nonlocal pos
        if pos >= len(tokens):
            raise MarkerError(f"unexpected end of marker {marker!r}")
        token = tokens[pos]
        if token == "(":
            pos += 1
            value = parse_or()
            if pos >= len(tokens) or tokens[pos] != ")":
                raise MarkerError(f"unbalanced parenthesis in {marker!r}")
            pos += 1
            return value
        if pos + 2 >= len(tokens):
            raise MarkerError(f"incomplete comparison in {marker!r} at token {pos}")
        name, op, raw = tokens[pos], tokens[pos + 1], tokens[pos + 2]
        if name not in _KNOWN_VARS:
            raise MarkerError(f"unknown marker variable {name!r} in {marker!r}")
        if op not in ("==", "!=", "<=", ">=", "<", ">"):
            raise MarkerError(f"expected comparison operator, got {op!r} in {marker!r}")
        if not (raw.startswith("'") and raw.endswith("'") and len(raw) >= 2):
            raise MarkerError(f"expected quoted value, got {raw!r} in {marker!r}")
        pos += 3
        return compare_marker_var(name, op, raw[1:-1], env)

    result = parse_or()
    if pos != len(tokens):
        raise MarkerError(f"trailing tokens in {marker!r}: {tokens[pos:]}")
    return result


def compare_marker_var(name: str, op: str, value: str, env: dict[str, str]) -> bool:
    if name not in env:
        raise MarkerError(f"no value for marker variable {name!r}")
    return _compare(env[name], op, value, as_version=name in _VERSION_VARS)


def target_env(python_version: str) -> dict[str, str]:
    """The marker environment for *python_version* on this machine."""
    return {
        "python_full_version": python_version,
        "python_version": ".".join(python_version.split(".")[:2]),
        "sys_platform": sys.platform,
        "platform_machine": platform.machine(),
        "platform_system": platform.system(),
        "os_name": os.name,
        "implementation_name": sys.implementation.name,
    }


def locked_versions(lock_path: Path, name: str) -> list[str]:
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    wanted = name.lower().replace("_", "-")
    return sorted({pkg["version"] for pkg in data.get("package", []) if pkg.get("name", "").lower() == wanted})


def _candidates(lock_path: Path, name: str) -> list[tuple[str, list[str]]]:
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    wanted = name.lower().replace("_", "-")
    found: list[tuple[str, list[str]]] = []
    for pkg in data.get("package", []):
        if pkg.get("name", "").lower() == wanted and pkg.get("version"):
            markers = [str(item) for item in pkg.get("resolution-markers") or []]
            found.append((str(pkg["version"]), markers))
    return found


def _select_for_python(candidates: list[tuple[str, list[str]]], python_version: str) -> str:
    env = target_env(python_version)
    applicable: list[str] = []
    for version, markers in candidates:
        # An entry without resolution-markers cannot be excluded — keep it
        # and let the ambiguity check below fail loudly if it matters.
        if not markers or any(marker_applies(marker, env) for marker in markers):
            applicable.append(version)
    if len(applicable) == 1:
        return applicable[0]
    raise MarkerError(
        f"python {python_version} on this platform matches {sorted(applicable) or 'nothing'}; "
        f"all candidates: {sorted({version for version, _ in candidates})}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="distribution name as it appears on PyPI, e.g. ruff")
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"), help="path to uv.lock (default: ./uv.lock)")
    parser.add_argument(
        "--python-version",
        metavar="X.Y[.Z]",
        help="select a marker-dependent pin for this Python (default: the running interpreter)",
    )
    args = parser.parse_args(argv)

    try:
        versions = locked_versions(args.lock, args.name)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"locked_version: cannot read {args.lock}: {exc}", file=sys.stderr)
        return 1
    if not versions:
        print(f"locked_version: {args.name!r} is not pinned in {args.lock}", file=sys.stderr)
        return 1
    if len(versions) == 1:
        print(versions[0])
        return 0

    python_version = args.python_version or f"{sys.version_info.major}.{sys.version_info.minor}"
    try:
        selected = _select_for_python(_candidates(args.lock, args.name), python_version)
    except MarkerError as exc:
        print(
            f"locked_version: {args.name!r} resolves to several versions in {args.lock} "
            f"({', '.join(versions)}); selection for python {python_version} failed: {exc}",
            file=sys.stderr,
        )
        return 1
    print(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
