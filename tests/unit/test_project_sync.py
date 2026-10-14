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


# ── owner-type fallback: a wrong-kind login is "not found", not an error ──────
#
# GitHub answers user(login:)/organization(login:) with a *type-mismatch error*
# (not null) when the login is the other kind of account. The tracker must treat
# that as "no project under this owner kind" and try the other kind instead —
# the first bootstrap run (board not created yet) crashed on exactly this.


class _FakeGraphQL:
    """Answers the tracker's queries for an owner of one kind; the other kind raises
    the same error GitHub raises, so a fallback that does not swallow it fails the test."""

    def __init__(
        self,
        owner_kind: str = "user",
        projects: list[dict] | None = None,
        project_number: dict | None = None,
        owner_id: str = "MDQ6VXNlcjoxMjM0NQ==",
        fields: list[dict] | None = None,
    ) -> None:
        self.owner_kind = owner_kind
        self.projects = projects or []
        self.project_number = project_number
        self.owner_id = owner_id
        self.fields = fields if fields is not None else [{"id": "F1", "name": "Status", "options": []}]
        self.calls: list[str] = []

    def __call__(self, token: str, query: str, variables: dict | None = None) -> dict:
        variables = variables or {}
        self.calls.append(query)
        if "organization(login" in query and self.owner_kind != "organization":
            raise sync.ApiError(
                f"GraphQL error: Could not resolve to an Organization with the login of '{variables.get('login')}'."
            )
        if "user(login" in query and self.owner_kind != "user":
            raise sync.ApiError(
                f"GraphQL error: Could not resolve to a User with the login of '{variables.get('login')}'."
            )
        if "createProjectV2" in query:
            return {"createProjectV2": {"projectV2": {"id": "P_1", "number": 7, "title": variables.get("title")}}}
        if "projectV2(number" in query:
            return {self.owner_kind: {"projectV2": self.project_number}}
        if "projectsV2(first" in query:
            return {self.owner_kind: {"projectsV2": {"nodes": self.projects}}}
        if "fields(first" in query:
            return {"node": {"fields": {"nodes": self.fields}}}
        if "{ id }" in query:
            return {self.owner_kind: {"id": self.owner_id}}
        raise AssertionError(f"unexpected query: {query}")


def test_first_bootstrap_run_survives_the_org_fallback_for_a_user_owner(monkeypatch) -> None:
    # Regression: board does not exist yet; the user query returns no project and
    # the org fallback must be swallowed, not crash the run.
    fake = _FakeGraphQL(owner_kind="user", projects=[])
    monkeypatch.setattr(sync, "_graphql", fake)
    board = sync.Board("token", "areatu", None, "SonoForge Tracker")
    with pytest.raises(sync.PlanError, match="проект не найден"):
        board.resolve(tolerant=False)
    assert any("organization(login" in call for call in fake.calls)  # it was tried…
    assert any("projectsV2(first" in call for call in fake.calls)


def test_missing_board_is_created_for_a_user_owner(monkeypatch) -> None:
    fake = _FakeGraphQL(owner_kind="user", projects=[])
    monkeypatch.setattr(sync, "_graphql", fake)
    board = sync.Board("token", "areatu", None, "SonoForge Tracker")
    assert board.resolve(tolerant=False, create=True) is True
    assert board.id == "P_1"
    assert board.resolved_number == 7
    assert board.resolved_title == "SonoForge Tracker"
    assert sum("createProjectV2" in call for call in fake.calls) == 1


def test_title_search_finds_user_project_despite_the_org_fallback_error(monkeypatch) -> None:
    fake = _FakeGraphQL(
        owner_kind="user",
        projects=[
            {"id": "P_9", "number": 9, "title": "Something else"},
            {"id": "P_5", "number": 5, "title": "SonoForge Tracker"},
        ],
    )
    monkeypatch.setattr(sync, "_graphql", fake)
    board = sync.Board("token", "areatu", None, "SonoForge Tracker")
    assert board.resolve(tolerant=False) is True
    assert board.id == "P_5"


def test_org_owner_finds_the_project_despite_the_user_fallback_error(monkeypatch) -> None:
    # Symmetric case: the plan can point at an org-owned board too.
    fake = _FakeGraphQL(
        owner_kind="organization",
        owner_id="O_kgDOdXVybmd",
        projects=[{"id": "P_3", "number": 3, "title": "SonoForge Tracker"}],
    )
    monkeypatch.setattr(sync, "_graphql", fake)
    board = sync.Board("token", "some-org", None, "SonoForge Tracker")
    assert board.resolve(tolerant=False) is True
    assert board.id == "P_3"
    assert any("organization(login" in call for call in fake.calls)


def test_number_search_returns_not_found_for_a_user_owner(monkeypatch) -> None:
    fake = _FakeGraphQL(owner_kind="user", project_number=None)
    monkeypatch.setattr(sync, "_graphql", fake)
    board = sync.Board("token", "areatu", 12, None)
    with pytest.raises(sync.PlanError, match="проект не найден"):
        board.resolve(tolerant=False)


def test_number_search_finds_the_user_project(monkeypatch) -> None:
    fake = _FakeGraphQL(owner_kind="user", project_number={"id": "P_12", "number": 12, "title": "SonoForge Tracker"})
    monkeypatch.setattr(sync, "_graphql", fake)
    board = sync.Board("token", "areatu", 12, None)
    assert board.resolve(tolerant=False) is True
    assert board.id == "P_12"


def test_real_permission_error_is_not_swallowed_by_the_owner_fallback(monkeypatch) -> None:
    def fake_graphql(token: str, query: str, variables: dict | None = None) -> dict:
        raise sync.ApiError("GraphQL error: Resource not accessible by personal access token")

    monkeypatch.setattr(sync, "_graphql", fake_graphql)
    board = sync.Board("token", "areatu", None, "SonoForge Tracker")
    with pytest.raises(sync.PlanError, match="не удалось получить проект"):
        board.resolve(tolerant=False)


def test_unhinted_api_error_message_has_no_double_period(monkeypatch) -> None:
    def fake_graphql(token: str, query: str, variables: dict | None = None) -> dict:
        raise sync.ApiError("GraphQL → <urlopen error timed out>")

    monkeypatch.setattr(sync, "_graphql", fake_graphql)
    board = sync.Board("token", "areatu", None, "SonoForge Tracker")
    with pytest.raises(sync.PlanError) as excinfo:
        board.resolve(tolerant=False)
    message = str(excinfo.value)
    assert ".. Иначе" not in message
    assert "Иначе проверьте номер/название проекта" in message
