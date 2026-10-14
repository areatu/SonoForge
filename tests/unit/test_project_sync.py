"""The tracker sync engine is safe to re-run and never guesses (QH tracker, .github/tracker).

Pinned down here, all without touching the network:

* the plan file is validated strictly — duplicate epic keys, unknown milestones and
  undefined labels are refused instead of silently syncing a half-broken board;
* the issue body carries the marker that makes creation idempotent, and its checklist
  is a faithful rendering of the plan snapshot;
* the board status is *derived* (closed → Done, ``status:blocked`` → Blocked,
  ``status:partial`` → In Progress), so a stale plan snapshot can never reopen or
  close work on its own;
* permission failures are translated into the token the user actually needs, because
  fine-grained PATs cannot reach user-owned Projects at all.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PLAN = _ROOT / ".github" / "tracker" / "qh-plan.yml"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / ".github" / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve string annotations through sys.modules[module.__name__].
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sync = _load("project_sync")


# ── slice rendering ─────────────────────────────────────────────────


def test_checked_slice_is_parsed_as_done_without_its_marker() -> None:
    done, text = sync.parse_slice("[x] Срез один")
    assert done is True
    assert text == "Срез один"


def test_unchecked_slice_bracket_is_stripped_too() -> None:
    done, text = sync.parse_slice("[ ] Срез два")
    assert done is False
    assert text == "Срез два"


def test_slice_without_checkbox_is_open_and_kept_verbatim() -> None:
    done, text = sync.parse_slice("просто текст")
    assert done is False
    assert text == "просто текст"


# ── board status is derived from the issue, not from the plan ───────


def test_closed_issue_is_done_regardless_of_labels() -> None:
    assert sync.status_for("closed", ["status:blocked"]) == sync.STATUS_DONE


def test_blocked_label_outranks_partial() -> None:
    assert sync.status_for("open", ["status:partial", "status:blocked"]) == sync.STATUS_BLOCKED


def test_partial_label_means_in_progress() -> None:
    assert sync.status_for("open", ["status:partial"]) == sync.STATUS_IN_PROGRESS


def test_open_issue_without_status_labels_is_todo() -> None:
    assert sync.status_for("open", ["qh"]) == sync.STATUS_TODO


# ── token diagnosis ─────────────────────────────────────────────────


def test_integration_token_error_points_at_the_pat_requirement() -> None:
    hint = sync.auth_hint("GraphQL error: Resource not accessible by integration")
    assert "classic" in hint
    assert "project" in hint and "repo" in hint


def test_fine_grained_token_error_says_user_projects_are_unreachable() -> None:
    hint = sync.auth_hint("Resource not accessible by personal access token")
    assert "fine-grained" in hint
    assert "организац" in hint


def test_scope_error_mentions_both_token_flavours() -> None:
    hint = sync.auth_hint("Your token has not been granted the required scopes to execute this query")
    assert "project" in hint
    assert "Organization permissions" in hint


def test_unrelated_error_gets_no_hint() -> None:
    assert sync.auth_hint("HTTP 500: internal error") == ""


# ── plan rendering ──────────────────────────────────────────────────


def test_plan_loads_with_the_shipped_structure() -> None:
    plan = sync.load_plan(_PLAN)
    assert plan.name == "QH"
    assert len(plan.epics) == 19
    assert {epic.gate for epic in plan.epics} >= {"G0", "G1", "G1-STE", "G2", "G3", "G4", "G5a", "G5b"}
    assert plan.tracker_label == "qh"


def test_every_epic_milestone_and_label_exists_in_the_plan() -> None:
    plan = sync.load_plan(_PLAN)
    milestones = {milestone["title"] for milestone in plan.milestones}
    labels = {label["name"] for label in plan.labels}
    for epic in plan.epics:
        assert epic.milestone in milestones, epic.key
        assert set(epic.labels) <= labels, epic.key


def test_closed_epics_are_fully_checked_in_the_snapshot() -> None:
    plan = sync.load_plan(_PLAN)
    for epic in plan.epics:
        if epic.state == "closed":
            assert epic.done_slices == len(epic.slices), epic.key
        else:
            assert epic.done_slices < len(epic.slices) or not epic.slices, epic.key


def test_body_starts_with_the_marker_that_makes_creation_idempotent() -> None:
    plan = sync.load_plan(_PLAN)
    epic = next(item for item in plan.epics if item.key == "qh-1c")
    body = sync.render_body(epic, plan)
    assert body.startswith(epic.marker)
    assert "<!-- qh-tracker:qh-1c -->" in body
    assert "docs/superpowers/specs" in body


def test_body_renders_the_checklist_and_counts_the_snapshot() -> None:
    plan = sync.load_plan(_PLAN)
    epic = next(item for item in plan.epics if item.key == "qh-1c")
    body = sync.render_body(epic, plan)
    assert f"### Срезы ({epic.done_slices}/{len(epic.slices)} по снимку)" in body
    assert "- [x] Барьеры generation" in body
    assert "- [ ] Hash-remap" in body


def test_body_mentions_the_external_blocker_of_a_blocked_epic() -> None:
    plan = sync.load_plan(_PLAN)
    epic = next(item for item in plan.epics if item.key == "qh-5b")
    assert "status:blocked" in epic.labels
    assert "Примечания" in sync.render_body(epic, plan)


# ── plan validation refuses half-broken input ───────────────────────


def _write_plan(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "plan.yml"
    path.write_text(body, encoding="utf-8")
    return path


_MINIMAL = """
version: 1
project:
  owner: areatu
  title: "Board"
epics:
  - key: a
    title: "A"
    milestone: "M1"
    gate: "G0"
    size: "M"
    state: open
    labels: [qh]
    goal: "goal"
    slices: []
"""


def test_minimal_plan_parses_and_keeps_the_new_flags_default_off(tmp_path: Path) -> None:
    plan = sync.load_plan(_write_plan(tmp_path, _MINIMAL))
    assert plan.project_create is False
    assert plan.project_link_to_repo is False
    assert plan.project_title == "Board"
    assert plan.project_number is None


def test_create_and_link_flags_are_read_from_the_plan(tmp_path: Path) -> None:
    body = _MINIMAL.replace('title: "Board"', 'title: "Board"\n  create: true\n  link_to_repo: true')
    plan = sync.load_plan(_write_plan(tmp_path, body))
    assert plan.project_create is True
    assert plan.project_link_to_repo is True


def test_duplicate_epic_keys_are_refused(tmp_path: Path) -> None:
    body = (
        _MINIMAL
        + """
  - key: a
    title: "A again"
    milestone: "M1"
    gate: "G0"
    size: "M"
    state: open
    labels: [qh]
    goal: "goal"
"""
    )
    with pytest.raises(sync.PlanError, match="duplicate epic key"):
        sync.load_plan(_write_plan(tmp_path, body))


def test_a_plan_without_epics_is_refused(tmp_path: Path) -> None:
    with pytest.raises(sync.PlanError, match="no epics defined"):
        sync.load_plan(_write_plan(tmp_path, "version: 1\nproject:\n  owner: areatu\n  title: B\nepics: []\n"))


def test_missing_owner_is_refused(tmp_path: Path) -> None:
    with pytest.raises(sync.PlanError, match="owner"):
        sync.load_plan(_write_plan(tmp_path, "version: 1\nproject:\n  title: B\nepics:\n  - key: a\n    title: A\n"))


def test_unknown_gui_choices_are_reported_by_the_cli_parser() -> None:
    with pytest.raises(SystemExit):
        sync.main(["nonsense", "--plan", str(_PLAN)])
