"""Sync the QH work-package plan into GitHub issues, milestones, labels and a Projects v2 board.

The plan file (``.github/tracker/*.yml``) is the single source of truth for the *structure*
of the tracker: labels, milestones and epic issues. This script is idempotent — re-running it
never duplicates an issue and never overwrites a body that was already created unless
``--refresh-bodies`` is passed explicitly.

Authority split (deliberate):

* ``state:`` in the plan is the *initial* state of a newly created issue. Afterwards the issue
  state is authoritative — the board always reflects reality, and editing the plan cannot
  silently reopen or close work.
* Board status is derived: closed issue → ``Done``, ``status:blocked`` → ``Blocked``,
  ``status:partial`` → ``In Progress``, otherwise ``Todo``.
* The labels of an epic are the plan labels *plus* any label added by hand (manual labels are kept).

Tokens
------

``PROJECTS_TOKEN`` (or ``GH_TOKEN``) is used for everything. Which token depends on who owns
the project — GitHub documents the split explicitly:

* **User-owned project** (``/users/<login>/projects/<n>``) — only a **classic PAT** works.
  Fine-grained PATs cannot reach projects owned by a user account at all: "Using fine-grained
  personal access token to access Projects owned by a user account" is listed under their
  limitations, and the fine-grained "Projects" permission lives in *Organization* permissions,
  which "can only be used if the resource owner is an organization". Required scopes:
  ``project`` (read/write to projects) plus ``repo``, which per the scope table "also grants
  the ability to manage projects owned by users".
* **Organization-owned project** — a fine-grained PAT with *Organization permissions → Projects:
  Read and write* plus *Repository permissions → Metadata: Read* is enough and is the
  least-privilege option; add *Issues: Read and write* for the repository side of this script.

The ``GITHUB_TOKEN`` of Actions cannot manage Projects v2 either way, which is why the workflow
passes a separate secret. Errors that look like a scope/permission problem get an explicit hint
(see :func:`auth_hint`).

Usage::

    python .github/scripts/project_sync.py check     --plan .github/tracker/qh-plan.yml
    python .github/scripts/project_sync.py bootstrap --plan .github/tracker/qh-plan.yml --create-fields
    python .github/scripts/project_sync.py sync      --plan .github/tracker/qh-plan.yml

Exit codes: 0 — success (or an offline dry-run print), 1 — drift found or API failure,
2 — unusable input (no token, unresolvable project, malformed plan).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

API_ROOT = "https://api.github.com"
GRAPHQL_ROOT = "https://api.github.com/graphql"
API_VERSION = "2022-11-28"
TIMEOUT = 30

STATUS_TODO = "Todo"
STATUS_IN_PROGRESS = "In Progress"
STATUS_DONE = "Done"
STATUS_BLOCKED = "Blocked"

STATUS_OPTIONS = (STATUS_TODO, STATUS_IN_PROGRESS, STATUS_DONE, STATUS_BLOCKED)

_PROJECT_BY_USER = """
query($login: String!, $number: Int!) {
  user(login: $login) { projectV2(number: $number) { id number title } }
}
"""

_PROJECT_BY_ORG = """
query($login: String!, $number: Int!) {
  organization(login: $login) { projectV2(number: $number) { id number title } }
}
"""

_PROJECTS_BY_USER = """
query($login: String!) { user(login: $login) { projectsV2(first: 50) { nodes { id number title } } } }
"""

_PROJECTS_BY_ORG = """
query($login: String!) { organization(login: $login) { projectsV2(first: 50) { nodes { id number title } } } }
"""

_PROJECT_FIELDS = """
query($project: ID!) {
  node(id: $project) {
    ... on ProjectV2 {
      fields(first: 50) {
        nodes {
          ... on ProjectV2Field { id name }
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }
      }
    }
  }
}
"""

_PROJECT_ITEMS = """
query($project: ID!, $cursor: String) {
  node(id: $project) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { id content { ... on Issue { number } } }
      }
    }
  }
}
"""

_ADD_ITEM = """
mutation($project: ID!, $content: ID!) {
  addProjectV2ItemById(input: {projectId: $project, contentId: $content}) { item { id } }
}
"""

_SET_SINGLE_SELECT = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: ID!) {
  updateProjectV2ItemFieldValue(
    input: {projectId: $project, itemId: $item, fieldId: $field, value: {singleSelectOptionId: $option}}
  ) { projectV2Item { id } }
}
"""

_SET_TEXT = """
mutation($project: ID!, $item: ID!, $field: ID!, $text: String!) {
  updateProjectV2ItemFieldValue(input: {projectId: $project, itemId: $item, fieldId: $field, value: {text: $text}})
  { projectV2Item { id } }
}
"""

_CREATE_SINGLE_SELECT_FIELD = """
mutation($project: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]) {
  createProjectV2Field(
    input: {projectId: $project, dataType: SINGLE_SELECT, name: $name, singleSelectOptions: $options}
  ) { projectV2Field { ... on ProjectV2SingleSelectField { id name options { id name } } } }
}
"""

_CREATE_TEXT_FIELD = """
mutation($project: ID!, $name: String!) {
  createProjectV2Field(input: {projectId: $project, dataType: TEXT, name: $name})
  { projectV2Field { ... on ProjectV2Field { id name } } }
}
"""

_OWNER_ID_USER = """
query($login: String!) { user(login: $login) { id } }
"""

_OWNER_ID_ORG = """
query($login: String!) { organization(login: $login) { id } }
"""

_CREATE_PROJECT = """
mutation($owner: ID!, $title: String!) {
  createProjectV2(input: {ownerId: $owner, title: $title}) { projectV2 { id number title } }
}
"""

_LINK_PROJECT_TO_REPO = """
mutation($project: ID!, $repository: ID!) {
  linkProjectV2ToRepository(input: {projectId: $project, repositoryId: $repository}) { repository { id } }
}
"""


def emit(line: str = "") -> None:
    """Write one line to stdout (a helper, so the module itself stays free of ``print``)."""
    sys.stdout.write(f"{line}\n")


def auth_hint(message: str) -> str:
    """Turn an opaque GitHub permission error into the token choice that fixes it.

    The three shapes below are the ones actually returned for Projects v2 when the credential is
    wrong; each maps to a different fix, so guessing is not acceptable here.
    """
    lowered = message.lower()
    if "not accessible by integration" in lowered:
        return (
            "Это установочный токен GitHub App без permission 'Projects'. Нужен PAT: classic со scopes "
            "'project' + 'repo' для проекта, принадлежащего пользователю, либо fine-grained с "
            "'Organization permissions → Projects: Read and write' для проекта организации."
        )
    if "not accessible by personal access token" in lowered:
        return (
            "Похоже на fine-grained PAT. Проекты, принадлежащие пользовательскому аккаунту, ему недоступны "
            "по спецификации GitHub — нужен classic PAT со scopes 'project' и 'repo'. Fine-grained подходит "
            "только для проекта, принадлежащего организации (Organization permissions → Projects: Read and write)."
        )
    if "scopes to execute this query" in lowered or "insufficient_scopes" in lowered:
        return (
            "Токену не хватает scope. Classic PAT: 'project' для записи, 'read:project' для чтения; "
            "fine-grained: 'Organization permissions → Projects: Read and write' — и только если проект "
            "принадлежит организации, а не пользователю."
        )
    return ""


class ApiError(RuntimeError):
    """An HTTP/GraphQL call failed. Messages never contain the token."""


class PlanError(RuntimeError):
    """The plan file or the invocation cannot be used."""


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------


def _call(method: str, url: str, token: str, payload: Any = None) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("X-GitHub-Api-Version", API_VERSION)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace").replace("\n", " ")
        raise ApiError(f"{method} {url} → HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"{method} {url} → {exc.reason}") from exc
    return json.loads(body) if body else None


def _graphql(token: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = urllib.request.Request(GRAPHQL_ROOT, data=data, method="POST")
    request.add_header("Accept", "application/json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace").replace("\n", " ")
        raise ApiError(f"GraphQL → HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"GraphQL → {exc.reason}") from exc
    errors = result.get("errors") or []
    if errors:
        raise ApiError("GraphQL error: " + "; ".join(str(item.get("message", "?")) for item in errors))
    return result.get("data") or {}


def _owner_query(token: str, query: str, variables: dict[str, Any], container: str) -> dict[str, Any]:
    """Run one owner-type query and return the ``user``/``organization`` node.

    GitHub does not answer ``user(login:)``/``organization(login:)`` with ``null`` when the
    login is the *other* kind of account — it raises ``Could not resolve to an
    Organization/User with the login of '...'``. That mismatch is therefore an empty
    result, not a failure: the other owner type is tried next. Any other error (missing
    scope, no access to the project, network) is re-raised so it can carry the token hint.
    """
    try:
        return _graphql(token, query, variables).get(container) or {}
    except ApiError as exc:
        message = str(exc).lower()
        mismatched = "could not resolve to a user with the login" in message or (
            "could not resolve to an organization with the login" in message
        )
        if not mismatched:
            raise
        return {}


# --------------------------------------------------------------------------------------
# Plan model
# --------------------------------------------------------------------------------------


def parse_slice(item: str) -> tuple[bool, str]:
    """``"[x] text"`` → ``(True, "text")``; plain text stays unchecked."""
    text = item.strip()
    lowered = text.lower()
    if lowered.startswith("[x]"):
        return True, text[3:].strip()
    if lowered.startswith("[ ]"):
        return False, text[3:].strip()
    return False, text


@dataclass
class Epic:
    key: str
    title: str
    milestone: str
    gate: str
    size: str
    state: str
    labels: list[str]
    goal: str
    spec: str = ""
    slices: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def marker(self) -> str:
        return f"<!-- qh-tracker:{self.key} -->"

    @property
    def done_slices(self) -> int:
        return sum(1 for item in self.slices if parse_slice(item)[0])


@dataclass
class Plan:
    path: Path
    name: str
    snapshot: str
    spec: str
    owner: str
    project_number: int | None
    project_title: str | None
    project_create: bool
    project_link_to_repo: bool
    fields: dict[str, str]
    labels: list[dict[str, Any]]
    milestones: list[dict[str, Any]]
    epics: list[Epic]

    @property
    def tracker_label(self) -> str:
        return self.epics[0].labels[0]

    def field(self, key: str, default: str) -> str:
        return self.fields.get(key) or default

    @property
    def gate_values(self) -> list[str]:
        return sorted({epic.gate for epic in self.epics if epic.gate})


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise PlanError(f"{where}: missing required key {key!r}")
    return mapping[key]


def load_plan(path: Path) -> Plan:
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - the workflow installs PyYAML
        raise PlanError(
            'PyYAML is required: pip install "pyyaml==$(python .github/scripts/locked_version.py pyyaml)"'
        ) from exc
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PlanError(f"cannot read plan {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise PlanError(f"cannot parse plan {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PlanError(f"{path}: top level must be a mapping")

    project = _require(raw, "project", str(path))
    if not isinstance(project, dict):
        raise PlanError(f"{path}: project must be a mapping")

    epics: list[Epic] = []
    seen: set[str] = set()
    for index, item in enumerate(_require(raw, "epics", str(path))):
        where = f"{path}: epics[{index}]"
        key = _require(item, "key", where)
        if key in seen:
            raise PlanError(f"{where}: duplicate epic key {key!r}")
        seen.add(key)
        epics.append(
            Epic(
                key=key,
                title=str(_require(item, "title", where)),
                milestone=str(item.get("milestone") or ""),
                gate=str(item.get("gate") or ""),
                size=str(item.get("size") or ""),
                state=str(item.get("state") or "open").lower(),
                labels=[str(label) for label in item.get("labels") or []],
                goal=str(item.get("goal") or ""),
                spec=str(item.get("spec") or ""),
                slices=[str(entry) for entry in item.get("slices") or []],
                evidence=[str(entry) for entry in item.get("evidence") or []],
                related=[str(entry) for entry in item.get("related") or []],
                notes=str(item.get("notes") or ""),
            )
        )
    if not epics:
        raise PlanError(f"{path}: no epics defined")

    return Plan(
        path=path,
        name=str(raw.get("plan_name") or path.stem),
        snapshot=str(raw.get("snapshot") or ""),
        spec=str(raw.get("spec") or ""),
        owner=str(_require(project, "owner", f"{path}: project")),
        project_number=project.get("number"),
        project_title=project.get("title"),
        project_create=bool(project.get("create", False)),
        project_link_to_repo=bool(project.get("link_to_repo", False)),
        fields={str(key): str(value) for key, value in (project.get("fields") or {}).items()},
        labels=[dict(item) for item in (raw.get("labels") or [])],
        milestones=[dict(item) for item in (raw.get("milestones") or [])],
        epics=epics,
    )


def render_body(epic: Epic, plan: Plan) -> str:
    """Render the issue body; the HTML marker makes creation idempotent."""
    lines = [epic.marker, ""]
    source = f"`{plan.spec}`" if plan.spec else "спека QH"
    snapshot = f" · снимок плана {plan.snapshot}" if plan.snapshot else ""
    lines.append(f"> Источник: {source} {epic.spec}{snapshot}".rstrip())
    lines.append("")
    if epic.goal:
        lines.extend([f"**Цель.** {epic.goal}", ""])
    summary = [f"**Gate:** {epic.gate}"] if epic.gate else []
    if epic.size:
        summary.append(f"**Размер:** {epic.size}")
    if epic.milestone:
        summary.append(f"**Milestone:** {epic.milestone}")
    if summary:
        lines.extend([" · ".join(summary), ""])
    if epic.slices:
        lines.append(f"### Срезы ({epic.done_slices}/{len(epic.slices)} по снимку)")
        for item in epic.slices:
            checked, text = parse_slice(item)
            lines.append(f"- [{'x' if checked else ' '}] {text}")
        lines.append("")
    if epic.evidence:
        lines.append("### Evidence")
        lines.extend(f"- {entry}" for entry in epic.evidence)
        lines.append("")
    if epic.related:
        lines.append("### Связано")
        lines.extend(f"- {entry}" for entry in epic.related)
        lines.append("")
    if epic.notes:
        lines.extend(["### Примечания", epic.notes, ""])
    lines.extend(
        [
            "---",
            "Чеклист — снимок из `.github/tracker/`, автоматически не обновляется. "
            "Статус на доске выводится из состояния issue и label'ов `status:*`.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


# --------------------------------------------------------------------------------------
# GitHub repository (REST)
# --------------------------------------------------------------------------------------


class Repository:
    """Labels, milestones and issues. Everything here also works with a plain GITHUB_TOKEN."""

    def __init__(self, owner: str, name: str, token: str) -> None:
        self.owner = owner
        self.name = name
        self.token = token

    def _url(self, suffix: str) -> str:
        return f"{API_ROOT}/repos/{self.owner}/{self.name}{suffix}"

    def _paginate(self, suffix: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            separator = "&" if "?" in suffix else "?"
            batch = _call("GET", self._url(f"{suffix}{separator}page={page}"), self.token)
            if not isinstance(batch, list):
                raise ApiError(f"GET {suffix} → unexpected payload (expected a list)")
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1

    def labels(self) -> dict[str, dict[str, Any]]:
        return {item["name"]: item for item in self._paginate("/labels?per_page=100")}

    def create_label(self, name: str, color: str, description: str) -> None:
        _call("POST", self._url("/labels"), self.token, {"name": name, "color": color, "description": description})

    def update_label(self, name: str, color: str, description: str) -> None:
        path = urllib.parse.quote(name, safe="")
        _call(
            "PATCH",
            self._url(f"/labels/{path}"),
            self.token,
            {"new_name": name, "color": color, "description": description},
        )

    def milestones(self) -> dict[str, dict[str, Any]]:
        return {item["title"]: item for item in self._paginate("/milestones?state=all&per_page=100")}

    def create_milestone(self, title: str, description: str) -> dict[str, Any]:
        return _call("POST", self._url("/milestones"), self.token, {"title": title, "description": description})

    def close_milestone(self, number: int) -> None:
        _call("PATCH", self._url(f"/milestones/{number}"), self.token, {"state": "closed"})

    def issues(self, label: str) -> dict[int, dict[str, Any]]:
        """Every issue (open and closed) carrying ``label``, keyed by number."""
        collected: dict[int, dict[str, Any]] = {}
        for item in self._paginate(f"/issues?state=all&labels={urllib.parse.quote(label)}&per_page=100"):
            if "pull_request" in item:  # the issues endpoint also returns pull requests
                continue
            collected[item["number"]] = item
        return collected

    def create_issue(self, *, title: str, body: str, labels: list[str], milestone: int | None) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title, "body": body, "labels": labels}
        if milestone is not None:
            payload["milestone"] = milestone
        return _call("POST", self._url("/issues"), self.token, payload)

    def update_issue(self, number: int, payload: dict[str, Any]) -> dict[str, Any]:
        return _call("PATCH", self._url(f"/issues/{number}"), self.token, payload)


# --------------------------------------------------------------------------------------
# Projects v2 (GraphQL)
# --------------------------------------------------------------------------------------


class Board:
    """Minimal Projects v2 client: resolve the project, read fields/items, write values."""

    def __init__(self, token: str, owner: str, number: int | None, title: str | None) -> None:
        self.token = token
        self.owner = owner
        self.number = number
        self.title = title
        self.id = ""
        self.resolved_number: int | None = None
        self.resolved_title = ""
        self.fields: dict[str, dict[str, Any]] = {}

    # -- resolution -------------------------------------------------------------------

    def resolve(self, *, tolerant: bool, create: bool = False) -> bool:
        """Find the project, creating it first when ``create`` is set and it does not exist.

        ``tolerant`` (dry-run / check) turns a permission failure into a warning.
        """
        try:
            project = self._find_project()
            if not project and create:
                project = self._create_project()
        except ApiError as exc:
            if tolerant:
                emit(f"::warning::Проект недоступен ({exc}); dry-run продолжается без project-плана.")
                return False
            hint = auth_hint(str(exc))
            hint_suffix = f" {hint}" if hint else ""
            raise PlanError(
                f"не удалось получить проект: {exc}.{hint_suffix} Иначе проверьте номер/название проекта "
                "и что токен имеет доступ к доске."
            ) from exc
        if not project:
            raise PlanError(
                f"проект не найден у {self.owner!r} (number={self.number}, title={self.title!r}); укажите "
                "number/title в .github/tracker/*.yml, передайте --project-number/--project-title "
                "или разрешите создание через project.create: true / --create-project"
            )
        self.id = project["id"]
        self.resolved_number = project.get("number")
        self.resolved_title = project.get("title", "")
        self.fields = self._load_fields()
        return True

    def _create_project(self) -> dict[str, Any]:
        if not self.title:
            raise PlanError("для создания доски задайте project.title в plan-файле (или --project-title)")
        owner_id = self._owner_id()
        data = _graphql(self.token, _CREATE_PROJECT, {"owner": owner_id, "title": self.title})
        project = (data.get("createProjectV2") or {}).get("projectV2") or {}
        if not project:
            raise PlanError(f"GitHub не вернул созданный проект для владельца {self.owner!r}")
        emit(f"создана доска #{project.get('number')} «{project.get('title')}» у {self.owner}")
        return project

    def _owner_id(self) -> str:
        for query, container in ((_OWNER_ID_USER, "user"), (_OWNER_ID_ORG, "organization")):
            node = _owner_query(self.token, query, {"login": self.owner}, container)
            if node.get("id"):
                return node["id"]
        raise PlanError(f"не удалось определить владельца {self.owner!r} — проверьте project.owner в plan-файле")

    def link_repository(self, repository_node_id: str) -> None:
        """Show the board in the repository's Projects tab."""
        _graphql(
            self.token,
            _LINK_PROJECT_TO_REPO,
            {"project": self.id, "repository": repository_node_id},
        )

    def _find_project(self) -> dict[str, Any] | None:
        if self.number is not None:
            for query, container in ((_PROJECT_BY_USER, "user"), (_PROJECT_BY_ORG, "organization")):
                node = _owner_query(self.token, query, {"login": self.owner, "number": self.number}, container)
                project = node.get("projectV2")
                if project:
                    return project
            return None
        if not self.title:
            raise PlanError(
                "не задан проект: заполните project.number или project.title в plan-файле, либо передайте "
                "--project-number/--project-title"
            )
        for query, container in ((_PROJECTS_BY_USER, "user"), (_PROJECTS_BY_ORG, "organization")):
            node = _owner_query(self.token, query, {"login": self.owner}, container)
            for item in (node.get("projectsV2") or {}).get("nodes") or []:
                if item and item.get("title") == self.title:
                    return item
        return None

    def _load_fields(self) -> dict[str, dict[str, Any]]:
        data = _graphql(self.token, _PROJECT_FIELDS, {"project": self.id})
        node = data.get("node") or {}
        fields: dict[str, dict[str, Any]] = {}
        for item in (node.get("fields") or {}).get("nodes") or []:
            if not item or not item.get("id"):
                continue
            options = {option["name"]: option["id"] for option in (item.get("options") or []) if option}
            fields[item["name"]] = {"id": item["id"], "options": options}
        return fields

    def items(self) -> dict[int, str]:
        """Map issue number → project item id for everything already on the board."""
        mapping: dict[int, str] = {}
        cursor: str | None = None
        while True:
            data = _graphql(self.token, _PROJECT_ITEMS, {"project": self.id, "cursor": cursor})
            node = data.get("node") or {}
            items = node.get("items") or {}
            for item in items.get("nodes") or []:
                content = (item or {}).get("content") or {}
                if item and content.get("number"):
                    mapping[int(content["number"])] = item["id"]
            page = items.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                return mapping
            cursor = page.get("endCursor")

    # -- mutations --------------------------------------------------------------------

    def add_item(self, issue_node_id: str) -> str:
        data = _graphql(self.token, _ADD_ITEM, {"project": self.id, "content": issue_node_id})
        return ((data.get("addProjectV2ItemById") or {}).get("item") or {}).get("id", "")

    def set_single_select(self, item_id: str, field_name: str, option_name: str) -> bool:
        definition = self.fields.get(field_name)
        if not definition:
            emit(f"::notice::Поле {field_name!r} не найдено в проекте — пропущено (см. bootstrap --create-fields).")
            return False
        option_id = definition["options"].get(option_name)
        if not option_id:
            emit(f"::notice::Вариант {option_name!r} отсутствует в поле {field_name!r} — пропущено.")
            return False
        _graphql(
            self.token,
            _SET_SINGLE_SELECT,
            {"project": self.id, "item": item_id, "field": definition["id"], "option": option_id},
        )
        return True

    def set_text(self, item_id: str, field_name: str, text: str) -> bool:
        definition = self.fields.get(field_name)
        if not definition:
            emit(f"::notice::Поле {field_name!r} не найдено в проекте — пропущено.")
            return False
        _graphql(self.token, _SET_TEXT, {"project": self.id, "item": item_id, "field": definition["id"], "text": text})
        return True

    def ensure_fields(self, plan: Plan) -> None:
        """Create the custom fields the sync writes to; unknown fields are left alone."""
        wanted = (
            (plan.field("gate", "Gate"), plan.gate_values or ["G0"], "SINGLE_SELECT"),
            (
                plan.field("size", "Size"),
                sorted({epic.size for epic in plan.epics if epic.size}) or ["M"],
                "SINGLE_SELECT",
            ),
            (plan.field("plan", "Plan"), [], "TEXT"),
            (plan.field("status", "Status"), list(STATUS_OPTIONS), "SINGLE_SELECT"),
        )
        for name, values, kind in wanted:
            if name in self.fields:
                continue
            if kind == "TEXT":
                _graphql(self.token, _CREATE_TEXT_FIELD, {"project": self.id, "name": name})
            else:
                options = [{"name": value, "color": "GRAY", "description": ""} for value in values]
                _graphql(
                    self.token, _CREATE_SINGLE_SELECT_FIELD, {"project": self.id, "name": name, "options": options}
                )
            emit(f"создано поле {name!r} ({len(values)} вариантов)" if kind != "TEXT" else f"создано поле {name!r}")
        self.fields = self._load_fields()
        missing = [
            plan.field(key, default)
            for key, default in (("status", "Status"), ("gate", "Gate"), ("size", "Size"), ("plan", "Plan"))
            if plan.field(key, default) not in self.fields
        ]
        if missing:
            emit(f"::warning::В проекте отсутствуют поля: {', '.join(missing)}")


def status_for(issue_state: str, labels: list[str]) -> str:
    """Board status derived from the issue itself, never from a plan snapshot."""
    if issue_state == "closed":
        return STATUS_DONE
    if "status:blocked" in labels:
        return STATUS_BLOCKED
    if "status:partial" in labels:
        return STATUS_IN_PROGRESS
    return STATUS_TODO


# --------------------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------------------


class Sync:
    def __init__(self, plan: Plan, repo: Repository, board: Board | None, *, dry_run: bool) -> None:
        self.plan = plan
        self.repo = repo
        self.board = board
        self.dry_run = dry_run
        self.actions = 0
        self.drift: list[str] = []

    def record_action(self, message: str) -> None:
        self.actions += 1
        emit(f"  {'·' if self.dry_run else '→'} {message}")

    def report_drift(self, message: str) -> None:
        self.drift.append(message)
        emit(f"  ! {message}")

    # -- structure --------------------------------------------------------------------

    def ensure_labels(self) -> None:
        existing = self.repo.labels()
        for label in self.plan.labels:
            name = str(label.get("name", ""))
            if not name:
                continue
            color = str(label.get("color", "ededed")).lstrip("#")
            description = str(label.get("description", ""))
            if name not in existing:
                if self.dry_run:
                    self.record_action(f"создать label {name}")
                else:
                    self.repo.create_label(name, color, description)
                    self.record_action(f"создан label {name}")
            elif (
                str(existing[name].get("color", "")).lower() != color.lower()
                or existing[name].get("description", "") != description
            ):
                if self.dry_run:
                    self.record_action(f"обновить label {name}")
                else:
                    self.repo.update_label(name, color, description)
                    self.record_action(f"обновлён label {name}")

    def check_labels(self) -> None:
        existing = self.repo.labels()
        for label in self.plan.labels:
            name = str(label.get("name", ""))
            if name and name not in existing:
                self.report_drift(f"label отсутствует: {name}")

    def ensure_milestones(self) -> dict[str, dict[str, Any]]:
        existing = self.repo.milestones()
        for milestone in self.plan.milestones:
            title = str(milestone.get("title", ""))
            if not title or title in existing:
                continue
            if self.dry_run:
                self.record_action(f"создать milestone {title}")
                existing[title] = {
                    "number": None,
                    "title": title,
                    "state": "open",
                    "open_issues": 0,
                    "closed_issues": 0,
                }
            else:
                existing[title] = self.repo.create_milestone(title, str(milestone.get("description", "")))
                self.record_action(f"создан milestone {title}")
        return existing

    def check_milestones(self) -> None:
        existing = self.repo.milestones()
        for milestone in self.plan.milestones:
            title = str(milestone.get("title", ""))
            if title and title not in existing:
                self.report_drift(f"milestone отсутствует: {title}")

    def find_epics(self) -> dict[str, dict[str, Any]]:
        """Existing tracker issues, keyed by epic key (matched through the body marker)."""
        found: dict[str, dict[str, Any]] = {}
        for number, issue in self.repo.issues(self.plan.tracker_label).items():
            body = issue.get("body") or ""
            for epic in self.plan.epics:
                if epic.marker in body:
                    found[epic.key] = {"number": number, "issue": issue}
        return found

    def ensure_epics(
        self, milestones: dict[str, dict[str, Any]], *, refresh_bodies: bool, enforce_state: bool
    ) -> dict[str, dict[str, Any]]:
        found = self.find_epics()
        for epic in self.plan.epics:
            milestone = milestones.get(epic.milestone) if epic.milestone else None
            milestone_number = None if milestone is None else milestone.get("number")
            if epic.milestone and milestone is None:
                self.report_drift(f"{epic.key}: milestone {epic.milestone!r} не найден в репозитории")
            if epic.key not in found:
                if self.dry_run:
                    self.record_action(f"создать issue {epic.key}: {epic.title}")
                    continue
                created = self.repo.create_issue(
                    title=epic.title,
                    body=render_body(epic, self.plan),
                    labels=list(epic.labels),
                    milestone=milestone_number,
                )
                self.record_action(f"создан issue #{created['number']} — {epic.title}")
                if epic.state == "closed":
                    self.repo.update_issue(created["number"], {"state": "closed", "state_reason": "completed"})
                    self.record_action(f"issue #{created['number']} закрыт (state: closed в плане)")
                found[epic.key] = {"number": created["number"], "issue": created}
                continue

            number = found[epic.key]["number"]
            issue = found[epic.key]["issue"]
            payload: dict[str, Any] = {}
            current_labels = [item["name"] for item in issue.get("labels", []) if isinstance(item, dict)]
            if set(epic.labels) - set(current_labels):
                payload["labels"] = sorted(set(current_labels) | set(epic.labels))
            if issue.get("title") != epic.title:
                payload["title"] = epic.title
            if (
                epic.milestone
                and (issue.get("milestone") or {}).get("title") != epic.milestone
                and milestone_number is not None
            ):
                payload["milestone"] = milestone_number
            if refresh_bodies:
                payload["body"] = render_body(epic, self.plan)
            if enforce_state and issue.get("state") != epic.state:
                payload["state"] = epic.state
                if epic.state == "closed":
                    payload["state_reason"] = "completed"
            if not payload:
                continue
            keys = ", ".join(sorted(payload))
            if self.dry_run:
                self.record_action(f"обновить issue #{number} ({keys})")
            else:
                self.repo.update_issue(number, payload)
                self.record_action(f"обновлён issue #{number} ({keys})")
        return found

    # -- board ------------------------------------------------------------------------

    def sync_board(self, found: dict[str, dict[str, Any]]) -> None:
        if self.board is None:
            return
        items = self.board.items()
        status_field = self.plan.field("status", "Status")
        gate_field = self.plan.field("gate", "Gate")
        size_field = self.plan.field("size", "Size")
        plan_field = self.plan.field("plan", "Plan")
        for epic in self.plan.epics:
            entry = found.get(epic.key)
            if entry is None:
                continue
            number = entry["number"]
            issue = entry.get("issue") or {}
            item_id = items.get(number)
            if not item_id:
                if self.dry_run:
                    self.record_action(f"добавить issue #{number} на доску")
                    continue
                node_id = issue.get("node_id")
                if not node_id:
                    self.report_drift(f"#{number}: нет node_id — невозможно добавить на доску")
                    continue
                item_id = self.board.add_item(node_id)
                self.record_action(f"issue #{number} добавлен на доску")
            labels = [item["name"] for item in issue.get("labels", []) if isinstance(item, dict)] or list(epic.labels)
            status = status_for(str(issue.get("state", "")), labels)
            if self.dry_run:
                self.record_action(
                    f"#{number}: Status={status}, Gate={epic.gate}, Size={epic.size}, Plan={self.plan.name}"
                )
                continue
            self.board.set_single_select(item_id, status_field, status)
            if epic.gate:
                self.board.set_single_select(item_id, gate_field, epic.gate)
            if epic.size:
                self.board.set_single_select(item_id, size_field, epic.size)
            self.board.set_text(item_id, plan_field, self.plan.name)

    def ensure_board_link(self) -> None:
        """Put the board into the repository's Projects tab (best effort, bootstrap only)."""
        if self.board is None or not self.plan.project_link_to_repo:
            return
        repository = _call("GET", f"{API_ROOT}/repos/{self.repo.owner}/{self.repo.name}", self.repo.token) or {}
        node_id = repository.get("node_id")
        if not node_id:
            self.report_drift("не удалось получить node_id репозитория для привязки доски")
            return
        if self.dry_run:
            self.record_action("привязать доску к репозиторию (Projects tab)")
            return
        try:
            self.board.link_repository(node_id)
        except ApiError as exc:
            # Linking needs admin on the repository; a failure here must not lose the sync.
            emit(f"::warning::не удалось привязать доску к репозиторию: {exc}")
            return
        self.record_action("доска привязана к репозиторию")

    def check_board(self, found: dict[str, dict[str, Any]]) -> None:
        for epic in self.plan.epics:
            if epic.key not in found:
                self.report_drift(f"{epic.key}: issue не создан (нужен bootstrap)")
        if self.board is None:
            self.report_drift("проект недоступен: состав доски и поля не проверены")
            return
        items = self.board.items()
        for epic in self.plan.epics:
            entry = found.get(epic.key)
            if entry is not None and entry["number"] not in items:
                self.report_drift(f"{epic.key}: issue #{entry['number']} отсутствует на доске")
        for key, default in (("status", "Status"), ("gate", "Gate"), ("size", "Size"), ("plan", "Plan")):
            name = self.plan.field(key, default)
            if name not in self.board.fields:
                self.report_drift(f"поле {name!r} не найдено в проекте")

    def close_finished_milestones(self) -> None:
        """A gate milestone closes itself once it has no open issues left."""
        existing = self.repo.milestones()
        for milestone in self.plan.milestones:
            title = str(milestone.get("title", ""))
            record = existing.get(title)
            if not record or record.get("state") == "closed" or not record.get("number"):
                continue
            if record.get("open_issues"):
                continue
            if not record.get("closed_issues"):
                continue  # an empty milestone stays open: it is a gate, not a finished gate
            if self.dry_run:
                self.record_action(f"закрыть milestone {title} (открытых пакетов не осталось)")
            else:
                self.repo.close_milestone(int(record["number"]))
                self.record_action(f"закрыт milestone {title} (открытых пакетов не осталось)")


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def read_token() -> str:
    token = (os.environ.get("PROJECTS_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        raise PlanError(
            "нет токена: задайте PROJECTS_TOKEN. Для проекта, принадлежащего пользователю, нужен classic PAT "
            "со scopes 'project' + 'repo'; для проекта организации — fine-grained PAT с "
            "'Organization permissions → Projects: Read and write' и 'Issues: Read and write'"
        )
    return token


def repo_slug(plan: Plan, explicit: str | None) -> tuple[str, str]:
    slug = explicit or os.environ.get("GITHUB_REPOSITORY") or ""
    if "/" not in slug:
        raise PlanError("не указан репозиторий: передайте --repo owner/name или задайте GITHUB_REPOSITORY")
    owner, _, name = slug.partition("/")
    return owner, name


def print_plan_summary(plan: Plan) -> None:
    emit(f"План {plan.name!r}: {len(plan.epics)} пакетов, {len(plan.milestones)} milestones, {len(plan.labels)} labels")
    for epic in plan.epics:
        state = "closed" if epic.state == "closed" else "open"
        slices = f"{epic.done_slices}/{len(epic.slices)}" if epic.slices else "—"
        emit(f"  [{state:6}] {epic.key:9} {epic.gate:7} {epic.size:2} срезы {slices:5} {epic.title}")


def print_offline_preview(plan: Plan, mode: str) -> None:
    """No token: still show exactly what bootstrap/sync would do with this plan."""
    emit("")
    emit("Токена нет — показываю план без обращения к GitHub:")
    emit(f"  labels:     создать/актуализировать {len(plan.labels)}")
    emit(f"  milestones: создать отсутствующие из {len(plan.milestones)}")
    if mode == "bootstrap":
        emit(f"  issues:     создать отсутствующие из {len(plan.epics)}")
    emit(f"  доска:      Status/Gate/Size/Plan для каждого пакета ({len(plan.epics)} элементов)")
    emit("")
    emit("Пакеты:")
    for epic in plan.epics:
        emit(f"  {epic.key:9} {epic.gate:7} {epic.size:2} {epic.milestone}")


def write_summary(path: Path, plan: Plan, found: dict[str, dict[str, Any]], drift: list[str]) -> None:
    """Append a markdown table to ``$GITHUB_STEP_SUMMARY`` so the run is readable in the UI."""
    lines = [
        "",
        f"### Трекер {plan.name}",
        "",
        "| Пакет | Gate | Размер | Milestone | Issue | Статус |",
        "|---|---|---|---|---|---|",
    ]
    for epic in plan.epics:
        entry = found.get(epic.key)
        if entry is None:
            lines.append(f"| `{epic.key}` | {epic.gate} | {epic.size} | {epic.milestone} | — | не создан |")
            continue
        issue = entry.get("issue") or {}
        labels = [item["name"] for item in issue.get("labels", []) if isinstance(item, dict)] or list(epic.labels)
        status = status_for(str(issue.get("state", "")), labels)
        lines.append(f"| `{epic.key}` | {epic.gate} | {epic.size} | {epic.milestone} | #{entry['number']} | {status} |")
    if drift:
        lines.extend(["", f"**Дрейф:** {len(drift)} расхождений"])
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError as exc:
        emit(f"::warning::не удалось записать summary {path}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "mode",
        choices=["bootstrap", "sync", "check"],
        help="bootstrap: создать структуру; sync: обновить доску; check: только проверка дрейфа",
    )
    parser.add_argument("--plan", type=Path, required=True, help="plan YAML, e.g. .github/tracker/qh-plan.yml")
    parser.add_argument("--repo", help="owner/name (по умолчанию GITHUB_REPOSITORY)")
    parser.add_argument("--project-number", type=int, help="номер Projects v2 (перебивает plan)")
    parser.add_argument("--project-title", help="точный заголовок проекта (перебивает plan)")
    parser.add_argument(
        "--create-project",
        action="store_true",
        help="создать доску, если её ещё нет (или project.create: true в плане)",
    )
    parser.add_argument(
        "--create-fields", action="store_true", help="bootstrap: создать отсутствующие поля Gate/Size/Plan/Status"
    )
    parser.add_argument("--refresh-bodies", action="store_true", help="перезаписать тело существующих issue из плана")
    parser.add_argument("--enforce-state", action="store_true", help="применить state из плана к существующим issue")
    parser.add_argument(
        "--summary", type=Path, help="куда дописать markdown-сводку (по умолчанию $GITHUB_STEP_SUMMARY)"
    )
    parser.add_argument("--dry-run", action="store_true", help="ничего не писать: показать, что было бы сделано")
    args = parser.parse_args(argv)

    try:
        plan = load_plan(args.plan)
    except PlanError as exc:
        emit(f"::error::{exc}")
        return 2

    if args.dry_run:
        emit("DRY-RUN: записи в GitHub не выполняются.")
    print_plan_summary(plan)

    try:
        token = read_token()
    except PlanError as exc:
        if args.mode == "check":
            emit(f"::warning::{exc}; дрейф не проверен.")
            return 2
        if args.dry_run:
            print_offline_preview(plan, args.mode)
            return 0
        emit(f"::error::{exc}")
        return 2

    try:
        owner, name = repo_slug(plan, args.repo)
    except PlanError as exc:
        emit(f"::error::{exc}")
        return 2

    repo = Repository(owner, name, token)
    board: Board | None = Board(
        token,
        plan.owner,
        args.project_number if args.project_number is not None else plan.project_number,
        args.project_title if args.project_title is not None else plan.project_title,
    )
    # A missing or unreachable project is a drift finding for `check` and a warning for a
    # dry-run, but a hard error when the run is actually supposed to write the board.
    tolerant = args.dry_run or args.mode == "check"
    # Creating a board is an explicit opt-in and never happens in check/dry-run.
    allow_create = (args.create_project or plan.project_create) and args.mode != "check" and not args.dry_run
    try:
        if not board.resolve(tolerant=tolerant, create=allow_create):
            board = None
    except PlanError as exc:
        if not tolerant:
            emit(f"::error::{exc}")
            return 2
        emit(f"::warning::{exc}")
        board = None
    if board is not None and board.id:
        emit(f"Проект: #{board.resolved_number} «{board.resolved_title}»")

    sync = Sync(plan, repo, board, dry_run=args.dry_run)
    found: dict[str, dict[str, Any]] = {}
    try:
        if args.mode == "check":
            emit("Структура:")
            sync.check_labels()
            sync.check_milestones()
            found = sync.find_epics()
            sync.check_board(found)
        elif args.mode == "bootstrap":
            emit("Labels:")
            sync.ensure_labels()
            emit("Milestones:")
            milestones = sync.ensure_milestones()
            if board is not None and args.create_fields and not args.dry_run:
                emit("Поля проекта:")
                board.ensure_fields(plan)
            emit("Issues:")
            found = sync.ensure_epics(milestones, refresh_bodies=args.refresh_bodies, enforce_state=args.enforce_state)
            emit("Доска:")
            sync.sync_board(found)
            sync.ensure_board_link()
            sync.close_finished_milestones()
        else:  # sync
            emit("Структура:")
            sync.check_labels()
            sync.check_milestones()
            emit("Issues:")
            found = sync.find_epics()
            for epic in plan.epics:
                if epic.key not in found:
                    sync.report_drift(f"{epic.key}: issue не создан (нужен bootstrap)")
            emit("Доска:")
            sync.sync_board(found)
            sync.close_finished_milestones()
    except ApiError as exc:
        emit(f"::error::{exc}{auth_hint(str(exc))}")
        return 1

    summary_path = args.summary or (
        Path(os.environ["GITHUB_STEP_SUMMARY"]) if os.environ.get("GITHUB_STEP_SUMMARY") else None
    )
    if summary_path is not None and not args.dry_run:
        write_summary(summary_path, plan, found, sync.drift)

    emit("")
    if sync.drift:
        emit(f"Дрейф: {len(sync.drift)} расхождений (строки '!' выше). Действий: {sync.actions}")
        return 1
    emit(f"Готово: {sync.actions} действий" + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
