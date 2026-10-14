"""Write a machine-readable inventory for split pytest CI selections.

Two sections are produced in ``$PYTEST_CI_METRICS_FILE``:

* ``collected`` / ``eligible_not_interactive`` / ``selected`` — the item
  inventory, snapshotted before marker deselection and compared with the
  selected list afterwards.  Under pytest-xdist worker gw0 writes it; every
  worker repeats collection by design.
* ``outcomes`` / ``skip_reasons`` / ``collection_errors`` / ``exit_status`` —
  the per-node run evidence (QH-2a.1, S-12).  The controller (or the plain
  single-process run) owns these: it receives every worker's test reports.
  ``check_required_tests.py`` consumes them so that a required scenario is
  only ever closed by a test that was collected *and* passed — a missing,
  skipped or xfailed required test is not a PASS.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

#: nodeid -> passed | failed | skipped | xfailed | xpassed | error
_OUTCOMES: dict[str, str] = {}
_SKIP_REASONS: dict[str, str] = {}
_COLLECTION_ERRORS: list[str] = []


def _has_marker(item: Any, name: str) -> bool:
    return item.get_closest_marker(name) is not None


def _counts(items: tuple[Any, ...]) -> dict[str, int]:
    gui_items = tuple(item for item in items if _has_marker(item, "gui"))
    not_gui_items = tuple(item for item in items if not _has_marker(item, "gui"))
    interactive = sum(_has_marker(item, "interactive") for item in items)
    return {
        "total": len(items),
        "gui": len(gui_items),
        "not_gui": len(not_gui_items),
        "interactive": interactive,
        "gui_files": len({str(item.path) for item in gui_items}),
        "not_gui_files": len({str(item.path) for item in not_gui_items}),
    }


def _metrics_path() -> Path | None:
    destination = os.environ.get("PYTEST_CI_METRICS_FILE")
    return Path(destination) if destination else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_inventory(inventory: dict[str, Any]) -> None:
    path = _metrics_path()
    if path is None:
        return
    _write_json(path, inventory)


def _is_xdist_worker() -> bool:
    return os.environ.get("PYTEST_XDIST_WORKER") is not None


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[Any]):
    """Record all collected items and the marker-filtered selection."""
    del session, config
    collected = tuple(items)
    yield

    # xdist's controller does not run collection hooks on a collected item
    # list. Each worker does; gw0 publishes the identical complete inventory,
    # while the remaining workers leave the artifact untouched.
    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    if worker_id is not None and worker_id != "gw0":
        return

    selected_ids = {item.nodeid for item in items}
    selected = tuple(item for item in collected if item.nodeid in selected_ids)
    collected_counts = _counts(collected)
    eligible = tuple(item for item in collected if not _has_marker(item, "interactive"))
    eligible_counts = _counts(eligible)
    selected_counts = _counts(selected)

    _write_inventory(
        {
            "collected": collected_counts,
            "eligible_not_interactive": eligible_counts,
            "selected": selected_counts,
        }
    )


# ── run evidence ────────────────────────────────────────────────────


def _classify(report: Any) -> str | None:
    """Map one phase report onto the terminal-summary vocabulary.

    ``None`` means "nothing to record for this phase" (a passing setup or
    teardown): the call phase decides.  An xfail that never runs
    (``run=False``) is reported from setup, so it is classified there too.
    """
    if report.when == "call":
        if hasattr(report, "wasxfail"):
            return "xfailed" if report.skipped else "xpassed"
        return str(report.outcome)
    if report.when == "setup":
        if report.failed:
            return "error"
        if report.skipped:
            return "xfailed" if hasattr(report, "wasxfail") else "skipped"
        return None
    return "error" if report.failed else None


def _skip_reason(report: Any) -> str:
    longrepr = getattr(report, "longrepr", None)
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr or "")


def pytest_runtest_logreport(report: Any) -> None:
    """Keep the final outcome of every executed node (controller-side under xdist)."""
    if _is_xdist_worker():
        return
    outcome = _classify(report)
    if outcome is None:
        return
    # A teardown error overrides anything; the call phase overrides the
    # setup phase; a setup record only stands when nothing else arrives.
    if outcome == "error" or report.when == "call" or report.nodeid not in _OUTCOMES:
        _OUTCOMES[report.nodeid] = outcome
    if outcome in ("skipped", "xfailed"):
        _SKIP_REASONS[report.nodeid] = _skip_reason(report)


def pytest_collectreport(report: Any) -> None:
    if _is_xdist_worker():
        return
    if report.failed:
        _COLLECTION_ERRORS.append(str(report.nodeid))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Merge the run evidence into the inventory file (plain run or xdist controller)."""
    del session
    if _is_xdist_worker():
        return
    path = _metrics_path()
    if path is None:
        return
    payload: dict[str, Any] = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
    payload["outcomes"] = dict(sorted(_OUTCOMES.items()))
    payload["skip_reasons"] = dict(sorted(_SKIP_REASONS.items()))
    payload["collection_errors"] = list(_COLLECTION_ERRORS)
    payload["exit_status"] = int(exitstatus)
    _write_json(path, payload)
