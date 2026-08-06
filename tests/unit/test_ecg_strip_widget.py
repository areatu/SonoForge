"""Tests for ECG strip widget with R-peak markers and cycle highlighting."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.ecg import EcgLead, EcgWaveform
from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle
from echo_personal_tool.presentation.ecg_strip_widget import EcgStripWidget


@pytest.fixture()
def sample_ecg_waveform() -> EcgWaveform:
    """Create a simple ECG waveform with 2 R-peaks for testing."""
    fs = 500.0
    duration_s = 2.0
    n_samples = int(fs * duration_s)
    t = np.arange(n_samples) / fs

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


def test_ecg_strip_widget_creation(qtbot):
    """Test that ECG strip widget can be created."""
    widget = EcgStripWidget()
    qtbot.addWidget(widget)
    assert widget is not None


def test_ecg_strip_set_ecg(qtbot, sample_ecg_waveform):
    """Test setting ECG waveform on the strip."""
    widget = EcgStripWidget()
    qtbot.addWidget(widget)

    # Should not raise
    widget.set_ecg(sample_ecg_waveform)

    # Check that signal item was created
    assert widget._signal_item is not None
    assert widget._r_peak_times is not None
    assert len(widget._r_peak_times) == 2


def test_ecg_strip_set_ecg_none(qtbot):
    """Test setting None ECG waveform clears the strip."""
    widget = EcgStripWidget()
    qtbot.addWidget(widget)

    widget.set_ecg(None)
    assert widget._signal_item is None
    assert widget._r_peak_times is None


def test_ecg_strip_set_cardiac_cycles(qtbot, sample_ecg_waveform, sample_cardiac_cycles):
    """Test setting cardiac cycles for highlighting."""
    widget = EcgStripWidget()
    qtbot.addWidget(widget)

    widget.set_ecg(sample_ecg_waveform)
    widget.set_cardiac_cycles(sample_cardiac_cycles)

    assert len(widget._cycles) == 2


def test_ecg_strip_highlight_cycle(qtbot, sample_ecg_waveform, sample_cardiac_cycles):
    """Test highlighting a specific cycle."""
    widget = EcgStripWidget()
    qtbot.addWidget(widget)

    widget.set_ecg(sample_ecg_waveform)
    widget.set_cardiac_cycles(sample_cardiac_cycles)

    # Highlight first cycle
    widget.highlight_cycle(0)
    assert widget._cycle_highlight is not None

    # Highlight second cycle
    widget.highlight_cycle(1)
    assert widget._cycle_highlight is not None

    # Clear highlight
    widget.highlight_cycle(None)
    assert widget._cycle_highlight is None


def test_ecg_strip_clear(qtbot, sample_ecg_waveform, sample_cardiac_cycles):
    """Test clearing the strip."""
    widget = EcgStripWidget()
    qtbot.addWidget(widget)

    widget.set_ecg(sample_ecg_waveform)
    widget.set_cardiac_cycles(sample_cardiac_cycles)

    widget.clear()

    assert widget._signal_item is None
    assert widget._r_peak_times is None
    assert len(widget._cycles) == 0


def test_ecg_strip_r_peak_markers(qtbot, sample_ecg_waveform):
    """Test that R-peak markers are drawn."""
    widget = EcgStripWidget()
    qtbot.addWidget(widget)

    widget.set_ecg(sample_ecg_waveform)

    # Should have 2 R-peak markers
    assert len(widget._rpeak_items) == 2


def test_ecg_strip_cycle_clicked_signal(qtbot, sample_ecg_waveform, sample_cardiac_cycles):
    """Test that cycle_clicked signal is emitted when clicking a cycle."""
    widget = EcgStripWidget()
    qtbot.addWidget(widget)

    widget.set_ecg(sample_ecg_waveform)
    widget.set_cardiac_cycles(sample_cardiac_cycles)

    # Connect signal
    received_cycles = []
    widget.cycle_clicked.connect(lambda c: received_cycles.append(c))

    # Simulate click in the middle of first cycle
    # This is a basic test - actual mouse event simulation would require more setup
    # For now, just verify the signal is defined
    assert hasattr(widget, 'cycle_clicked')
