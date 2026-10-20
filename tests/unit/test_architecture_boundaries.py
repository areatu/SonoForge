"""QH-4b baseline ratchet for direct domain -> infrastructure imports.

The current 24 edges are historical debt, not approved architecture. Each is
listed explicitly so this test fails on new edges and requires the reviewed
baseline to shrink as dependencies are inverted. The target remains zero.
"""

from __future__ import annotations

import ast
from pathlib import Path

_DOMAIN_ROOT = Path(__file__).parents[2] / "src" / "echo_personal_tool" / "domain"

# Exact current debt inventory. Do not add entries to make a new import pass;
# remove an entry only in the same change that removes that source dependency.
_EXPECTED_EDGES = frozenset(
    {
        ("domain/calculations/lvef_simpson.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/calculations/planimeter.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/calculations/rv_fac.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/calculators/text.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/models/linear_measurement.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/bench_lvef.py", "echo_personal_tool.infrastructure.dicom_reader"),
        ("domain/services/bsa_provenance.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/cine_segment_diagnostics.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/cine_segment_diagnostics.py", "echo_personal_tool.infrastructure.onnx_engine"),
        ("domain/services/cine_segment_diagnostics.py", "echo_personal_tool.infrastructure.video_reader"),
        ("domain/services/indexed_results_formatter.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/indexed_results_formatter.py", "echo_personal_tool.infrastructure.profiler"),
        ("domain/services/la_segmentation_service.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/measurement_report_formatter.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/measurement_results_formatter.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/measurement_results_formatter.py", "echo_personal_tool.infrastructure.profiler"),
        ("domain/services/nomenclature.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/provenance_notes.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/reference_card.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/reference_topics.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/report_builder.py", "echo_personal_tool.infrastructure.i18n"),
        ("domain/services/segment_roi.py", "echo_personal_tool.infrastructure.dicom_frame_panels"),
        ("domain/services/segment_roi.py", "echo_personal_tool.infrastructure.pixel_utils"),
        ("domain/services/segment_roi.py", "echo_personal_tool.infrastructure.samsung_tick_detector"),
    }
)
_PREFIX = "echo_personal_tool.infrastructure"


def _direct_import_edges() -> frozenset[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for source in _DOMAIN_ROOT.rglob("*.py"):
        relative = source.relative_to(_DOMAIN_ROOT.parent).as_posix()
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            modules: tuple[str, ...] = ()
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = (node.module,)
            elif isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            for module in modules:
                if module == _PREFIX or module.startswith(_PREFIX + "."):
                    edges.add((relative, module))
    return frozenset(edges)


def test_domain_has_no_untracked_infrastructure_edges() -> None:
    actual = _direct_import_edges()
    added = sorted(actual - _EXPECTED_EDGES)
    removed = sorted(_EXPECTED_EDGES - actual)
    assert not added and not removed, (
        "domain -> infrastructure boundary changed; new edges are forbidden and removed debt "
        "must shrink the reviewed inventory. "
        f"Added: {added}; removed: {removed}; expected zero direct edges eventually."
    )
