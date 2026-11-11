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

#: QH-4b finished the inversion: the reviewed inventory is empty.  Do not add
#: entries to bless a new import — any direct edge must fail this ratchet.
_KNOWN_DOMAIN_DEBT: frozenset[tuple[str, str]] = frozenset()


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
        # Ratchet (same policy as QH-4b): the reviewed inventory is empty, so
        # any direct domain -> infrastructure/presentation import fails here.
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
        import echo_personal_tool.presentation.viewer as viewer_pkg
        from echo_personal_tool.presentation.viewer import (
            DopplerController,
            MagnifierController,
            MModeController,
            ResultsOverlayController,
            TagsOverlayController,
            ViewerContext,
        )

        assert ViewerContext is not None
        assert ResultsOverlayController is not None
        assert TagsOverlayController is not None
        assert MagnifierController is not None
        assert MModeController is not None
        assert DopplerController is not None
        # issue 466: unwired duplicate owners were removed from the package
        for removed in (
            "ToolInteractionController",
            "ContourEditingController",
            "CalibrationController",
            "WorkerBridge",
            "WorkerToken",
        ):
            assert not hasattr(viewer_pkg, removed)


def test_doppler_owner_replaces_widget_state_and_forwarding_api() -> None:
    tree = ast.parse((SRC / "presentation" / "viewer_widget.py").read_text(encoding="utf-8"))
    widget = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ViewerWidget")
    methods = {node.name for node in widget.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    old_methods = {
        "start_doppler_calibration",
        "clear_doppler_calibration_display",
        "get_doppler_tool_mode",
        "set_doppler_tool_mode",
        "finish_doppler_trace",
        "get_doppler_dto",
        "restore_doppler_state",
        "is_doppler_context",
        "resolved_doppler_mode",
        "apply_doppler_calibration_state",
        "_configure_doppler_axis_for_frame",
        "_handle_doppler_mouse_click",
        "_handle_doppler_calibration_click",
        "_remove_doppler_measurement_at_cursor",
        "start_vti_auto_trace",
        "start_mitral_inflow_workflow",
    }
    assert not methods.intersection(old_methods)
    old_state = {
        "_doppler",
        "_doppler_calibration_state",
        "_doppler_cal_step",
        "_doppler_pending_roi",
        "_doppler_velocity_confirmed",
        "_doppler_axis_calibrated",
        "_doppler_grid_line_positions",
        "_doppler_hint_dismissed",
        "_doppler_mode_override",
        "_dicom_doppler_mode",
    }
    attributes = {
        node.attr
        for node in ast.walk(widget)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"
    }
    assert not attributes.intersection(old_state)


def test_protocol_coordinator_owns_workflow_not_main_window() -> None:
    path = SRC / "presentation" / "main_window.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
    methods = {node.name for node in window.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    attributes = {
        node.attr
        for node in ast.walk(window)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"
    }
    assert not attributes.intersection(
        {"_protocol_session", "_protocol_step_bar", "_protocol_armed_index", "_protocol_auto_advance"}
    )
    assert not methods.intersection(
        {"_ensure_protocol_session", "_on_protocol_selected", "_protocol_escape", "_sync_protocol_step_bar"}
    )
    owner = SRC / "presentation" / "coordinators" / "protocol_coordinator.py"
    assert not any(name.endswith("main_window") for name in _imports_of(owner))


def test_tags_overlay_has_one_owner() -> None:
    tree = ast.parse((SRC / "presentation" / "viewer_widget.py").read_text(encoding="utf-8"))
    window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ViewerWidget")
    names = {
        node.attr
        for node in ast.walk(window)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"
    }
    methods = {node.name for node in window.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not names.intersection({"_dicom_tags_overlay_label", "_interesting_dicom_tags", "_tags_overlay_controller"})
    assert not methods.intersection(
        {
            "_refresh_dicom_tags_overlay",
            "_position_dicom_tags_overlay",
            "refresh_dicom_tags_overlay",
            "dicom_tags_overlay_text",
        }
    )
    assert not any(
        name.endswith("viewer_widget") for name in _imports_of(PRESENTATION_VIEWER / "overlay_controller.py")
    )
