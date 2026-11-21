"""Verify a complete, disjoint logic-shard run before merging its evidence.

Counts alone can hide one missing test and one duplicate. Check identities,
terminal outcomes, collection errors and exit status in every OS/Python cell.
The output has the original single-logic inventory shape, so coverage and the
required-formulas gate consume the full run, never an individual shard.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def nodeids(payload: dict[str, Any], key: str) -> set[str]:
    values = payload.get(key)
    require(isinstance(values, list) and all(isinstance(value, str) for value in values), f"missing/invalid {key}")
    require(len(values) == len(set(values)), f"duplicate nodeids in {key}")
    return set(values)


def merge(shards: list[dict[str, Any]], count: int) -> dict[str, Any]:
    require(count > 0 and len(shards) == count, f"expected {count} shards, received {len(shards)}")
    first = shards[0]
    expected = nodeids(first, "eligible_logic_nodeids")
    require(bool(expected), "empty eligible logic inventory")
    all_eligible = nodeids(first, "eligible_nodeids")
    require(expected <= all_eligible, "logic inventory contains ineligible nodes")
    merged: dict[str, Any] = {
        "collected": first["collected"],
        "eligible_not_interactive": first["eligible_not_interactive"],
        "eligible_nodeids": sorted(all_eligible),
        "eligible_logic_nodeids": sorted(expected),
        "selected": dict.fromkeys(first["selected"], 0),
        "outcomes": {},
        "skip_reasons": {},
        "durations": {},
        "collection_errors": [],
        "exit_status": 0,
    }
    seen: set[str] = set()
    indices: set[int] = set()
    files: set[str] = set()
    for shard in shards:
        metadata = shard.get("shard", {})
        index = metadata.get("index")
        require(
            metadata.get("count") == count and type(index) is int and 0 <= index < count, "invalid shard index/count"
        )
        require(index not in indices, f"duplicate shard index {index}")
        indices.add(index)
        require(shard.get("exit_status") == 0, f"shard {index} failed or never finished")
        require(shard.get("collection_errors") == [], f"shard {index} has collection errors or missing evidence")
        for section in ("collected", "eligible_not_interactive"):
            require(shard[section] == first[section], f"shards disagree on {section}")
        require(nodeids(shard, "eligible_logic_nodeids") == expected, "shards disagree on eligible logic nodeids")
        require(nodeids(shard, "eligible_nodeids") == all_eligible, "shards disagree on eligible nodeids")
        selected = nodeids(shard, "selected_nodeids")
        require(bool(selected), f"shard {index} selected no tests")
        require(not seen & selected, f"shard {index} duplicated selected tests")
        require(selected <= expected, f"shard {index} selected GUI or unknown tests")
        selected_files = {node.split("::", 1)[0] for node in selected}
        require(not files & selected_files, "a test file was split between shards")
        files.update(selected_files)
        require(set(shard.get("outcomes", {})) == selected, f"shard {index} lost or added executed tests")
        require(
            all(outcome in {"passed", "skipped", "xfailed"} for outcome in shard["outcomes"].values()),
            f"shard {index} contains a failed/error/xpassed outcome",
        )
        counters = shard["selected"]
        require(counters["total"] == counters["not_gui"] == len(selected), f"shard {index} selected count mismatch")
        require(counters["gui"] == counters["interactive"] == 0, f"shard {index} selected excluded tests")
        for key in merged["selected"]:
            merged["selected"][key] += counters[key]
        for key in ("outcomes", "skip_reasons", "durations"):
            merged[key].update(shard.get(key, {}))
        seen.update(selected)
    require(seen == expected, f"logic partition missing {len(expected - seen)} tests")
    require(len(expected) == first["eligible_not_interactive"]["not_gui"], "eligible logic count mismatch")
    merged["selected_nodeids"] = sorted(seen)
    merged["shard_elapsed_seconds"] = [shard.get("elapsed_seconds", 0) for shard in shards]
    return merged


def timing_summary(payload: dict[str, Any], label: str) -> str:
    by_file: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for node, phases in payload["durations"].items():
        for phase, seconds in phases.items():
            by_file[node.split("::", 1)[0]][phase] += seconds
    rows = [
        f"### Logic shards — {label}\n",
        f"Verified {len(payload['selected_nodeids'])} distinct tests; no missing/overlapping shards.\n",
        "Worker-time totals below include setup/teardown; they are not job wall-clock.\n",
        "| File | Setup, s | Call, s | Teardown, s |",
        "|---|---:|---:|---:|",
    ]
    for filename in sorted(by_file, key=lambda name: -sum(by_file[name].values()))[:15]:
        phases = by_file[filename]
        rows.append(f"| `{filename}` | {phases['setup']:.2f} | {phases['call']:.2f} | {phases['teardown']:.2f} |")
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, nargs="+", type=Path)
    parser.add_argument("--shards", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--github-summary", action="store_true")
    args = parser.parse_args()
    try:
        payload = merge([json.loads(path.read_text(encoding="utf-8")) for path in args.inputs], args.shards)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sys.stdout.write(f"::error title=logic shards::{exc}\n")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = timing_summary(payload, args.output.stem)
    sys.stdout.write(summary)
    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
