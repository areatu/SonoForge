"""Unit tests for the Doppler widget."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models import DopplerMeasurementDTO
from echo_personal_tool.presentation.doppler_widget import DopplerWidget


def test_tool_mode_round_trip(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)

    assert widget.get_tool_mode() == "none"

    widget.set_tool_mode("peak")
    assert widget.get_tool_mode() == "peak"

    widget.set_tool_mode("trace")
    assert widget.get_tool_mode() == "trace"


def test_get_measurement_dto_starts_empty(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)

    assert widget.get_measurement_dto() == DopplerMeasurementDTO(
        peaks=(),
        intervals=(),
        traces=(),
    )


def test_cancel_active_tool_resets_mode(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)

    widget.set_tool_mode("interval")

    assert widget.cancel_active_tool() is True
    assert widget.get_tool_mode() == "none"
    assert widget.cancel_active_tool() is False


def test_show_spectrogram_accepts_grayscale_array(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)

    pixels = np.arange(12, dtype=np.float32).reshape(3, 4)
    widget.show_spectrogram(pixels)

    assert widget._image_item.image is not None
    assert widget._image_item.image.shape == (3, 4)
