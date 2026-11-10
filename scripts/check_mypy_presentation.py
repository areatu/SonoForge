#!/usr/bin/env python3
"""Ratchet mypy --strict errors per file and error code across presentation (#476).

``domain``, ``imaging``, ``application``, ``infrastructure``, ``ui``,
``constructor``, and every transitively-clean ``presentation`` module live in
``[tool.mypy].files`` with ``strict = true``. The remaining ``presentation``
modules (notably ``ViewerWidget`` and ``MainWindow`` while #478/#479 decompose
them) are checked here against ``scripts/mypy_presentation_baseline.json``:

* any new error or grown ``(file, error_code)`` count fails CI immediately;
* any module outside the baseline (including transitively-blocked 0-error
  modules) has an implicit ceiling of **0** errors;
* when a module and its ``presentation`` imports reach **0** errors, it must
  graduate out of the baseline and into ``[tool.mypy].files`` in
  ``pyproject.toml`` (``--fix`` performs both updates automatically);
* on the baseline Python version (3.11) counts must match the baseline so debt
  is ratcheted down as slices land; on newer matrix versions (3.12, 3.13)
  ``actual <= baseline`` is enforced as a ceiling so minor stub differences
  do not cause false staleness while regressions still fail.

Standard library only (plus invoking ``mypy`` as a subprocess).

Usage:
    python scripts/check_mypy_presentation.py [--github-summary]
    python scripts/check_mypy_presentation.py --python-version 3.12 --mypy-bin /path/to/mypy
    python scripts/check_mypy_presentation.py --fix
Exit: 0 — within baseline, 1 — regression / unpromoted module / stale baseline, 2 — usage/IO.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRES_ROOT = REPO_ROOT / "src" / "echo_personal_tool" / "presentation"
DEFAULT_PYPROJECT = REPO_ROOT / "pyproject.toml"
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "mypy_presentation_baseline.json"
PRES_PREFIX = "src/echo_personal_tool/presentation/"

_ERROR_RE = re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+): error: (?P<msg>.+?)  ?\[(?P<code>[a-z0-9-]+)\]\s*$")


@dataclass(frozen=True)
class MypyDiagnostic:
    file: str
    line: int
    code: str
    message: str


def run_mypy(
    pres_root: Path,
    *,
    pyproject: Path,
    mypy_bin: str | None = None,
    python_version: str | None = None,
) -> tuple[int, str]:
    prefix = [mypy_bin] if mypy_bin else [sys.executable, "-m", "mypy"]
    cmd = [
        *prefix,
        "--config-file",
        str(pyproject),
        "--no-incremental",
        "--show-error-codes",
        "--no-error-summary",
        "--no-pretty",
    ]
    if python_version is not None:
        cmd.extend(["--python-version", python_version])
    cmd.append(str(pres_root))
    proc = subprocess.run(cmd, cwd=pyproject.parent, capture_output=True, text=True, check=False)
    if proc.returncode not in (0, 1):
        raise RuntimeError(
            f"mypy exited with unexpected status {proc.returncode}:\n{proc.stdout}\n{proc.stderr}".strip()
        )
    return proc.returncode, proc.stdout


def parse_mypy_output(output: str, *, repo_root: Path = REPO_ROOT) -> list[MypyDiagnostic]:
    """Parse ``mypy --show-error-codes --no-pretty`` lines for ``presentation/``."""
    diagnostics: list[MypyDiagnostic] = []
    for raw in output.splitlines():
        match = _ERROR_RE.match(raw)
        if match is None:
            continue
        raw_path = match.group("path").replace("\\", "/")
        candidate = Path(raw_path)
        if candidate.is_absolute():
            try:
                norm_path = candidate.resolve().relative_to(repo_root.resolve()).as_posix()
            except ValueError:
                norm_path = raw_path
        else:
            norm_path = raw_path
        if not norm_path.startswith(PRES_PREFIX):
            continue
        diagnostics.append(
            MypyDiagnostic(
                file=norm_path,
                line=int(match.group("line")),
                code=match.group("code"),
                message=match.group("msg").strip(),
            )
        )
    return diagnostics


def count_by_file_and_code(diagnostics: list[MypyDiagnostic]) -> dict[str, dict[str, int]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for item in diagnostics:
        grouped[item.file][item.code] += 1
    return {file: dict(sorted(codes.items())) for file, codes in sorted(grouped.items())}


def presentation_files(pres_root: Path, *, repo_root: Path = REPO_ROOT) -> list[str]:
    return sorted(
        path.relative_to(repo_root).as_posix() for path in pres_root.rglob("*.py") if "__pycache__" not in path.parts
    )


def transitively_clean_files(
    pres_root: Path,
    dirty_files: set[str],
    *,
    repo_root: Path = REPO_ROOT,
) -> set[str]:
    """Return ``presentation`` files with 0 errors in themselves and all ``presentation`` deps."""
    src_root = repo_root / "src"
    all_pres = presentation_files(pres_root, repo_root=repo_root)
    pres_set = set(all_pres)

    mod_to_file: dict[str, str] = {}
    for rel in all_pres:
        parts = list(Path(rel).relative_to("src").with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        mod_to_file[".".join(parts)] = rel

    deps: dict[str, set[str]] = defaultdict(set)
    for rel in all_pres:
        full_path = repo_root / rel
        # Importing any submodule executes every ancestor package __init__.py.
        cur = full_path.parent
        while cur.is_relative_to(pres_root):
            init_rel = (cur / "__init__.py").relative_to(repo_root).as_posix()
            if init_rel in pres_set and init_rel != rel:
                deps[rel].add(init_rel)
            if cur == pres_root:
                break
            cur = cur.parent

        mod_parts = list(full_path.relative_to(src_root).with_suffix("").parts)
        pkg = mod_parts[:-1] if mod_parts[-1] != "__init__" else mod_parts
        tree = ast.parse(full_path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    anchor = pkg[: max(len(pkg) - (node.level - 1), 0)]
                    base = ".".join([*anchor, node.module]) if node.module else ".".join(anchor)
                else:
                    base = node.module or ""
                if base in mod_to_file:
                    deps[rel].add(mod_to_file[base])
                for alias in node.names:
                    cand = f"{base}.{alias.name}" if base else alias.name
                    if cand in mod_to_file:
                        deps[rel].add(mod_to_file[cand])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in mod_to_file:
                        deps[rel].add(mod_to_file[alias.name])

    rev_deps: dict[str, set[str]] = defaultdict(set)
    for src, targets in deps.items():
        for dst in targets:
            rev_deps[dst].add(src)

    trans_dirty = set(dirty_files)
    queue = list(dirty_files)
    while queue:
        item = queue.pop()
        for caller in rev_deps[item]:
            if caller not in trans_dirty:
                trans_dirty.add(caller)
                queue.append(caller)

    return {rel for rel in all_pres if rel not in trans_dirty}


def strict_presentation_files(pyproject: Path, all_pres: list[str]) -> set[str]:
    """Expand ``[tool.mypy].files`` entries covering ``presentation/`` into file paths."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    configured = data.get("tool", {}).get("mypy", {}).get("files", [])
    if not isinstance(configured, list):
        return set()
    covered: set[str] = set()
    for entry in configured:
        if not isinstance(entry, str):
            continue
        norm = entry.rstrip("/")
        for rel in all_pres:
            if rel == norm or rel.startswith(f"{norm}/"):
                covered.add(rel)
    return covered


def load_baseline(path: Path, existing_files: set[str]) -> tuple[dict[str, object], list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"cannot read baseline {path}: {exc}"]
    problems: list[str] = []
    if not isinstance(data, dict):
        return {}, ["baseline must be a JSON object"]
    if data.get("origin_issue") != 476:
        problems.append("baseline origin_issue must be 476")
    if not isinstance(data.get("python_version"), str):
        problems.append("baseline needs a string 'python_version'")
    files = data.get("files")
    if not isinstance(files, dict):
        problems.append("baseline needs a 'files' object")
        return data, problems

    computed_total = 0
    for rel, codes in files.items():
        if not isinstance(rel, str) or not rel.startswith(PRES_PREFIX) or not rel.endswith(".py"):
            problems.append(f"invalid baseline file key: {rel!r}")
            continue
        if rel not in existing_files:
            problems.append(f"STALE baseline file (deleted or moved): {rel}")
        if not isinstance(codes, dict) or not codes:
            problems.append(f"baseline entry {rel} must map error codes to positive counts")
            continue
        for code, count in codes.items():
            if not isinstance(code, str) or not code:
                problems.append(f"baseline entry {rel} has an empty error code")
            if type(count) is not int or count < 1:
                problems.append(f"baseline entry {rel} [{code}] must be a positive integer, got {count!r}")
            else:
                computed_total += count

    if data.get("total_files") != len(files):
        problems.append(f"baseline total_files={data.get('total_files')!r} != {len(files)}")
    if data.get("total_errors") != computed_total:
        problems.append(f"baseline total_errors={data.get('total_errors')!r} != {computed_total}")
    return data, problems


def check(
    diagnostics: list[MypyDiagnostic],
    *,
    all_pres: list[str],
    trans_clean: set[str],
    strict_covered: set[str],
    baseline_data: dict[str, object],
    baseline_problems: list[str],
    exact_counts: bool = True,
) -> list[str]:
    problems = list(baseline_problems)
    raw_files = baseline_data.get("files", {})
    expected_files: dict[str, dict[str, int]] = raw_files if isinstance(raw_files, dict) else {}
    actual_files = count_by_file_and_code(diagnostics)

    samples: dict[tuple[str, str], list[str]] = defaultdict(list)
    for diag in diagnostics:
        bucket = samples[(diag.file, diag.code)]
        if len(bucket) < 5:
            bucket.append(f"{diag.file}:{diag.line}: {diag.message}")

    # 1. Regressions: new files, new codes, or grown counts.
    for rel in sorted(set(actual_files) | set(expected_files)):
        actual_codes = actual_files.get(rel, {})
        expected_codes = expected_files.get(rel, {})
        for code in sorted(set(actual_codes) | set(expected_codes)):
            found = actual_codes.get(code, 0)
            allowed = expected_codes.get(code, 0)
            if found > allowed:
                locs = "; ".join(samples[(rel, code)])
                kind = "NEW" if allowed == 0 else "GROWN"
                problems.append(f"{kind} mypy error {rel} [{code}]: {allowed} -> {found} ({locs})")
            elif exact_counts and found < allowed:
                problems.append(
                    f"DECREASED mypy error {rel} [{code}]: {allowed} -> {found} "
                    "(run `python scripts/check_mypy_presentation.py --fix` to lower the ratchet)"
                )

    # 2. Promotion gate: transitively-clean presentation files belong in [tool.mypy].files,
    #    and strict-covered files must not linger in the baseline.
    if exact_counts:
        for rel in sorted(trans_clean - strict_covered):
            problems.append(
                f"UNPROMOTED clean module {rel}: 0 errors in module and presentation imports — "
                "move it to `[tool.mypy].files` in pyproject.toml (or run `--fix`)"
            )
    for rel in sorted(strict_covered & set(expected_files)):
        problems.append(f"STALE baseline module {rel}: already covered by `[tool.mypy].files` — remove from baseline")
    return problems


def update_pyproject_strict_files(pyproject: Path, all_pres: list[str], trans_clean: set[str]) -> int:
    """Sync ``[tool.mypy].files`` ``presentation/`` entries to ``trans_clean``."""
    already = strict_presentation_files(pyproject, all_pres)
    if already == trans_clean:
        return 0

    text = pyproject.read_text(encoding="utf-8")
    pattern = re.compile(r"(?ms)^(\[tool\.mypy\]\n.*?^files = \[\n)(.*?)(\n\])")
    match = pattern.search(text)
    if match is None:
        raise RuntimeError(f"could not locate [tool.mypy].files array in {pyproject}")

    existing_lines = [line for line in match.group(2).splitlines() if line.strip()]
    non_pres = [line for line in existing_lines if PRES_PREFIX not in line]
    rebuilt = non_pres + [f'    "{entry}",' for entry in sorted(trans_clean)]
    updated = text[: match.start()] + match.group(1) + "\n".join(rebuilt) + match.group(3) + text[match.end() :]
    pyproject.write_text(updated, encoding="utf-8")
    return len(trans_clean - already)


def write_baseline(path: Path, counts: dict[str, dict[str, int]], *, python_version: str = "3.11") -> None:
    total_errors = sum(sum(codes.values()) for codes in counts.values())
    payload = {
        "comment": (
            "Ratcheted ceiling of mypy --strict errors in presentation modules not yet in "
            "[tool.mypy].files (#476). Counts may only decrease; modules reaching 0 errors "
            "(with clean presentation imports) graduate to [tool.mypy].files via --fix."
        ),
        "origin_issue": 476,
        "python_version": python_version,
        "total_files": len(counts),
        "total_errors": total_errors,
        "files": counts,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_PRES_ROOT, help="presentation package directory")
    parser.add_argument("--pyproject", type=Path, default=DEFAULT_PYPROJECT, help="path to pyproject.toml")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="path to baseline JSON")
    parser.add_argument("--mypy-bin", default=None, help="mypy executable to run (default: python -m mypy)")
    parser.add_argument("--python-version", default=None, help="pass --python-version to mypy")
    parser.add_argument("--mypy-output", type=Path, default=None, help="parse captured mypy stdout instead of running")
    parser.add_argument("--fix", action="store_true", help="lower baseline and promote clean modules to pyproject.toml")
    parser.add_argument("--github-summary", action="store_true", help="append report to GITHUB_STEP_SUMMARY")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"check_mypy_presentation: no such directory {args.root}", file=sys.stderr)
        return 2
    if not args.pyproject.is_file():
        print(f"check_mypy_presentation: no such file {args.pyproject}", file=sys.stderr)
        return 2

    repo_root = args.pyproject.resolve().parent
    pres_root = args.root.resolve()
    try:
        if args.mypy_output is not None:
            raw_output = args.mypy_output.read_text(encoding="utf-8")
        else:
            _rc, raw_output = run_mypy(
                pres_root,
                pyproject=args.pyproject.resolve(),
                mypy_bin=args.mypy_bin,
                python_version=args.python_version,
            )
    except (OSError, RuntimeError) as exc:
        print(f"check_mypy_presentation: {exc}", file=sys.stderr)
        return 2

    diagnostics = parse_mypy_output(raw_output, repo_root=repo_root)
    counts = count_by_file_and_code(diagnostics)
    all_pres = presentation_files(pres_root, repo_root=repo_root)
    trans_clean = transitively_clean_files(pres_root, set(counts), repo_root=repo_root)

    if args.fix:
        promoted = update_pyproject_strict_files(args.pyproject, all_pres, trans_clean)
        strict_now = strict_presentation_files(args.pyproject, all_pres)
        filtered = {rel: codes for rel, codes in counts.items() if rel not in strict_now}
        write_baseline(args.baseline, filtered, python_version=args.python_version or "3.11")
        total_err = sum(sum(c.values()) for c in filtered.values())
        print(
            f"mypy presentation baseline refreshed: {total_err} error(s) in {len(filtered)} file(s); "
            f"{len(strict_now)}/{len(all_pres)} presentation module(s) in [tool.mypy].files "
            f"(+{promoted} promoted)"
        )
        return 0

    strict_covered = strict_presentation_files(args.pyproject, all_pres)
    baseline_data, baseline_problems = load_baseline(args.baseline, set(all_pres))
    baseline_py = baseline_data.get("python_version", "3.11")
    exact_counts = args.python_version in (None, baseline_py)
    problems = check(
        diagnostics,
        all_pres=all_pres,
        trans_clean=trans_clean,
        strict_covered=strict_covered,
        baseline_data=baseline_data,
        baseline_problems=baseline_problems,
        exact_counts=exact_counts,
    )

    total_found = len(diagnostics)
    total_allowed = baseline_data.get("total_errors", "?")
    mode = "exact" if exact_counts else f"ceiling py{args.python_version}"
    if problems:
        header = f"mypy presentation ratchet FAILED ({mode}: {total_found} error(s) vs baseline {total_allowed}):"
        print(header)
        for item in problems:
            print(f"  - {item}")
    else:
        print(
            f"mypy presentation ratchet passed ({mode}): {total_found} error(s) in {len(counts)} file(s) "
            f"within baseline {total_allowed}; {len(strict_covered)}/{len(all_pres)} presentation module(s) strict"
        )

    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as handle:
            status = "PASSED" if not problems else "FAILED"
            handle.write(
                f"### mypy presentation ratchet ({status})\n\n"
                f"- Strict `[tool.mypy].files` coverage: **{len(strict_covered)} / {len(all_pres)}** "
                f"`presentation` modules\n"
                f"- Remaining baseline errors: **{total_found}** across **{len(counts)}** modules "
                f"(ceiling: {total_allowed})\n"
            )
            if problems:
                handle.write("\n" + "\n".join(f"- `{p}`" for p in problems[:25]) + "\n")

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
