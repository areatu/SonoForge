"""ECG strip loading for the Doppler spectrogram (viewer collaborator).

Extracted from ViewerWidget: pushes waveforms and cycles onto the ECG strip,
and loads the waveform from the DICOM behind the clip.  The strip is shown
only when the clip actually carries a usable waveform — a Doppler clip without
ECG in the DICOM would otherwise paint an empty bar.
"""

from __future__ import annotations

import logging
from typing import Any

from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.application.dicom_io import read_ecg_waveform

__all__ = [
    "highlight_ecg_cycle_for_strip",
    "hide_ecg_strip",
    "load_ecg_for_strip",
    "set_cardiac_cycles_for_strip",
    "set_ecg_waveform_for_strip",
    "show_ecg_strip",
]

logger = logging.getLogger(__name__)


def show_ecg_strip(view: Any) -> None:
    """Show the ECG strip under the spectrogram."""
    view._ecg_strip.show()


def hide_ecg_strip(view: Any) -> None:
    """Hide the ECG strip."""
    view._ecg_strip.hide()


def set_ecg_waveform_for_strip(view: Any, ecg: object | None) -> None:
    """Set ECG waveform on the strip for display."""
    from echo_personal_tool.domain.models.ecg import EcgWaveform

    if ecg is not None and not isinstance(ecg, EcgWaveform):
        return
    view._ecg_strip.set_ecg(ecg)


def set_cardiac_cycles_for_strip(view: Any, cycles: object) -> None:
    """Set cardiac cycles on the strip for cycle highlighting."""
    from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

    if not isinstance(cycles, (list, tuple)):
        return
    valid_cycles = [c for c in cycles if isinstance(c, CardiacCycle)]
    view._ecg_strip.set_cardiac_cycles(valid_cycles)


def highlight_ecg_cycle_for_strip(view: Any, cycle_index: int | None) -> None:
    """Highlight a specific ECG cycle by index, or clear if None."""
    view._ecg_strip.highlight_cycle(cycle_index)


def load_ecg_for_strip(view: Any) -> None:
    """Load ECG for the strip; show it only when a usable waveform exists."""
    instance = view._current_instance_metadata()
    if instance is None or instance.path is None:
        view.hide_ecg_strip()
        return
    try:
        ecg = read_ecg_waveform(instance.path)
    except Exception as exc:  # noqa: BLE001 - missing/unreadable waveform skips the strip
        log_boundary_failure(logger, "dicom.waveform", exc, code="invalid", level=logging.DEBUG)
        ecg = None
    if ecg is None:
        view.hide_ecg_strip()
        return
    view.set_ecg_waveform_for_strip(ecg)
    # Never show an empty strip: the widget drops waves it cannot draw
    # (missing primary lead, unusable sampling, too few samples).
    if getattr(view._ecg_strip, "signal_item", None) is None:
        view.hide_ecg_strip()
        return
    view.show_ecg_strip()
