"""Tests for ViewerWidget ECG strip integration."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from echo_personal_tool.domain.models.ecg import EcgLead, EcgWaveform
from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


@pytest.fixture()
def sample_ecg_waveform() -> EcgWaveform:
    """Create a simple ECG waveform with 2 R-peaks for testing."""
    fs = 500.0
    duration_s = 2.0
    n_samples = int(fs * duration_s)

    # Create a simple ECG-like signal with 2 R-peaks
    signal = np.zeros(n_samples, dtype=np.int16)
    # R-peak at 0.5s and 1.5s (60 bpm)
    r_peak_times = [0.5, 1.5]
    for r_time in r_peak_times:
        r_idx = int(r_time * fs)
        # Simple QRS complex
        for i in range(-5, 6):
            if 0 <= r_idx + i < n_samples:
                signal[r_idx + i] = int(1000 * np.exp(-0.5 * (i / 2) ** 2))

    lead = EcgLead(
        name="II",
        samples=signal,
        sampling_frequency=fs,
        baseline=0,
        bits_stored=12,
    )
    return EcgWaveform(
        leads=[lead],
        waveform_frequency=fs,
        number_of_waveform_channels=1,
    )


@pytest.fixture()
def sample_cardiac_cycles() -> list[CardiacCycle]:
    """Create sample cardiac cycles for testing."""
    return [
        CardiacCycle(
            start_ms=400.0,
            end_ms=1400.0,
            r_peak_ms=500.0,
            ed_ms=500.0,
            es_ms=675.0,
            source="ecg",
            confidence=0.9,
            rr_ms=1000.0,
        ),
        CardiacCycle(
            start_ms=1400.0,
            end_ms=2000.0,
            r_peak_ms=1500.0,
            ed_ms=1500.0,
            es_ms=1675.0,
            source="ecg",
            confidence=0.9,
            rr_ms=1000.0,
        ),
    ]


def test_viewer_widget_ecg_strip_initially_hidden(qtbot):
    """Test that ECG strip is initially hidden."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    assert widget.contract.ecg_strip.isHidden()


def test_viewer_widget_show_ecg_strip(qtbot):
    """Test showing the ECG strip."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    widget.show_ecg_strip()
    assert not widget.contract.ecg_strip.isHidden()


def test_viewer_widget_hide_ecg_strip(qtbot):
    """Test hiding the ECG strip."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    widget.show_ecg_strip()
    assert not widget.contract.ecg_strip.isHidden()
    widget.hide_ecg_strip()
    assert widget.contract.ecg_strip.isHidden()


def test_viewer_widget_set_ecg_waveform_for_strip(qtbot, sample_ecg_waveform):
    """Test setting ECG waveform on the strip."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    widget.set_ecg_waveform_for_strip(sample_ecg_waveform)
    # The strip should now have the ECG loaded
    assert widget.contract.ecg_strip.signal_item is not None


def test_viewer_widget_set_ecg_waveform_for_strip_none(qtbot):
    """Test setting None ECG waveform on the strip."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    widget.set_ecg_waveform_for_strip(None)
    assert widget.contract.ecg_strip.signal_item is None


def test_viewer_widget_set_cardiac_cycles_for_strip(qtbot, sample_cardiac_cycles):
    """Test setting cardiac cycles on the strip."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    widget.set_cardiac_cycles_for_strip(sample_cardiac_cycles)
    assert len(widget.contract.ecg_strip.cycles) == 2


def test_viewer_widget_set_cardiac_cycles_for_strip_invalid(qtbot):
    """Test setting invalid cardiac cycles on the strip."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    # Should not raise
    widget.set_cardiac_cycles_for_strip("invalid")
    assert len(widget.contract.ecg_strip.cycles) == 0


def test_viewer_widget_highlight_ecg_cycle_for_strip(qtbot, sample_cardiac_cycles):
    """Test highlighting a specific ECG cycle."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    widget.set_cardiac_cycles_for_strip(sample_cardiac_cycles)

    # Highlight first cycle
    widget.highlight_ecg_cycle_for_strip(0)
    assert widget.contract.ecg_strip.cycle_highlight is not None

    # Highlight second cycle
    widget.highlight_ecg_cycle_for_strip(1)
    assert widget.contract.ecg_strip.cycle_highlight is not None

    # Clear highlight
    widget.highlight_ecg_cycle_for_strip(None)
    assert widget.contract.ecg_strip.cycle_highlight is None


def test_viewer_widget_load_ecg_for_strip(qtbot):
    """Test loading ECG for strip (requires instance path)."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    # This method requires a valid instance path, so we just test it doesn't crash
    with patch("echo_personal_tool.presentation.ecg_strip_loader.read_ecg_waveform") as read_ecg:
        widget.contract.load_ecg_for_strip()

    read_ecg.assert_not_called()  # no open instance, so there is no file to read


def test_viewer_widget_load_ecg_for_strip_reads_the_open_instance(qtbot, sample_ecg_waveform, tmp_path):
    """The waveform of the open study's file goes to the strip."""
    from echo_personal_tool.domain.models import InstanceMetadata, ViewerState

    widget = ViewerWidget()
    qtbot.addWidget(widget)
    path = tmp_path / "echo.dcm"
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.4.5.6",
        series_uid="1.2.3.4.5",
        modality="US",
        number_of_frames=1,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=path,
        media_format="dicom",
    )
    widget.set_state(
        ViewerState(instance=instance, current_frame_index=0, total_frames=1, frame_time_ms=33.3, is_playing=False)
    )

    with (
        patch(
            "echo_personal_tool.presentation.ecg_strip_loader.read_ecg_waveform", return_value=sample_ecg_waveform
        ) as read_ecg,
        patch.object(widget, "set_ecg_waveform_for_strip") as set_strip,
    ):
        widget.contract.load_ecg_for_strip()

    read_ecg.assert_called_once_with(path)
    set_strip.assert_called_once_with(sample_ecg_waveform)
