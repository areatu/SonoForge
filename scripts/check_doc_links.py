#!/usr/bin/env python3
"""Documentation must not point at things that are not in the repository (issue #329).

A link into a file that does not exist, or a comment that names a directory
nobody can clone, makes a requirement impossible to check: it lives in a
document the reader does not have. Two promises, both with a zero baseline:

* **every relative link resolves** — inline links, images and reference
  definitions of every tracked Markdown file (not only ``.md`` targets) must
  point at an existing file or directory. Anchors, URLs and ``mailto:`` are
  not checked; fenced code blocks and inline code are skipped, so an example of
  a link is not a link;
* **no reference to an ignored documentation directory** — the ``docs/...``
  directories named in ``.gitignore`` (the local implementation plans are one)
  hold working files that a clone never has. A tracked text file may not name
  them, except for the documents listed with a reason in
  ``scripts/doc_links_allowlist.json`` — the reviews that *describe* the gap.
  An allowlist entry that no longer names the directory is stale and fails, so
  the list is always exactly the exceptions.

Files are discovered with ``git ls-files`` (so ignored and untracked files are
never scanned) and with a directory walk outside a repository. Standard
library only: the CI lint job installs nothing else.

Exit codes: 0 — clean, 1 — violations, 2 — usage/allowlist errors.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWLIST = REPO_ROOT / "scripts" / "doc_links_allowlist.json"

#: Text files whose references to ignored directories are checked.
TEXT_SUFFIXES = frozenset({".md", ".py", ".yml", ".yaml", ".toml", ".json", ".txt", ".cfg", ".ini"})
SKIPPED_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache"})

_INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]+>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_REFERENCE_DEFINITION = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)")
_CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_FENCE = re.compile(r"^\s{0,3}(```+|~~~+)")


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


# ── discovery ───────────────────────────────────────────────────────────────


def tracked_files(root: Path) -> list[Path]:
    """Tracked files (``git ls-files``); a directory walk unless ``root`` is itself a repository root.

    A directory that merely lies *inside* some other repository (a temporary tree, a vendored
    checkout) is walked: ``git ls-files`` would report its untracked files as nothing.
    """
    try:
        top = (
            subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, check=True)
            .stdout.decode("utf-8")
            .strip()
        )
        if Path(top).resolve() != root.resolve():
            raise OSError("not a repository root")
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
        ).stdout.decode("utf-8")
        return sorted(root / name for name in listing.split("\0") if name and (root / name).is_file())
    except (OSError, subprocess.CalledProcessError):
        return sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and not any(part in SKIPPED_DIRS for part in path.relative_to(root).parts)
        )


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


# ── relative links ──────────────────────────────────────────────────────────


def markdown_links(text: str) -> Iterator[tuple[int, str]]:
    """``(line, target)`` of every link outside fenced code blocks and inline code."""
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = _FENCE.match(line)
        if marker:
            mark = marker.group(1)[0]
            if fence is None:
                fence = mark
            elif fence == mark:
                fence = None
            continue
        if fence is not None:
            continue
        prose = _CODE_SPAN.sub("", line)
        for match in _INLINE_LINK.finditer(prose):
            yield number, match.group(1).strip("<>")
        reference = _REFERENCE_DEFINITION.match(prose)
        if reference:
            yield number, reference.group(1).strip("<>")


def resolve_link(source: Path, target: str, root: Path) -> Path | None:
    """The file a relative link points at, or ``None`` for URLs and in-page anchors."""
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target or _SCHEME.match(target):
        return None
    target = unquote(target)
    base = root if target.startswith("/") else source.parent
    return (base / target.lstrip("/")).resolve()


def find_broken_links(root: Path, files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for source in files:
        if source.suffix.lower() != ".md":
            continue
        text = _read(source)
        if text is None:
            continue
        for number, target in markdown_links(text):
            resolved = resolve_link(source, target, root)
            if resolved is not None and not resolved.exists():
                violations.append(Violation(source.relative_to(root).as_posix(), number, f"broken link: {target}"))
    return violations


# ── ignored documentation directories ───────────────────────────────────────


def ignored_doc_dirs(root: Path) -> list[str]:
    """``docs/...`` directories named in ``.gitignore`` (no trailing slash)."""
    text = _read(root / ".gitignore") or ""
    found: list[str] = []
    for line in text.splitlines():
        pattern = line.strip()
        if pattern.startswith("docs/") and pattern.endswith("/") and not pattern.startswith("!"):
            found.append(pattern.rstrip("/"))
    return found


def load_allowlist(path: Path) -> dict[str, str]:
    """``{file: reason}`` — raises ``OSError``/``ValueError`` on a missing or malformed file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data["allowed"]
    if not isinstance(entries, dict) or not all(
        isinstance(name, str) and isinstance(reason, str) and reason.strip() for name, reason in entries.items()
    ):
        raise ValueError("'allowed' must map file names to a non-empty reason")
    return dict(entries)


def find_ignored_references(root: Path, files: list[Path], allowlist: dict[str, str]) -> list[Violation]:
    directories = ignored_doc_dirs(root)
    if not directories:
        return []
    violations: list[Violation] = []
    seen_in_allowed: set[str] = set()
    for source in files:
        relative = source.relative_to(root).as_posix()
        if relative == ".gitignore" or source.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = _read(source)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            hit = next((directory for directory in directories if directory in line), None)
            if hit is None:
                continue
            if relative in allowlist:
                seen_in_allowed.add(relative)
                continue
            violations.append(
                Violation(
                    relative,
                    number,
                    f"names `{hit}/`, which is in .gitignore and not in the repository — "
                    "describe it in words or link a tracked document",
                )
            )
    for name in sorted(set(allowlist) - seen_in_allowed):
        violations.append(
            Violation(name, 0, "stale allowlist entry — the file no longer names an ignored directory; remove it")
        )
    return violations


# ── command line ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check documentation links (issue #329).")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    parser.add_argument(
        "--allowlist", type=Path, default=None, help="allowlist JSON (default: scripts/doc_links_allowlist.json)"
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    allowlist_path = args.allowlist or (root / "scripts" / "doc_links_allowlist.json")
    try:
        allowlist = load_allowlist(allowlist_path) if allowlist_path.exists() else {}
    except (OSError, ValueError, KeyError) as exc:
        sys.stderr.write(f"error: cannot read {allowlist_path}: {exc}\n")
        return 2

    files = tracked_files(root)
    markdown = sum(1 for path in files if path.suffix.lower() == ".md")
    violations = find_broken_links(root, files) + find_ignored_references(root, files, allowlist)
    if violations:
        sys.stderr.write(f"documentation links failed ({len(violations)} problem(s)):\n")
        sys.stderr.write("\n".join(f"  {violation}" for violation in sorted(violations, key=str)) + "\n")
        return 1
    sys.stdout.write(
        f"documentation links passed: {markdown} Markdown files, no broken relative link, "
        f"no reference to an ignored documentation directory ({len(allowlist)} reviewed exception(s))\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
