#!/usr/bin/env python3
"""Enforce aggregate and per-module line coverage floors on application/workers (issue 483).

Reads Cobertura ``coverage.xml`` generated after ``coverage combine`` and checks:
  1. At least ``--min-files`` non-empty worker modules were measured (guards
     against path/glob drift silently turning the check into a vacuous pass).
  2. Aggregate line coverage across ``echo_personal_tool/application/workers/``
     meets ``--min-total-percent``.
  3. Every individual non-empty worker ``.py`` module meets
     ``--min-module-percent`` so a newly added 0%-covered background worker
     cannot hide behind the package average.
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

WORKER_MARKERS = (
    "src/echo_personal_tool/application/workers/",
    "echo_personal_tool/application/workers/",
    "application/workers/",
)


@dataclass(frozen=True)
class WorkerFileCoverage:
    filename: str
    statements: int
    covered: int

    @property
    def percent(self) -> float:
        if self.statements == 0:
            return 100.0
        return (self.covered / self.statements) * 100.0


def parse_worker_coverage(xml_path: Path) -> list[WorkerFileCoverage]:
    """Parse ``coverage.xml`` and return coverage per non-empty worker file."""
    tree = ET.parse(xml_path)  # noqa: S314 - trusted local coverage output
    root = tree.getroot()
    by_file: dict[str, tuple[int, int]] = {}

    for cls in root.iter("class"):
        raw_name = (cls.attrib.get("filename") or "").replace("\\", "/")
        if not any(raw_name.startswith(prefix) or f"/{prefix}" in raw_name for prefix in WORKER_MARKERS):
            continue
        short_name = "echo_personal_tool/application/workers/" + raw_name.rsplit("/workers/", 1)[-1]
        lines = list(cls.findall("./lines/line"))
        stmts = len(lines)
        hits = sum(1 for line in lines if int(line.attrib.get("hits", "0")) > 0)
        prev_stmts, prev_hits = by_file.get(short_name, (0, 0))
        by_file[short_name] = (prev_stmts + stmts, prev_hits + hits)

    return [
        WorkerFileCoverage(filename=name, statements=stmts, covered=hits)
        for name, (stmts, hits) in sorted(by_file.items())
        if stmts > 0
    ]


def render_summary(items: list[WorkerFileCoverage], min_total: float, min_module: float) -> str:
    total_stmts = sum(item.statements for item in items)
    total_hits = sum(item.covered for item in items)
    total_pct = (total_hits / total_stmts * 100.0) if total_stmts else 0.0
    out = [
        "### Background workers per-module coverage (issue 483)",
        "",
        f"- **Aggregate**: **{total_pct:.1f}%** ({total_hits}/{total_stmts} lines; floor `{min_total:.1f}%`)",
        f"- **Per-module floor**: `{min_module:.1f}%` across **{len(items)}** worker modules",
        "",
        "| Worker module | Covered / Stmts | Line % |",
        "|---|---:|---:|",
    ]
    for item in items:
        out.append(f"| `{item.filename}` | {item.covered}/{item.statements} | {item.percent:.1f}% |")
    out.append("")
    return "\n".join(out)


def evaluate(
    items: list[WorkerFileCoverage],
    *,
    min_files: int,
    min_total_percent: float,
    min_module_percent: float,
) -> list[str]:
    problems: list[str] = []
    if len(items) < min_files:
        problems.append(f"expected at least {min_files} non-empty worker modules in coverage.xml, found {len(items)}")
        return problems

    total_stmts = sum(item.statements for item in items)
    total_hits = sum(item.covered for item in items)
    total_pct = (total_hits / total_stmts * 100.0) if total_stmts else 0.0
    if total_pct + 1e-9 < min_total_percent:
        problems.append(f"application/workers aggregate coverage {total_pct:.1f}% < required {min_total_percent:.1f}%")

    for item in items:
        if item.percent + 1e-9 < min_module_percent:
            problems.append(
                f"{item.filename}: coverage {item.percent:.1f}% ({item.covered}/{item.statements}) "
                f"< per-module floor {min_module_percent:.1f}%"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml_path", type=Path, help="Path to Cobertura coverage.xml")
    parser.add_argument("--min-files", type=int, default=15)
    parser.add_argument("--min-total-percent", type=float, default=82.0)
    parser.add_argument("--min-module-percent", type=float, default=65.0)
    parser.add_argument("--github-summary", action="store_true")
    args = parser.parse_args(argv)

    if not args.xml_path.is_file():
        print(f"check_worker_coverage: missing {args.xml_path}", file=sys.stderr)
        return 2

    items = parse_worker_coverage(args.xml_path)
    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as handle:
            handle.write(render_summary(items, args.min_total_percent, args.min_module_percent) + "\n")

    problems = evaluate(
        items,
        min_files=args.min_files,
        min_total_percent=args.min_total_percent,
        min_module_percent=args.min_module_percent,
    )
    if problems:
        print("worker coverage gate FAILED:\n" + "\n".join(f"  - {p}" for p in problems), file=sys.stderr)
        return 1

    total_stmts = sum(i.statements for i in items)
    total_hits = sum(i.covered for i in items)
    total_pct = (total_hits / total_stmts * 100.0) if total_stmts else 0.0
    worst = min(items, key=lambda i: i.percent)
    print(
        f"worker coverage gate passed: {total_pct:.1f}% total across {len(items)} worker modules "
        f"(lowest module: {worst.filename} at {worst.percent:.1f}% >= {args.min_module_percent:.1f}%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
