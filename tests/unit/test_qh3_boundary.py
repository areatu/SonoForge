"""QH-3 boundary ratchet — zero new domain→infrastructure, controller purity.

G4 §8.2 requires the final domain boundary to be zero; QH-3 already enforces
that no controller imports the viewer facade for I/O and that domain stays pure.
This test is the ratchet that fails on a new direct violation (§10 slice 11).
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).parents[2] / "src" / "echo_personal_tool"
DOMAIN = SRC / "domain"
PRESENTATION_VIEWER = SRC / "presentation" / "viewer"

#: Exact inventory of the pre-existing domain → infrastructure edges (the
#: debt QH-4b tracks). Do not add entries to bless a new import; remove an
#: entry only in the same change that removes that source dependency.
_KNOWN_DOMAIN_DEBT = frozenset(
    {
        ("domain/services/bench_lvef.py", "echo_personal_tool.infrastructure.dicom_reader"),
        ("domain/services/cine_segment_diagnostics.py", "echo_personal_tool.infrastructure.onnx_engine"),
        ("domain/services/cine_segment_diagnostics.py", "echo_personal_tool.infrastructure.video_reader"),
        ("domain/services/indexed_results_formatter.py", "echo_personal_tool.infrastructure.profiler"),
        ("domain/services/measurement_results_formatter.py", "echo_personal_tool.infrastructure.profiler"),
        ("domain/services/segment_roi.py", "echo_personal_tool.infrastructure.dicom_frame_panels"),
        ("domain/services/segment_roi.py", "echo_personal_tool.infrastructure.pixel_utils"),
        ("domain/services/segment_roi.py", "echo_personal_tool.infrastructure.samsung_tick_detector"),
    }
)


def _imports_of(py_file: pathlib.Path) -> list[str]:
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


class TestQH3BoundaryRatchet:
    def test_domain_does_not_import_infrastructure_or_presentation(self) -> None:
        # Ratchet (same policy as QH-4b): the 8 remaining historical edges below
        # are inventoried debt, not approved architecture. This fails only when a
        # NEW direct edge appears; the target boundary remains zero.
        added: list[str] = []
        offenders: set[tuple[str, str]] = set()
        for py in DOMAIN.rglob("*.py"):
            rel = py.relative_to(SRC).as_posix()
            for mod in _imports_of(py):
                if mod.startswith("echo_personal_tool.infrastructure") or mod.startswith(
                    "echo_personal_tool.presentation"
                ):
                    offenders.add((rel, mod))
        added = sorted(f"{f} → {m}" for f, m in offenders - _KNOWN_DOMAIN_DEBT)
        assert not added, "domain must not grow infrastructure/presentation dependencies:\n" + "\n".join(added)

    def test_viewer_controllers_do_not_import_main_window_as_service_locator(self) -> None:
        bad: list[str] = []
        for py in PRESENTATION_VIEWER.rglob("*.py"):
            if py.name == "__init__.py":
                continue
            for mod in _imports_of(py):
                if mod.endswith("main_window") or mod == "echo_personal_tool.presentation.main_window":
                    bad.append(f"{py.name} → {mod}")
        assert bad == [], "controllers must receive narrow dependencies, not MainWindow service locator:\n" + "\n".join(
            bad
        )

    def test_viewer_controllers_do_not_import_infrastructure_io(self) -> None:
        # Controllers may import domain calculations; importing dicom_reader /
        # onnx_worker / download would be orchestration (§8.2 slice 2) and must
        # live in application/workers, not in the controller.
        forbidden = {
            "echo_personal_tool.infrastructure.dicom_reader",
            "echo_personal_tool.infrastructure.dicom_session",
            "echo_personal_tool.infrastructure.onnx_worker",
            "echo_personal_tool.application.workers.onnx_worker",
            "echo_personal_tool.application.workers.dicom_decode_worker",
        }
        bad: list[str] = []
        for py in PRESENTATION_VIEWER.rglob("*.py"):
            for mod in _imports_of(py):
                if mod in forbidden:
                    bad.append(f"{py.name} → {mod}")
        assert bad == [], "controller must not orchestrate I/O directly:\n" + "\n".join(bad)

    def test_presentation_viewer_package_exists_and_exports_controllers(self) -> None:
        from echo_personal_tool.presentation.viewer import (
            CalibrationController,
            ContourEditingController,
            MagnifierController,
            ResultsOverlayController,
            ToolInteractionController,
            ViewerContext,
            WorkerBridge,
        )

        assert ViewerContext is not None
        assert ResultsOverlayController is not None
        assert MagnifierController is not None
        assert ToolInteractionController is not None
        assert ContourEditingController is not None
        assert CalibrationController is not None
        assert WorkerBridge is not None
