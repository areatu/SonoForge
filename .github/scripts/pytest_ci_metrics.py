"""Write a machine-readable inventory for split pytest CI selections.

The hook snapshots the complete collected item list before marker deselection,
then compares it with the selected list afterwards. Under pytest-xdist worker
gw0 writes the report; every worker repeats collection by design.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest


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


def _write_inventory(inventory: dict[str, Any]) -> None:
    destination = os.environ.get("PYTEST_CI_METRICS_FILE")
    if not destination:
        return

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


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
