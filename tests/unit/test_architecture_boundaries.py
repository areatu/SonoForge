"""QH-4b ratchet for direct domain -> infrastructure imports.

The reviewed baseline is now **zero** edges (G4 §8.2).  Every historical edge
was inverted or relocated behind an adapter:

* formatter instrumentation dropped from the domain (profiling stays outside);
* Samsung tick detection and pixel normalization moved to the pure
  ``echo_personal_tool.imaging`` kernel;
* the DICOM panel adapter is called by the application, the domain receives
  the parsed ``FramePanelLayout``;
* cine diagnostics and the LVEF bench pairing moved to ``application/services``.

Any new edge fails here.  The baseline must never grow; it is kept as an empty
inventory so the failure message stays explicit.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC_ROOT = Path(__file__).parents[2] / "src"
_DOMAIN_ROOT = _SRC_ROOT / "echo_personal_tool" / "domain"
_IMAGING_ROOT = _SRC_ROOT / "echo_personal_tool" / "imaging"

# Exact current debt inventory. Do not add entries to make a new import pass;
# the target and the current state are both zero direct edges.
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
