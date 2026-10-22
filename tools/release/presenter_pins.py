#!/usr/bin/env python3
"""Keep the Presenter's lite dependency list provably inside ``uv.lock``.

`QH-5a` slice 1 (spec §9.1): one locked dependency policy for CI, build, release
*and* the Presenter profile. The Presenter ships a *second* dependency list,
``build/presenter/pinned-packages.txt``, because the lite build must not contain
ONNX Runtime, PyMuPDF, openpyxl or the WebEngine stack. A second list is only
acceptable while it provably belongs to the one lock, so this tool derives the
lite set from ``uv.lock`` and checks the file against it:

* the set of pinned packages must equal the project's dependency closure with the
  excluded packages removed and the PySide6 metapackage replaced by
  ``pyside6-essentials`` — **including transitive dependencies**, so the lite
  build has no floating resolution of its own;
* every pin must carry the exact version ``uv.lock`` resolves for the Presenter
  build environment (CPython 3.11 on Linux x86_64 / Windows x64); a lock that
  splits a resolution by marker is evaluated for that environment instead of
  being guessed;
* the packages the profile is defined by *excluding* must be absent, and
  ``pyside6-essentials`` must be present.

``--write`` regenerates the pin body from the lock (the header comment is kept);
CI runs the default check mode and fails on any drift.

CLI::

    python tools/release/presenter_pins.py            # check (CI, build jobs)
    python tools/release/presenter_pins.py --write    # refresh after a lock bump
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - the project requires >=3.11
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PINS = REPO_ROOT / "build" / "presenter" / "pinned-packages.txt"
DEFAULT_LOCK = REPO_ROOT / "uv.lock"
PROJECT_NAME = "sonoforge"
PRESENTER_EXTRAS = ("presenter",)

# Packages the lite profile is defined by *not* shipping. If one of these
# reappears in the pin list the Presenter silently becomes the full product.
EXCLUDED = ("onnxruntime", "pymupdf", "fitz", "openpyxl", "pyside6", "pyside6-addons")
# ``pyside6`` is the metapackage that pulls ``pyside6-addons``; the lite profile
# pins the essentials distribution instead.
SUBSTITUTIONS = {"pyside6": "pyside6-essentials"}
REQUIRED = ("pyside6-essentials",)

TARGET_ENV = {
    "python_full_version": "3.11.9",
    "python_version": "3.11",
    "sys_platform": "linux",
    "platform_machine": "x86_64",
    "platform_system": "Linux",
    "os_name": "posix",
    "implementation_name": "cpython",
}

_PIN_RE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*(?P<version>[^\s;#]+)\s*$")
_MARKER_ATOM = re.compile(r"^\s*([a-z_]+)\s*(<=|>=|==|!=|<|>)\s*['\"]([^'\"]*)['\"]\s*$")


class PinError(RuntimeError):
    """The pin list or the lock cannot be interpreted."""


def normalise(name: str) -> str:
    """PEP 503 normalisation: ``PySide6_Essentials`` → ``pyside6-essentials``."""
    return re.sub(r"[-_.]+", "-", name).lower()


# ── marker evaluation ────────────────────────────────────────────────


def _version_parts(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"[._+-]", value) if part]


def _ordering(left: str, right: str) -> int:
    """``-1``/``0``/``1`` comparing two dotted versions part by part."""
    left_parts, right_parts = _version_parts(left), _version_parts(right)
    for left_part, right_part in zip(left_parts, right_parts):
        if left_part == right_part:
            continue
        if isinstance(left_part, int) and isinstance(right_part, int):
            return -1 if left_part < right_part else 1
        return -1 if str(left_part) < str(right_part) else 1
    return (len(left_parts) > len(right_parts)) - (len(left_parts) < len(right_parts))


def _compare(left: str, operator: str, right: str) -> bool:
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    order = _ordering(left, right)
    return {"<": order < 0, "<=": order <= 0, ">": order > 0, ">=": order >= 0}[operator]


def marker_applies(expression: str | None, env: dict | None = None) -> bool:
    """Evaluate the small PEP 508 subset ``uv.lock`` uses for split resolutions.

    Supports comparisons on one environment key, ``and``/``or`` and parentheses.
    Anything outside that subset raises instead of being assumed true.
    """
    if not expression:
        return True
    env = dict(TARGET_ENV if env is None else env)
    text = expression.strip()
    while text.startswith("(") and text.endswith(")") and _balanced(text[1:-1]):
        text = text[1:-1].strip()

    split = _split_marker(text)
    if split is not None:
        joiner, chunks = split
        results = (marker_applies(chunk, env) for chunk in chunks)
        return all(results) if joiner == "and" else any(results)

    match = _MARKER_ATOM.match(text)
    if not match:
        raise PinError(f"cannot evaluate marker {expression!r}")
    key, operator, value = match.groups()
    if key not in env:
        raise PinError(f"unknown marker variable {key!r} in {expression!r}")
    return _compare(str(env[key]), operator, value)


def _balanced(text: str) -> bool:
    depth = 0
    for char in text:
        depth += char == "("
        depth -= char == ")"
        if depth < 0:
            return False
    return depth == 0


def _split_marker(text: str) -> tuple[str, list[str]] | None:
    """Split a marker expression on the top-level ``or`` (preferred) or ``and``."""
    for joiner in ("or", "and"):
        depth = 0
        chunks: list[str] = []
        current = ""
        found = False
        for token in re.split(r"(\s+(?:and|or)\s+|[()])", text):
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
            elif depth == 0 and re.fullmatch(r"\s+" + joiner + r"\s+", token or ""):
                chunks.append(current.strip())
                current = ""
                found = True
                continue
            current += token
        if found:
            chunks.append(current.strip())
            return joiner, [chunk for chunk in chunks if chunk]
    return None


# ── lock reading ─────────────────────────────────────────────────────


def _lock(path: Path) -> list[dict]:
    try:
        return tomllib.loads(Path(path).read_text(encoding="utf-8")).get("package") or []
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PinError(f"cannot read {path}: {exc}") from exc


def lock_packages(path: Path = DEFAULT_LOCK) -> dict[str, set[str]]:
    """``{normalised name: {versions}}`` — several when a resolution is split."""
    packages: dict[str, set[str]] = {}
    for entry in _lock(path):
        name, version = normalise(entry.get("name", "")), entry.get("version")
        if name and version:
            packages.setdefault(name, set()).add(version)
    return packages


def lock_versions(path: Path = DEFAULT_LOCK) -> dict[str, set[str]]:
    """Versions that apply to :data:`TARGET_ENV` (marker-split resolutions resolved)."""
    versions: dict[str, set[str]] = {}
    for entry in _lock(path):
        name, version = normalise(entry.get("name", "")), entry.get("version")
        if not name or not version:
            continue
        markers = entry.get("resolution-markers")
        if markers and not any(marker_applies(marker) for marker in markers):
            continue
        versions.setdefault(name, set()).add(version)
    return versions


def lite_closure(path: Path = DEFAULT_LOCK) -> dict[str, str]:
    """The exact ``{package: version}`` set the Presenter builds must install."""
    packages = {normalise(entry["name"]): entry for entry in _lock(path) if entry.get("name")}
    if PROJECT_NAME not in packages:
        raise PinError(f"{PROJECT_NAME} is not in {path}")
    excluded = {normalise(name) for name in EXCLUDED}
    root = packages[PROJECT_NAME]
    queue = [normalise(item["name"]) for item in root.get("dependencies") or []]
    optional = root.get("optional-dependencies") or {}
    for extra in PRESENTER_EXTRAS:
        queue += [normalise(item["name"]) for item in optional.get(extra) or []]

    seen: set[str] = set()
    while queue:
        requested = queue.pop()
        name = SUBSTITUTIONS.get(requested, requested)
        if name in seen or name in excluded or name not in packages:
            continue
        seen.add(name)
        children = [normalise(item["name"]) for item in packages[name].get("dependencies") or []]
        queue.extend(children)

    versions = lock_versions(path)
    closure: dict[str, str] = {}
    for name in sorted(seen):
        resolved = versions.get(name) or set()
        if len(resolved) != 1:
            raise PinError(
                f"{path} resolves {name} to {sorted(resolved) or 'nothing'} for the Presenter build environment; "
                "the lite pin list cannot express an ambiguous resolution"
            )
        closure[name] = next(iter(resolved))
    return closure


def parse_pins(path: Path = DEFAULT_PINS) -> list[tuple[str, str]]:
    pins: list[tuple[str, str]] = []
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = _PIN_RE.match(line)
        if not match:
            raise PinError(f"{path}:{number}: not a `name==version` pin: {raw.strip()!r}")
        pins.append((match.group("name"), match.group("version")))
    if not pins:
        raise PinError(f"{path} contains no pins")
    return pins


def pins_map(path: Path = DEFAULT_PINS) -> dict[str, str]:
    pins: dict[str, str] = {}
    for name, version in parse_pins(path):
        key = normalise(name)
        if key in pins:
            raise PinError(f"{path}: {name} is pinned more than once")
        pins[key] = version
    return pins


def check(pins_path: Path = DEFAULT_PINS, lock_path: Path = DEFAULT_LOCK) -> list[str]:
    """Return every violation (empty when the pin list matches the lock exactly)."""
    expected = lite_closure(lock_path)
    pinned = pins_map(pins_path)
    problems: list[str] = []

    for name, version in sorted(expected.items()):
        if name not in pinned:
            problems.append(f"{name}=={version} is missing: the lite set must include every closure package")
        elif pinned[name] != version:
            problems.append(f"{name} is pinned to {pinned[name]}, but uv.lock resolves {version}")
    for name in sorted(set(pinned) - set(expected)):
        if name in {normalise(item) for item in EXCLUDED}:
            problems.append(f"{name} must not be pinned: the lite profile excludes it")
        else:
            problems.append(f"{name} is pinned but not part of the Presenter dependency closure")
    for required in REQUIRED:
        if normalise(required) not in pinned:
            problems.append(f"{required} must be pinned: it replaces an excluded package")
    return problems


def render_pins(closure: dict[str, str]) -> list[str]:
    return [f"{name}=={version}" for name, version in sorted(closure.items())]


def rewrite(pins_path: Path = DEFAULT_PINS, lock_path: Path = DEFAULT_LOCK) -> list[str]:
    """Replace the pin body with the closure from the lock, keeping the header."""
    path = Path(pins_path)
    text = path.read_text(encoding="utf-8")
    header: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            header.append(line)
        else:
            break
    while header and not header[-1].strip():
        header.pop()
    body = render_pins(lite_closure(lock_path))
    path.write_text("\n".join(header + [""] + body) + "\n", encoding="utf-8")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--write", action="store_true", help="regenerate the pin body from uv.lock")
    args = parser.parse_args(argv)
    try:
        if args.write:
            body = rewrite(args.pins, args.lock)
            print(f"presenter pins: wrote {len(body)} pin(s) to {args.pins}")
        problems = check(args.pins, args.lock)
    except (OSError, PinError) as exc:
        print(f"presenter pins: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("presenter pins: the lite pin list does not match uv.lock:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("  fix with: python tools/release/presenter_pins.py --write", file=sys.stderr)
        return 1
    count = len(pins_map(args.pins))
    print(
        f"presenter pins OK: {count} pin(s) match uv.lock for "
        f"{TARGET_ENV['python_full_version']}/{TARGET_ENV['sys_platform']}, excluded set absent, "
        "lite replacement present"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
