"""Viewer composition package — QH-3 target boundary.

Re-exports the controllers so existing code can import from
`echo_personal_tool.presentation.viewer` without reaching into submodules.
ViewerWidget remains the public facade (imports unchanged for callers); the
new modules are injected into it by composition.

The package is also the place where the lifecycle harness (tests) discovers
all owner-scoped controllers to assert zero-leak on close.
"""

from echo_personal_tool.presentation.viewer.calibration_controller import CalibrationController
from echo_personal_tool.presentation.viewer.commands import (
    ClearResultsOverlayCommand,
    CommandResult,
    ConfigureMagnifierCommand,
    DeleteContourCommand,
    SetFrameCommand,
    SetMagnifierHeldCommand,
    SetResultsOverlayPositionCommand,
    SetResultsOverlayTextCommand,
    ViewerCommand,
)
from echo_personal_tool.presentation.viewer.context import ViewerContext, ViewerPaneIdentity, ViewTransform
from echo_personal_tool.presentation.viewer.contour_controller import ContourEditingController
from echo_personal_tool.presentation.viewer.magnifier_controller import MagnifierController
from echo_personal_tool.presentation.viewer.overlay_controller import (
    DebugOverlayController,
    FrameOverlayController,
    ResultsOverlayController,
    TagsOverlayController,
)
from echo_personal_tool.presentation.viewer.target_boundary import BOUNDARY
from echo_personal_tool.presentation.viewer.tool_controller import ToolInteractionController
from echo_personal_tool.presentation.viewer.worker_bridge import WorkerBridge, WorkerToken

__all__ = [
    # boundary doc
    "BOUNDARY",
    # context
    "ViewerContext",
    "ViewerPaneIdentity",
    "ViewTransform",
    # commands
    "ViewerCommand",
    "CommandResult",
    "SetFrameCommand",
    "SetResultsOverlayTextCommand",
    "SetResultsOverlayPositionCommand",
    "ClearResultsOverlayCommand",
    "ConfigureMagnifierCommand",
    "SetMagnifierHeldCommand",
    "DeleteContourCommand",
    # controllers
    "ResultsOverlayController",
    "FrameOverlayController",
    "TagsOverlayController",
    "DebugOverlayController",
    "MagnifierController",
    "ToolInteractionController",
    "ContourEditingController",
    "CalibrationController",
    "WorkerBridge",
    "WorkerToken",
]
