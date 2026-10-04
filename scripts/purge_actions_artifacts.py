#!/usr/bin/env python3
"""Delete old GitHub Actions artifacts to keep repository storage in check.

GitHub keeps workflow artifacts for the retention period configured in
``Settings → Actions → General`` (90 days by default, up to 400). Build
artifacts are transport between jobs and redundant copies of published
release assets, so a SonoForge release cycle accumulates tens of gigabytes
of them; the storage is free while the repository is public, but it becomes
billed the moment the repository is made private (``$0.25`` per GB-month).

This script applies a conservative policy instead of a blanket wipe:

* every artifact **name** keeps its ``--keep-latest`` newest copies, so the
  most recent builds stay downloadable;
* only artifacts older than ``--older-than`` days are candidates;
* the ``github-pages`` artifact is never touched — the Pages deployment
  environment references it;
* a single run deletes at most ``--max-deletes`` artifacts (biggest first, so
  a capped run frees the most space) to stay inside the 1000 requests/hour
  API limit of the workflow token; leftovers are reported for the next run.

Usage (the workflow ``.github/workflows/artifact-cleanup.yml`` calls the
same entry point)::

    GH_TOKEN=<token> python scripts/purge_actions_artifacts.py \
        --repo areatu/SonoForge --older-than 14 --keep-latest 2 --dry-run

The token needs the ``actions: write`` permission for deletions (``actions:
read`` is enough for ``--dry-run``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

DEFAULT_API_ROOT = "https://api.github.com"
PROTECTED_NAMES = frozenset({"github-pages"})
MAX_DELETES_DEFAULT = 800
PAGE_SIZE = 100


@dataclass(frozen=True)
class Artifact:
    """A single workflow artifact as returned by the REST API."""

    id: int
    name: str
    created_at: datetime
    size_in_bytes: int

    @property
    def size_mb(self) -> float:
        return self.size_in_bytes / 1024 / 1024


def parse_timestamp(value: str) -> datetime:
    """Parse an API timestamp (``2026-10-03T14:39:04Z``) into an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def select_for_deletion(
    artifacts: Sequence[Artifact],
    *,
    older_than_days: int,
    keep_latest: int,
    max_deletes: int,
    now: datetime | None = None,
    protected_names: Collection[str] = PROTECTED_NAMES,
) -> list[Artifact]:
    """Pick the artifacts to delete, biggest first.

    ``keep_latest`` newest copies are preserved per artifact name, the rest are
    dropped only when older than ``older_than_days``; protected names and
    anything beyond ``max_deletes`` stay in place.
    """
    reference = now or datetime.now(UTC)
    cutoff = reference - timedelta(days=older_than_days)

    grouped: dict[str, list[Artifact]] = {}
    for artifact in artifacts:
        grouped.setdefault(artifact.name, []).append(artifact)

    candidates: list[Artifact] = []
    for name, group in grouped.items():
        if name in protected_names:
            continue
        newest_first = sorted(group, key=lambda a: a.created_at, reverse=True)
        for artifact in newest_first[keep_latest:]:
            if artifact.created_at < cutoff:
                candidates.append(artifact)

    candidates.sort(key=lambda a: (-a.size_in_bytes, a.created_at))
    return candidates[:max_deletes]


class RateLimited(RuntimeError):
    """The API refused the request because of a rate limit."""


class GitHubClient:
    """Minimal REST client for listing and deleting artifacts."""

    def __init__(self, repo: str, token: str, api_root: str = DEFAULT_API_ROOT, timeout: float = 30.0) -> None:
        self.repo = repo
        self.token = token
        self.api_root = api_root.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str) -> dict[str, object] | None:
        request = urllib.request.Request(f"{self.api_root}{path}", method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404 and method == "DELETE":
                return None  # Already gone: nothing to do.
            if error.code in (403, 429):
                remaining = error.headers.get("X-RateLimit-Remaining")
                if remaining == "0" or error.code == 429:
                    raise RateLimited(f"HTTP {error.code}: API rate limit exhausted") from error
            detail = error.read().decode("utf-8", "replace")[:200]
            raise RuntimeError(f"HTTP {error.code} on {method} {path}: {detail}") from error
        return json.loads(body) if body else None

    def iter_artifacts(self) -> Iterator[Artifact]:
        """Yield every artifact of the repository, newest first per API order."""
        page = 1
        while True:
            payload = self._request("GET", f"/repos/{self.repo}/actions/artifacts?per_page={PAGE_SIZE}&page={page}")
            if not payload:
                return
            batch = payload.get("artifacts") or []
            for raw in batch:
                yield Artifact(
                    id=int(raw["id"]),
                    name=str(raw["name"]),
                    created_at=parse_timestamp(str(raw["created_at"])),
                    size_in_bytes=int(raw["size_in_bytes"]),
                )
            if len(batch) < PAGE_SIZE:
                return
            page += 1

    def delete_artifact(self, artifact_id: int) -> None:
        self._request("DELETE", f"/repos/{self.repo}/actions/artifacts/{artifact_id}")


def human_gb(size_in_bytes: int) -> str:
    return f"{size_in_bytes / 1024**3:.1f} GB"


def report_summary(lines: Sequence[str]) -> None:
    """Print the report and mirror it into the Actions job summary when present."""
    for line in lines:
        print(line)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("\n".join(lines) + "\n")
    except OSError:
        pass


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="OWNER/NAME (default: $GITHUB_REPOSITORY)"
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "",
        help="API token (default: $GH_TOKEN / $GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--older-than", type=int, default=14, dest="older_than", help="keep artifacts younger than N days (default: 14)"
    )
    parser.add_argument(
        "--keep-latest",
        type=int,
        default=2,
        dest="keep_latest",
        help="newest copies preserved per artifact name (default: 2)",
    )
    parser.add_argument(
        "--max-deletes",
        type=int,
        default=MAX_DELETES_DEFAULT,
        dest="max_deletes",
        help=f"per-run deletion cap (default: {MAX_DELETES_DEFAULT})",
    )
    parser.add_argument("--dry-run", action="store_true", help="only report what would be deleted")
    parser.add_argument("--delay", type=float, default=0.0, help="seconds to sleep between deletions (default: 0)")
    parser.add_argument(
        "--api-root",
        default=os.environ.get("GITHUB_API_URL", DEFAULT_API_ROOT),
        help="API base URL (GHE); default: public GitHub",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.repo or not args.token:
        print("error: --repo and --token (or $GITHUB_REPOSITORY / $GH_TOKEN) are required", file=sys.stderr)
        return 2

    client = GitHubClient(args.repo, args.token, args.api_root)
    try:
        artifacts = list(client.iter_artifacts())
    except RuntimeError as error:
        print(f"error: cannot list artifacts: {error}", file=sys.stderr)
        return 2

    total_bytes = sum(a.size_in_bytes for a in artifacts)
    selected = select_for_deletion(
        artifacts,
        older_than_days=args.older_than,
        keep_latest=args.keep_latest,
        max_deletes=args.max_deletes,
    )
    selected_bytes = sum(a.size_in_bytes for a in selected)
    remaining = len(artifacts) - len(selected)

    lines = [
        f"[artifact-cleanup] {args.repo}: {len(artifacts)} artifacts, {human_gb(total_bytes)} in total.",
        f"[artifact-cleanup] policy: keep the {args.keep_latest} newest per name, "
        f"delete the rest older than {args.older_than} days, cap {args.max_deletes}/run.",
        f"[artifact-cleanup] selected: {len(selected)} artifacts, {human_gb(selected_bytes)} freed.",
    ]
    if args.dry_run:
        lines.append("[artifact-cleanup] dry run: nothing was deleted.")
    report_summary(lines)

    if not selected:
        return 0

    seen: set[str] = set()
    largest_names: list[str] = []
    for artifact in selected:
        if artifact.name in seen:
            continue
        seen.add(artifact.name)
        largest_names.append(f"{artifact.name} ({artifact.size_mb:.0f} MB)")
        if len(largest_names) == 5:
            break
    largest = ", ".join(largest_names)
    print(f"[artifact-cleanup] largest: {largest}")

    if args.dry_run:
        return 0

    deleted = 0
    deleted_bytes = 0
    interrupted: str | None = None
    for artifact in selected:
        try:
            client.delete_artifact(artifact.id)
        except RateLimited as error:
            interrupted = str(error)
            break
        except RuntimeError as error:
            print(f"::warning::artifact {artifact.id} ({artifact.name}) not deleted: {error}")
            continue
        deleted += 1
        deleted_bytes += artifact.size_in_bytes
        if args.delay:
            time.sleep(args.delay)

    left = len(selected) - deleted
    report_summary(
        [
            f"[artifact-cleanup] deleted {deleted} artifacts, freed {human_gb(deleted_bytes)}.",
            f"[artifact-cleanup] {remaining + left} artifacts remain; rerun to continue.",
        ]
    )
    if interrupted:
        print(f"::warning::rate limit hit ({interrupted}); rerun the workflow in an hour to continue")
    elif left:
        print(f"::warning::{left} selected artifacts were not deleted; rerun to continue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
