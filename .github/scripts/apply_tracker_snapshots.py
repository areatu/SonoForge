#!/usr/bin/env python3
"""Refresh GitHub issue snapshots (body, status labels) from ``.github/tracker/*.yml``.

The tracker plans are the source of truth for the *structure* of the tracker; the issue
state is the source of truth for *progress*.  ``project_sync.py`` writes an issue body
only on creation or with an explicit ``--refresh-bodies`` flag because a body is a
snapshot, not live state.  This script is the explicit refresh step:

* render the body of every epic with :func:`project_sync.render_body` and patch it only
  when it differs;
* add the plan's ``status:*`` label to an open epic (``status:partial`` / ``status:blocked``);
* remove stale ``status:*`` labels and ``p0`` from a closed epic, so a finished package
  does not keep "blocks release" or "in progress" markings;
* leave every other label untouched (manual labels are kept by design);
* never change the issue state or title — those are authoritative.

The script is idempotent: a second run makes no writes.  It is used by
``.github/workflows/tracker-refresh.yml`` and can be run locally with a PAT that has
``issues: write``::

    GH_TOKEN=... python3 .github/scripts/apply_tracker_snapshots.py \\
        --plan .github/tracker/qh-plan.yml --plan .github/tracker/tool-panel-plan.yml

Exit codes: 0 — applied (or nothing to do / dry-run), 1 — an epic has no issue or an API
call failed, 2 — unusable input.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_sync  # noqa: E402  (path setup must come first)

API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
TIMEOUT = 30
MARKER = re.compile(r"<!--\s*qh-tracker:([A-Za-z0-9_.-]+)\s*-->")
STATUS_PREFIX = "status:"
#: Labels that describe a gate/priority of an open package and stop being true when it closes.
CLOSED_REMOVALS = ("p0",)


class ApiError(RuntimeError):
    """GitHub answered with a non-2xx status."""


def _token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        raise SystemExit("GH_TOKEN (or GITHUB_TOKEN) is required")
    return token


def _request(method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {_token()}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "sonoforge-tracker-refresh",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise ApiError(f"{method} {url} -> {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network path
        raise ApiError(f"{method} {url} -> {exc.reason}") from exc


def _repo(explicit: str | None) -> str:
    repo = explicit or os.environ.get("GITHUB_REPOSITORY") or ""
    if "/" not in repo:
        raise SystemExit("--repo owner/name (or GITHUB_REPOSITORY) is required")
    return repo


def _list_issues(repo: str) -> dict[str, dict[str, Any]]:
    """Map epic key → issue payload by the HTML marker in the body."""
    found: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        query = urllib.parse.urlencode({"state": "all", "per_page": 100, "page": page})
        items = _request("GET", f"{API_ROOT}/repos/{repo}/issues?{query}")
        if not isinstance(items, list):
            raise ApiError("unexpected /issues payload")
        for item in items:
            if "pull_request" in item:
                continue
            match = MARKER.search(item.get("body") or "")
            if match:
                found.setdefault(match.group(1), item)
        if len(items) < 100:
            return found
        page += 1


def _label_names(issue: dict[str, Any]) -> set[str]:
    return {label["name"] for label in issue.get("labels") or [] if isinstance(label, dict)}


def _add_labels(repo: str, number: int, labels: list[str]) -> None:
    if labels:
        _request(
            "POST",
            f"{API_ROOT}/repos/{repo}/issues/{number}/labels",
            {"labels": labels},
        )


def _remove_label(repo: str, number: int, label: str) -> None:
    quoted = urllib.parse.quote(label, safe="")
    try:
        _request("DELETE", f"{API_ROOT}/repos/{repo}/issues/{number}/labels/{quoted}")
    except ApiError as exc:
        # 404 means the label is already gone — idempotent re-runs must not fail.
        if " -> 404:" not in str(exc):
            raise


def _apply_plan(
    plan: project_sync.Plan,
    issues: dict[str, dict[str, Any]],
    *,
    repo: str,
    dry_run: bool,
) -> tuple[int, int, list[str]]:
    patched = relabeled = 0
    problems: list[str] = []
    for epic in plan.epics:
        issue = issues.get(epic.key)
        if issue is None:
            problems.append(f"{epic.key}: no issue with marker {epic.marker}")
            continue
        number = int(issue["number"])
        current_body = (issue.get("body") or "").strip()
        new_body = project_sync.render_body(epic, plan).strip()
        if new_body != current_body:
            if dry_run:
                print(f"[dry-run] #{number} {epic.key}: body {len(current_body)} -> {len(new_body)} chars")
            else:
                _request(
                    "PATCH",
                    f"{API_ROOT}/repos/{repo}/issues/{number}",
                    {"body": new_body},
                )
                print(f"#{number} {epic.key}: body updated")
            patched += 1

        closed = issue.get("state") == "closed"
        current_labels = _label_names(issue)
        plan_status = {label for label in epic.labels if label.startswith(STATUS_PREFIX)}
        add = sorted(plan_status - current_labels) if not closed else []
        remove: set[str] = set()
        for label in current_labels:
            if label.startswith(STATUS_PREFIX):
                # A closed package never keeps "in progress"/"blocked"; an open one loses
                # only a status the plan no longer declares.
                if closed or label not in plan_status:
                    remove.add(label)
            elif closed and label in CLOSED_REMOVALS:
                remove.add(label)
        remove_sorted = sorted(remove)
        if add or remove_sorted:
            if dry_run:
                print(f"[dry-run] #{number} {epic.key}: labels +{add} -{remove_sorted}")
            else:
                _add_labels(repo, number, add)
                for label in remove_sorted:
                    _remove_label(repo, number, label)
                print(f"#{number} {epic.key}: labels +{add} -{remove_sorted}")
            relabeled += 1

        if epic.state == "closed" and not closed:
            problems.append(f"#{number} {epic.key}: plan says closed, issue is open (state not changed)")
        if epic.state == "open" and closed:
            problems.append(f"#{number} {epic.key}: plan says open, issue is closed (state not changed)")
    return patched, relabeled, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--plan",
        action="append",
        default=[],
        help="tracker plan (repeatable); required",
    )
    parser.add_argument("--repo", help="owner/name; defaults to GITHUB_REPOSITORY")
    parser.add_argument("--dry-run", action="store_true", help="print actions, write nothing")
    args = parser.parse_args(argv)
    if not args.plan:
        parser.error("at least one --plan is required")

    repo = _repo(args.repo)
    plans: list[project_sync.Plan] = []
    try:
        for raw in args.plan:
            plans.append(project_sync.load_plan(Path(raw)))
    except project_sync.PlanError as exc:
        print(f"plan error: {exc}", file=sys.stderr)
        return 2

    try:
        issues = _list_issues(repo)
    except ApiError as exc:
        print(f"GitHub error: {exc}", file=sys.stderr)
        return 1

    total_bodies = total_labels = 0
    problems: list[str] = []
    for plan in plans:
        patched, relabeled, plan_problems = _apply_plan(
            plan, issues, repo=repo, dry_run=args.dry_run
        )
        total_bodies += patched
        total_labels += relabeled
        problems.extend(plan_problems)
        print(
            f"{plan.name}: {len(plan.epics)} epics, bodies {patched}, labels {relabeled}"
            f"{' (dry-run)' if args.dry_run else ''}"
        )

    for problem in problems:
        print(f"warning: {problem}", file=sys.stderr)
    print(f"done: {total_bodies} bodies, {total_labels} label sets, {len(problems)} warnings")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
