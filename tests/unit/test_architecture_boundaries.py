"""QH-4b ratchet for direct domain -> infrastructure imports.

The reviewed baseline is now **zero** edges (G4 §8.2).  Every historical edge
was inverted or relocated behind an adapter:

* formatter instrumentation dropped from the domain (profiling stays outside);
* Samsung tick detection and pixel normalization moved to the pure
  ``echo_personal_tool.imaging`` kernel;
* the DICOM panel adapter is called by the application, the domain receives
  the parsed ``FramePanelLayout``;
* cine diagnostics and the LVEF bench pairing moved to ``application/services``.

Any new domain edge fails here. The domain baseline is intentionally empty.
The separate presentation -> infrastructure ratchet uses the issue #307
allowlist in ``tests/architecture/presentation_infrastructure_allowlist.json``;
it requires an exact match so both new imports and stale exceptions fail.

Issue 328 adds the last guard of the set: the package import graph has **no
cycles** (strongly connected components of more than one module). The reviewed
baseline is zero, so there is no allowlist to grow; see
``test_import_graph_has_no_cycles`` for what counts as an import.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).parents[2] / "src"
_DOMAIN_ROOT = _SRC_ROOT / "echo_personal_tool" / "domain"
_IMAGING_ROOT = _SRC_ROOT / "echo_personal_tool" / "imaging"
_APPLICATION_ROOT = _SRC_ROOT / "echo_personal_tool" / "application"
_PRESENTATION_ROOT = _SRC_ROOT / "echo_personal_tool" / "presentation"
_PRESENTATION_VIEWER_ROOT = _PRESENTATION_ROOT / "viewer"
_PRESENTATION_INFRA_ALLOWLIST = (
    Path(__file__).parents[1] / "architecture" / "presentation_infrastructure_allowlist.json"
)

# Exact domain -> infrastructure debt inventory. Do not add entries to make a
# new import pass; the target and current state are both zero direct edges.
_EXPECTED_EDGES: frozenset[tuple[str, str]] = frozenset()
_FORBIDDEN_PREFIXES = (
    "echo_personal_tool.infrastructure",
    "echo_personal_tool.presentation",
    "echo_personal_tool.application",
)


def _resolves_to_forbidden(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in prefixes)


def _import_edges(root: Path, prefixes: tuple[str, ...], *, src_root: Path | None = None) -> frozenset[tuple[str, str]]:
    """Inventory absolute, relative and package-level imports of ``prefixes``.

    ``from ..infrastructure.x import y`` and ``from echo_personal_tool import
    infrastructure`` are as real as an absolute module import, so they are
    resolved against the importing module instead of being silently skipped.
    """
    base_root = src_root if src_root is not None else _SRC_ROOT
    edges: set[tuple[str, str]] = set()
    for source in root.rglob("*.py"):
        relative = source.relative_to(base_root).as_posix()
        module_path = source.relative_to(base_root).with_suffix("").parts
        package = list(module_path[:-1])
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    keep = len(package) - (node.level - 1)
                    anchor = package[: max(keep, 0)]
                    if node.module:
                        modules.append(".".join([*anchor, node.module]))
                    else:
                        modules.extend(".".join([*anchor, alias.name]) for alias in node.names)
                elif node.module:
                    modules.append(node.module)
                    if node.module == "echo_personal_tool":
                        modules.extend(f"echo_personal_tool.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                if _resolves_to_forbidden(module, prefixes):
                    edges.add((relative, module))
    return frozenset(edges)


def _reviewed_presentation_infrastructure_edges() -> frozenset[tuple[str, str]]:
    """Load reviewed direct edges and require reason + tracking issue per group."""
    payload = json.loads(_PRESENTATION_INFRA_ALLOWLIST.read_text(encoding="utf-8"))
    assert payload.get("origin_issue") == 307
    entries = payload.get("entries")
    assert isinstance(entries, dict)

    edges: set[tuple[str, str]] = set()
    for module, entry in entries.items():
        assert module.startswith("echo_personal_tool.infrastructure."), module
        assert isinstance(entry, dict), module
        assert isinstance(entry.get("reason"), str) and entry["reason"].strip(), module
        assert type(entry.get("issue")) is int and entry["issue"] > 0, module
        sources = entry.get("sources")
        assert isinstance(sources, list) and sources, module
        for source in sources:
            assert isinstance(source, str) and source.startswith("echo_personal_tool/presentation/"), source
            edge = (source, module)
            assert edge not in edges, f"duplicate presentation/infrastructure edge: {edge}"
            edges.add(edge)
    return frozenset(edges)


def test_domain_has_no_untracked_infrastructure_edges() -> None:
    actual = _import_edges(_DOMAIN_ROOT, ("echo_personal_tool.infrastructure",))
    added = sorted(actual - _EXPECTED_EDGES)
    removed = sorted(_EXPECTED_EDGES - actual)
    assert not added and not removed, (
        "domain -> infrastructure boundary changed; new edges are forbidden and removed debt "
        f"must shrink the reviewed inventory. Added: {added}; removed: {removed}; target is zero."
    )
    assert actual == frozenset(), f"domain must not import infrastructure at all: {sorted(actual)}"


def test_domain_only_depends_on_domain_imaging_and_stdlib() -> None:
    """G4 §8.2: domain never reaches into application/presentation either."""
    offenders = sorted(_import_edges(_DOMAIN_ROOT, _FORBIDDEN_PREFIXES[1:]))
    assert offenders == [], "domain must not import application/presentation:\n" + "\n".join(
        f"{source} -> {module}" for source, module in offenders
    )


def test_imaging_kernel_is_independent_of_layers() -> None:
    """The shared algorithmic kernel must stay free of I/O and layer imports."""
    offenders = sorted(
        _import_edges(
            _IMAGING_ROOT,
            (
                "echo_personal_tool.domain",
                "echo_personal_tool.application",
                "echo_personal_tool.infrastructure",
                "echo_personal_tool.presentation",
            ),
        )
    )
    assert offenders == [], "imaging must stay a pure algorithmic kernel:\n" + "\n".join(
        f"{source} -> {module}" for source, module in offenders
    )


def test_application_does_not_import_presentation_or_ui() -> None:
    """G4 §8.2: application layer must never import presentation, ui, or constructor."""
    offenders = sorted(
        _import_edges(
            _APPLICATION_ROOT,
            (
                "echo_personal_tool.presentation",
                "echo_personal_tool.ui",
                "echo_personal_tool.constructor",
            ),
        )
    )
    assert offenders == [], "application must not import presentation/ui/constructor:\n" + "\n".join(
        f"{source} -> {module}" for source, module in offenders
    )


def test_application_io_facades_have_no_qt_imports() -> None:
    """Application I/O facades stay importable without pulling Qt into application."""
    sources = tuple(
        _APPLICATION_ROOT / name
        for name in (
            "dicom_export.py",
            "dicom_io.py",
            "diagnostics.py",
            "localization.py",
            "profile_settings.py",
            "recent_folders.py",
            "report_export.py",
            "report_phrases.py",
            "server_io.py",
            "user_preferences.py",
        )
    )
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        qt_imports = sorted(
            module
            for module in imports
            if module == "PySide6"
            or module.startswith("PySide6.")
            or module == "PyQt6"
            or module.startswith("PyQt6.")
            or module == "PyQt5"
            or module.startswith("PyQt5.")
        )
        assert qt_imports == [], f"application facade {source.name} must not import Qt: {qt_imports}"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "import echo_personal_tool.application.user_preferences; "
            "assert 'echo_personal_tool.infrastructure.user_preferences' not in sys.modules; "
            "import echo_personal_tool.application.profile_settings; "
            "assert 'echo_personal_tool.infrastructure.profile' not in sys.modules; "
            "import echo_personal_tool.application.dicom_export; "
            "import echo_personal_tool.application.dicom_io; "
            "import echo_personal_tool.application.recent_folders; "
            "import echo_personal_tool.application.report_export; "
            "import echo_personal_tool.application.report_phrases; "
            "import echo_personal_tool.application.server_io; "
            "import echo_personal_tool.application.localization; "
            "import echo_personal_tool.application.diagnostics; "
            "assert not any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules); "
            "assert 'echo_personal_tool.infrastructure.dicom_session' not in sys.modules; "
            "assert 'echo_personal_tool.infrastructure.dicom_tag_inspector' not in sys.modules; "
            "assert 'echo_personal_tool.infrastructure.dicom_metadata_mapper' not in sys.modules; "
            "assert 'echo_personal_tool.infrastructure.recent_store' not in sys.modules; "
            "assert 'echo_personal_tool.infrastructure.report_phrase_store' not in sys.modules",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, f"application I/O facade violated its import boundary: {result.stderr}"


def test_presentation_has_only_reviewed_infrastructure_imports() -> None:
    """New edges fail; retired edges must be deleted from the exact allowlist."""
    actual = _import_edges(_PRESENTATION_ROOT, ("echo_personal_tool.infrastructure",))
    expected = _reviewed_presentation_infrastructure_edges()
    added = sorted(actual - expected)
    retired = sorted(expected - actual)
    assert not added and not retired, (
        "presentation -> infrastructure must match the reviewed, shrinking allowlist. "
        "New imports are forbidden and migrated imports must be removed from the inventory. "
        f"Added: {added}; retired/stale: {retired}"
    )


def test_viewer_controllers_do_not_import_main_window_or_infrastructure_io() -> None:
    """G3 / G4 §8.2: viewer controllers must not use MainWindow as service locator or import I/O adapters."""
    offenders = sorted(
        _import_edges(
            _PRESENTATION_VIEWER_ROOT,
            (
                "echo_personal_tool.presentation.main_window",
                "echo_personal_tool.infrastructure.dicom_reader",
                "echo_personal_tool.infrastructure.dicom_session",
                "echo_personal_tool.infrastructure.onnx_worker",
                "echo_personal_tool.application.workers.onnx_worker",
                "echo_personal_tool.application.workers.dicom_decode_worker",
            ),
        )
    )
    assert offenders == [], "viewer controllers must stay pure of MainWindow/I-O adapters:\n" + "\n".join(
        f"{source} -> {module}" for source, module in offenders
    )


def test_ratchet_detects_relative_and_package_level_imports(tmp_path: Path) -> None:
    """Guard the guard: relative imports must not slip past the inventory."""
    domain = tmp_path / "echo_personal_tool" / "domain"
    domain.mkdir(parents=True)
    (domain / "relative.py").write_text("from ..infrastructure.profiler import profiled\n", encoding="utf-8")
    (domain / "package_level.py").write_text("from echo_personal_tool import infrastructure\n", encoding="utf-8")
    (domain / "clean.py").write_text("from . import sibling\n", encoding="utf-8")

    edges = _import_edges(domain, ("echo_personal_tool.infrastructure",), src_root=tmp_path)

    assert edges == frozenset(
        {
            ("echo_personal_tool/domain/package_level.py", "echo_personal_tool.infrastructure"),
            ("echo_personal_tool/domain/relative.py", "echo_personal_tool.infrastructure.profiler"),
        }
    )

    presentation = tmp_path / "echo_personal_tool" / "presentation"
    presentation.mkdir(parents=True)
    (presentation / "relative.py").write_text("from ..infrastructure.profiler import profiled\n", encoding="utf-8")
    (presentation / "package_level.py").write_text("from echo_personal_tool import infrastructure\n", encoding="utf-8")
    presentation_edges = _import_edges(presentation, ("echo_personal_tool.infrastructure",), src_root=tmp_path)
    assert presentation_edges == frozenset(
        {
            ("echo_personal_tool/presentation/package_level.py", "echo_personal_tool.infrastructure"),
            ("echo_personal_tool/presentation/relative.py", "echo_personal_tool.infrastructure.profiler"),
        }
    )


# ── Issue 328: the import graph has no cycles ───────────────────────────────

_PACKAGE = "echo_personal_tool"


def _package_modules(src_root: Path | None = None) -> dict[str, Path]:
    """Every module of the package by dotted name; a package is its ``__init__``."""
    base = src_root if src_root is not None else _SRC_ROOT
    modules: dict[str, Path] = {}
    for source in (base / _PACKAGE).rglob("*.py"):
        parts = list(source.relative_to(base).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = source
    return modules


def _referenced_modules(node: ast.AST, package: list[str]) -> Iterator[str]:
    """Dotted names an import statement can refer to: the module and, for ``from x import y``, ``x.y``.

    A relative ``from . import y`` names no package, only the submodules ``y``.
    """
    if isinstance(node, ast.ImportFrom):
        if node.level:
            anchor = package[: max(len(package) - (node.level - 1), 0)]
            base = ".".join([*anchor, node.module]) if node.module else ""
            if base:
                yield base
        elif node.module:
            base = node.module
            yield base
        else:
            return
        prefix = base or ".".join(package[: max(len(package) - (node.level - 1), 0)])
        for alias in node.names:
            yield f"{prefix}.{alias.name}"
    elif isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name


def _import_graph(src_root: Path | None = None) -> dict[str, dict[str, int]]:
    """``module -> {imported module of the package: line of the import}``.

    Every import counts: at module level, inside a function and under
    ``TYPE_CHECKING``. A lazy import hides a cycle from the import system, not
    from the architecture, and a typing-only import still makes two modules
    impossible to understand or test apart.
    """
    modules = _package_modules(src_root)
    graph: dict[str, dict[str, int]] = {}
    for name, source in modules.items():
        package = name.split(".") if source.name == "__init__.py" else name.split(".")[:-1]
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        edges: dict[str, int] = {}
        for node in ast.walk(tree):
            for target in _referenced_modules(node, package):
                if target in modules and target != name:
                    edges.setdefault(target, node.lineno)
        graph[name] = edges
    return graph


def _strongly_connected_components(graph: Mapping[str, Iterable[str]]) -> list[frozenset[str]]:
    """Tarjan's algorithm, iterative; only components of more than one module."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[frozenset[str]] = []
    counter = 0
    for root in graph:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work: list[tuple[str, Iterator[str]]] = [(root, iter(sorted(graph.get(root, ()))))]
        while work:
            node, children = work[-1]
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(graph.get(child, ())))))
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    members: list[str] = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        members.append(member)
                        if member == node:
                            break
                    if len(members) > 1:
                        components.append(frozenset(members))
    return components


def _shortest_cycle(graph: Mapping[str, Mapping[str, int]], component: frozenset[str]) -> list[str]:
    """A shortest cycle inside ``component`` as ``[a, b, ..., a]``."""
    best: list[str] = []
    for start in sorted(component):
        previous: dict[str, str] = {}
        queue: deque[str] = deque([start])
        found = False
        while queue and not found:
            node = queue.popleft()
            for child in sorted(graph[node]):
                if child == start:
                    path = [node]
                    while path[-1] != start:
                        path.append(previous[path[-1]])
                    cycle = [*reversed(path), start]
                    best = cycle if not best or len(cycle) < len(best) else best
                    found = True
                    break
                if child in component and child not in previous and child != start:
                    previous[child] = node
                    queue.append(child)
    return best


def _describe_cycle(
    graph: Mapping[str, Mapping[str, int]], component: frozenset[str], src_root: Path | None = None
) -> str:
    """The members and one shortest cycle, every hop with the file and line that creates it."""
    paths = _package_modules(src_root)
    base = src_root if src_root is not None else _SRC_ROOT
    cycle = _shortest_cycle(graph, component)
    hops = [
        f"    {source} -> {target}  ({paths[source].relative_to(base).as_posix()}:{graph[source][target]})"
        for source, target in zip(cycle, cycle[1:], strict=False)
    ]
    return f"{len(component)} modules: {', '.join(sorted(component))}\n  one shortest cycle:\n" + "\n".join(hops)


def _cycles_of(src_root: Path | None = None) -> tuple[dict[str, dict[str, int]], list[frozenset[str]]]:
    graph = _import_graph(src_root)
    components = _strongly_connected_components({name: edges.keys() for name, edges in graph.items()})
    return graph, sorted(components, key=lambda component: sorted(component))


def test_import_graph_has_no_cycles() -> None:
    """Issue 328: no group of modules imports one another in a circle.

    The reviewed baseline was eight cycles (the report layer, the calculators, the
    preferences facade, the theme, ...) and is now zero, so any new component of
    more than one module fails here. Break it with a leaf module both sides can
    import, a ``Protocol`` for what one side needs from the other, or a
    registration hook that the consumer calls instead of the owner importing it.
    """
    graph, cycles = _cycles_of()

    assert not cycles, "new import cycle(s):\n\n" + "\n\n".join(_describe_cycle(graph, cycle) for cycle in cycles)


def test_the_cycle_scanner_sees_the_whole_package() -> None:
    """Guard the guard: a scanner that silently finds nothing would pass the check above."""
    graph = _import_graph()

    assert len(graph) > 400
    assert sum(len(edges) for edges in graph.values()) > 1000


def _write_package(root: Path, files: dict[str, str]) -> Path:
    """A throwaway ``echo_personal_tool`` package; every directory becomes a package."""
    for relative, source in {"__init__.py": "", **files}.items():
        target = root / _PACKAGE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    for directory in (root / _PACKAGE).rglob("*"):
        if directory.is_dir() and not (directory / "__init__.py").exists():
            (directory / "__init__.py").write_text("", encoding="utf-8")
    return root


_A_AND_B = frozenset({f"{_PACKAGE}.a", f"{_PACKAGE}.b"})


@pytest.mark.parametrize(
    ("a_source", "b_source"),
    [
        ("from echo_personal_tool.b import y\n", "from echo_personal_tool.a import x\n"),
        ("def f():\n    from echo_personal_tool.b import y\n", "from echo_personal_tool.a import x\n"),
        (
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from echo_personal_tool.b import Y\n",
            "import echo_personal_tool.a\n",
        ),
        ("from .b import y\n", "from .a import x\n"),
        ("from . import b\n", "from . import a\n"),
        ("import echo_personal_tool.b as b\n", "from echo_personal_tool import a\n"),
    ],
    ids=["module-level", "inside-a-function", "type-checking", "relative-module", "relative-package", "import-as"],
)
def test_the_cycle_scanner_sees_every_form_of_import(tmp_path: Path, a_source: str, b_source: str) -> None:
    root = _write_package(tmp_path, {"a.py": a_source, "b.py": b_source})

    _graph, cycles = _cycles_of(root)

    assert cycles == [_A_AND_B]


def test_a_package_facade_and_its_own_submodule_importing_it_form_a_cycle(tmp_path: Path) -> None:
    """The report-mode shape: ``__init__`` re-exports ``preview``, ``preview`` imports the package root."""
    root = _write_package(
        tmp_path,
        {
            "pkg/__init__.py": "from echo_personal_tool.pkg.preview import Preview\n",
            "pkg/preview.py": "from echo_personal_tool.pkg import view_map\n",
            "pkg/view_map.py": "",
        },
    )

    _graph, cycles = _cycles_of(root)

    assert cycles == [frozenset({f"{_PACKAGE}.pkg", f"{_PACKAGE}.pkg.preview"})]


def test_importing_the_submodule_by_its_full_name_does_not_go_through_the_facade(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path,
        {
            "pkg/__init__.py": "from echo_personal_tool.pkg.preview import Preview\n",
            "pkg/preview.py": "import echo_personal_tool.pkg.view_map as view_map\n",
            "pkg/view_map.py": "",
        },
    )

    _graph, cycles = _cycles_of(root)

    assert cycles == []


def test_acyclic_foreign_and_self_imports_are_not_cycles(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path,
        {
            "a.py": "from echo_personal_tool.b import x\nfrom echo_personal_tool.c import y\n",
            "b.py": "from echo_personal_tool.d import z\nimport numpy\n",
            "c.py": "from echo_personal_tool.d import z\n",
            "d.py": "import echo_personal_tool.d\nimport os\n",
        },
    )

    graph, cycles = _cycles_of(root)

    assert cycles == []
    assert set(graph[f"{_PACKAGE}.a"]) == {f"{_PACKAGE}.b", f"{_PACKAGE}.c"}
    assert graph[f"{_PACKAGE}.d"] == {}


def test_the_cycle_report_names_a_shortest_cycle_with_file_and_line(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path,
        {
            "a.py": "import os\nfrom echo_personal_tool.b import x\nfrom echo_personal_tool.c import y\n",
            "b.py": "from echo_personal_tool.c import y\n",
            "c.py": "\n\nfrom echo_personal_tool.a import x\n",
        },
    )
    graph, cycles = _cycles_of(root)

    assert len(cycles) == 1
    report = _describe_cycle(graph, cycles[0], root)

    assert report.startswith("3 modules: echo_personal_tool.a, echo_personal_tool.b, echo_personal_tool.c")
    assert "echo_personal_tool.a -> echo_personal_tool.c  (echo_personal_tool/a.py:3)" in report
    assert "echo_personal_tool.c -> echo_personal_tool.a  (echo_personal_tool/c.py:3)" in report
    assert "echo_personal_tool.b" not in report.split("one shortest cycle:")[1], "the shortcut a -> c -> a wins"
