"""Viewer composition package — QH-3 target boundary.

Re-exports the live controllers so existing code can import from
`echo_personal_tool.presentation.viewer` without reaching into submodules.
ViewerWidget remains the public facade (imports unchanged for callers); the
modules are injected into it by composition.

The package is also the place where the lifecycle harness (tests) discovers
all owner-scoped controllers to assert zero-leak on close.
"""

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
from echo_personal_tool.presentation.viewer.display import ViewerDisplay
from echo_personal_tool.presentation.viewer.doppler_controller import DopplerController, DopplerViewerPort
from echo_personal_tool.presentation.viewer.label_picker_owner import ViewerLabelPicker
from echo_personal_tool.presentation.viewer.magnifier_controller import MagnifierController
from echo_personal_tool.presentation.viewer.mmode_controller import MModeController, MModeViewerPort
from echo_personal_tool.presentation.viewer.overlay_controller import (
    ResultsOverlayController,
    TagsOverlayController,
)
from echo_personal_tool.presentation.viewer.target_boundary import BOUNDARY
from echo_personal_tool.presentation.viewer.transport import ViewerTransport
from echo_personal_tool.presentation.viewer.zoom import ViewerZoom

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
    "TagsOverlayController",
    "MagnifierController",
    "MModeController",
    "MModeViewerPort",
    "DopplerController",
    "DopplerViewerPort",
    "ViewerTransport",
    "ViewerDisplay",
    "ViewerZoom",
    "ViewerLabelPicker",
]
