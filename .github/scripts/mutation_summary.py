#!/usr/bin/env python3
"""Summarize mutmut results for the nightly mutation job (issue #620).

Prints the mutation score and the list of surviving mutants (the
"разбор выживших мутантов") and fails when the score drops below
``--min-score`` (default 0 = report-only, so a first nightly run cannot
paint the suite red before the baseline is known).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-score", type=float, default=0.0, help="minimum mutation score in percent")
    parser.add_argument("--github-summary", action="store_true")
    args = parser.parse_args()

    out = subprocess.run(
        [sys.executable, "-m", "mutmut", "results", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        data = json.loads(out.stdout)
    except ValueError:
        print(out.stdout)
        print(out.stderr, file=sys.stderr)
        print("mutation_summary: could not parse `mutmut results` output", file=sys.stderr)
        return 2

    stats = data.get("stats", {})
    total = int(stats.get("total", 0))
    killed = int(stats.get("killed", 0))
    survived = int(stats.get("survived", 0))
    score = (100.0 * killed / total) if total else 0.0
    print(f"mutation score: {score:.1f}% ({killed}/{total} killed, {survived} survived)")
    # Workflow command: surfaces the score as a check-run annotation, so the
    # baseline can be established from CI even where job logs are not fetched.
    print(f"::notice title=Mutation score::score {score:.1f}% — {killed}/{total} killed, {survived} survived")

    survivors = [m for m in data.get("mutants", []) if m.get("status") == "survived"]
    lines = [
        "### Mutation testing (domain calculations/calculators)",
        f"score {score:.1f}% — {survived} surviving mutants",
        "",
    ]
    for m in survivors[:50]:
        lines.append(f"- survived: {m.get('name')} ({m.get('location', '')})")
    if len(survivors) > 50:
        lines.append(f"- … and {len(survivors) - 50} more")
    summary = "\n".join(lines)
    print(summary)
    if args.github_summary and Path.environ.get("GITHUB_STEP_SUMMARY"):
        with Path.environ["GITHUB_STEP_SUMMARY"].open("a", encoding="utf-8") as fh:
            fh.write(summary + "\n")
    if score < args.min_score:
        print(f"mutation_summary: score {score:.1f}% below the {args.min_score}% floor", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
