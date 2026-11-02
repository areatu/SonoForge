"""#327: the viewer inspection seam is a frozen, reviewed allowlist.

The private-access ratchet counts references in ``test_*viewer*.py``; this file
is one of them, so it deliberately uses no ``obj._name`` access itself.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from echo_personal_tool.presentation.viewer_contract import EXPOSED_PRIVATE_NAMES, ViewerContract
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

REPO_ROOT = Path(__file__).parents[2]
ALLOWLIST = REPO_ROOT / "tests" / "architecture" / "viewer_contract_allowlist.json"


def _checker():
    path = REPO_ROOT / "scripts" / "check_test_private_access.py"
    spec = importlib.util.spec_from_file_location("check_test_private_access", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_exposed_names_are_exactly_the_reviewed_allowlist() -> None:
    data = json.loads(ALLOWLIST.read_text(encoding="utf-8"))

    assert data["origin_issue"] == 327
    assert set(EXPOSED_PRIVATE_NAMES) == set(data["facade"])
    assert len(data["facade"]) == len(set(data["facade"])), "duplicate entries must not hide a new name"
    assert not (set(EXPOSED_PRIVATE_NAMES) & set(data["promoted"]))
    assert not (set(EXPOSED_PRIVATE_NAMES) & set(data["other_objects"]))


def test_promoted_and_helper_names_are_all_declared() -> None:
    data = json.loads(ALLOWLIST.read_text(encoding="utf-8"))

    assert len(data["promoted"]) == 6
    assert all(name.startswith("_") and not public.startswith("_") for name, public in data["promoted"].items())
    assert len(data["other_objects"]) == 12
    assert all(
        name.startswith("_") and entry["public_name"] and entry["owner"]
        for name, entry in data["other_objects"].items()
    )


def test_the_adapter_maps_reads_and_writes_through_the_allowlist() -> None:
    dummy = SimpleNamespace(**{"_timeline_slider": 7})
    contract = ViewerContract(dummy)

    assert contract.timeline_slider == 7
    contract.timeline_slider = 9
    assert vars(dummy)["_timeline_slider"] == 9


def test_the_adapter_refuses_names_outside_the_allowlist() -> None:
    contract = ViewerContract(SimpleNamespace())

    with pytest.raises(AttributeError, match="reviewed allowlist"):
        _ = contract.not_declared

    with pytest.raises(AttributeError, match="reviewed allowlist"):
        contract.not_declared = 1


def test_viewer_widget_exposes_the_contract_property() -> None:
    assert isinstance(ViewerWidget.contract, property)


def test_viewer_test_files_have_zero_private_references() -> None:
    checker = _checker()

    found, errors = checker.scan(REPO_ROOT, checker.DEFAULT_SCOPE)

    assert errors == []
    assert sum(checker.file_counts(found).values()) == 0, "the ratchet must stay at zero"
