"""#419: the direction of a cross-layer import is its own architecture gate.

The no-cycles test proves acyclicity; an acyclic ``infrastructure -> application``
edge is still the wrong dependency. These tests pin the AST inventory, the
exact reviewed baseline, and the failure modes of the ratchet.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parents[2]

_spec = importlib.util.spec_from_file_location("check_layer_directions", _ROOT / "scripts/check_layer_directions.py")
assert _spec is not None and _spec.loader is not None
cld = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cld
_spec.loader.exec_module(cld)


def _write_package(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "echo_personal_tool"
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _baseline(entries: list[dict[str, object]]) -> dict[str, object]:
    return {"origin_issue": 419, "decisions": {}, "entries": entries}


def test_the_committed_inventory_matches_the_reviewed_baseline() -> None:
    edges = cld.inventory(cld.DEFAULT_ROOT)
    data, baseline_problems = cld.load_allowlist(cld.DEFAULT_ALLOWLIST)

    assert cld.check(edges, data, baseline_problems) == []
    assert {edge.direction for edge in edges} == set(cld.FORBIDDEN)
    assert len(edges) == 29, "the AST inventory must not silently become empty"
    assert all(edge.source_file.endswith(".py") and edge.line > 0 for edge in edges)


def test_allowed_directions_are_not_gated(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path,
        {
            "presentation/shell.py": "from echo_personal_tool.ui.strain_window import StrainWindow\n",
            "application/facade.py": "from echo_personal_tool.infrastructure.dimse_client import DimseClient\n",
            "infrastructure/adapter.py": "from echo_personal_tool.domain.models import Frame\n",
        },
    )

    assert cld.inventory(root) == []


def test_new_forbidden_edge_is_reported_with_file_and_line(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path,
        {"infrastructure/probe.py": "import os\nfrom echo_personal_tool.application.transport_policy import policy\n"},
    )

    edges = cld.inventory(root)
    assert [(edge.line, edge.dest_module, edge.kind) for edge in edges] == [
        (2, "echo_personal_tool.application.transport_policy", "module")
    ]
    problems = cld.check(edges, _baseline([]), [])
    assert any(
        "NEW forbidden edge" in problem
        and "echo_personal_tool/infrastructure/probe.py:2" in problem
        and "application.transport_policy" in problem
        for problem in problems
    )


def test_relative_and_package_level_imports_are_inventoried(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path,
        {"infrastructure/probe.py": ("from ..application import policy\nfrom echo_personal_tool import application\n")},
    )

    edges = cld.inventory(root)
    assert [(edge.line, edge.dest_module) for edge in edges] == [
        (1, "echo_personal_tool.application"),
        (2, "echo_personal_tool.application"),
    ]


def test_type_only_and_lazy_imports_are_gated_but_classified(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path,
        {
            "infrastructure/probe.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    from echo_personal_tool.application import policy\n"
                "def build():\n"
                "    from echo_personal_tool.application import service\n"
                "    return service\n"
            )
        },
    )

    edges = cld.inventory(root)
    assert sorted(edge.kind for edge in edges) == ["lazy", "type-only"]
    assert all(edge.direction == "infrastructure>application" for edge in edges)


def test_a_second_import_of_an_existing_edge_is_growth(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path,
        {
            "infrastructure/probe.py": (
                "from echo_personal_tool.application import a\nfrom echo_personal_tool.application import b\n"
            )
        },
    )
    data = _baseline(
        [
            {
                "direction": "infrastructure>application",
                "source": "echo_personal_tool/infrastructure/probe.py",
                "imports": {"echo_personal_tool.application": 1},
                "reason": "reviewed historical edge",
                "issue": 419,
            }
        ]
    )

    problems = cld.check(cld.inventory(root), data, [])
    assert any("GROWN forbidden edge" in problem and "1 -> 2 import(s)" in problem for problem in problems)


def test_a_stale_baseline_entry_fails(tmp_path: Path) -> None:
    root = _write_package(tmp_path, {"infrastructure/probe.py": "import os\n"})
    data = _baseline(
        [
            {
                "direction": "ui>presentation",
                "source": "echo_personal_tool/ui/gone.py",
                "imports": {"echo_personal_tool.presentation.ui_metrics": 1},
                "reason": "removed in a follow-up slice",
                "issue": 419,
            }
        ]
    )

    problems = cld.check(cld.inventory(root), data, [])
    assert any("STALE baseline edge" in problem and "ui/gone.py" in problem for problem in problems)


def test_an_allowlist_entry_without_a_reason_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.json"
    path.write_text(
        json.dumps(
            {
                "origin_issue": 419,
                "decisions": {name: "forbidden" for name in cld.FORBIDDEN}
                | {"presentation>ui": "allowed composition", "application>infrastructure": "allowed facade"},
                "entries": [
                    {
                        "direction": "ui>presentation",
                        "source": "echo_personal_tool/ui/probe.py",
                        "imports": {"echo_personal_tool.presentation.ui_metrics": 1},
                        "issue": 419,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    _data, problems = cld.load_allowlist(path)
    assert any("has no reviewed reason" in problem for problem in problems)


def test_facade_reexport_of_infrastructure_symbol_is_detected(tmp_path: Path) -> None:
    """#477: ``Dto = _adapter.Dto`` or ``__all__`` re-export in ``application`` fails unless reviewed."""
    root = _write_package(
        tmp_path,
        {
            "infrastructure/adapter.py": "class AdapterDto:\n    pass\n",
            "application/facade.py": (
                "from echo_personal_tool.infrastructure import adapter as _adapter\nDto = _adapter.AdapterDto\n"
            ),
            "presentation/dialog.py": "from echo_personal_tool.application.facade import Dto\n",
        },
    )

    reexports, indirect_uses = cld.scan_facade_contracts(root)
    problems = cld.check_facade_contracts(reexports, indirect_uses, _baseline([]))

    assert any("NEW facade re-export" in p and "facade.py:2 Dto" in p for p in problems)
    assert any("NEW indirect presentation->infrastructure use" in p and "dialog.py:1" in p for p in problems)


def test_indirect_presentation_import_of_internal_facade_binding_fails(tmp_path: Path) -> None:
    """#477: ``presentation`` importing an internal ``infrastructure`` import from ``application`` fails."""
    root = _write_package(
        tmp_path,
        {
            "infrastructure/codec.py": "class StorageError(Exception):\n    pass\n",
            "application/records.py": (
                "from echo_personal_tool.infrastructure.codec import StorageError\n"
                "__all__ = ['load_record']\n"
                "def load_record() -> None:\n"
                "    return None\n"
            ),
            "presentation/window.py": "from echo_personal_tool.application.records import StorageError\n",
        },
    )

    reexports, indirect_uses = cld.scan_facade_contracts(root)
    problems = cld.check_facade_contracts(reexports, indirect_uses, _baseline([]))

    assert reexports == []
    assert any("NEW indirect presentation->infrastructure use" in p and "StorageError" in p for p in problems)


def test_application_owned_class_and_wrapper_pass_facade_gate(tmp_path: Path) -> None:
    """#477: app-owned dataclasses/Protocols and ``def`` wrappers do not leak ``infrastructure``."""
    root = _write_package(
        tmp_path,
        {
            "infrastructure/adapter.py": "class Settings:\n    pass\n",
            "application/server_io.py": (
                "from dataclasses import dataclass\n"
                "from echo_personal_tool.infrastructure import adapter as _adapter\n"
                "@dataclass\n"
                "class Settings:\n"
                "    host: str = ''\n"
                "def load_settings() -> Settings:\n"
                "    _ = _adapter.Settings\n"
                "    return Settings()\n"
                "__all__ = ['Settings', 'load_settings']\n"
            ),
            "presentation/dialog.py": "from echo_personal_tool.application.server_io import Settings, load_settings\n",
        },
    )

    reexports, indirect_uses = cld.scan_facade_contracts(root)

    assert reexports == []
    assert indirect_uses == []
    assert cld.check_facade_contracts(reexports, indirect_uses, _baseline([])) == []
