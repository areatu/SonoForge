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
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

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
            "recent_folders.py",
            "report_export.py",
            "report_phrases.py",
            "server_io.py",
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
            "import echo_personal_tool.application.dicom_export; "
            "import echo_personal_tool.application.dicom_io; "
            "import echo_personal_tool.application.recent_folders; "
            "import echo_personal_tool.application.report_export; "
            "import echo_personal_tool.application.report_phrases; "
            "import echo_personal_tool.application.server_io; "
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
