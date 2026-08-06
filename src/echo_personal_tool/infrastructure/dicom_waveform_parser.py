"""Parse ECG waveform data from DICOM files using pydicom.waveform."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from echo_personal_tool.domain.models.ecg import EcgLead, EcgWaveform

logger = logging.getLogger(__name__)


def parse_waveform_from_dicom(dataset: Any) -> EcgWaveform | None:
    """Extract ECG waveform from a pydicom Dataset.

    Uses pydicom.waveform module for structured extraction.
    Returns None if no waveform data is present.

    Args:
        dataset: A pydicom.Dataset (already loaded, without pixel data).

    Returns:
        EcgWaveform or None if no waveform sequence found.
    """
    if not hasattr(dataset, "WaveformSequence"):
        return None

    waveform_seq = getattr(dataset, "WaveformSequence", None)
    if waveform_seq is None or len(waveform_seq) == 0:
        return None

    try:
        return _parse_waveform_sequence(waveform_seq, dataset)
    except Exception:
        logger.debug("Failed to parse waveform from DICOM", exc_info=True)
        return None


def _parse_waveform_sequence(waveform_seq: Any, dataset: Any) -> EcgWaveform | None:
    """Parse WaveformSequence items into EcgWaveform."""
    leads: list[EcgLead] = []
    waveform_frequency = _get_waveform_frequency(dataset)
    n_channels = 0

    for item in waveform_seq:
        # Each item in WaveformSequence represents one waveform record
        channel_definition = getattr(item, "ChannelDefinitionSequence", None)
        if channel_definition is None:
            continue

        # Get waveform sample data
        sample_data = getattr(item, "WaveformSampleData", None)
        if sample_data is None:
            continue

        # Get bits allocated and sample interpretation
        bits_allocated = getattr(item, "WaveformBitsAllocated", 16)
        interpretation = getattr(item, "WaveformSampleInterpretation", "SS")
        baseline = getattr(item, "WaveformBaseline", 0)

        # Get number of channels from the item
        n_channels_item = getattr(item, "NumberOfWaveformChannels", 1)
        n_channels = max(n_channels, n_channels_item)

        # Parse channel definitions
        for ch_def in channel_definition:
            channel_number = getattr(ch_def, "WaveformChannelNumber", 0)
            channel_source = getattr(ch_def, "ChannelSourceSequence", None)
            channel_label = _get_channel_label(ch_def, channel_source)
            min_val = getattr(ch_def, "ChannelMinimumValue", None)
            max_val = getattr(ch_def, "ChannelMaximumValue", None)

            # Extract samples for this channel
            samples = _extract_channel_samples(
                sample_data,
                channel_number,
                n_channels_item,
                bits_allocated,
                interpretation,
            )

            if samples is not None and len(samples) > 0:
                lead = EcgLead(
                    name=channel_label,
                    samples=samples,
                    sampling_frequency=waveform_frequency,
                    baseline=int(baseline) if baseline is not None else 0,
                    bits_stored=int(bits_allocated) if bits_allocated else 16,
                )
                leads.append(lead)

    if not leads:
        return None

    return EcgWaveform(
        leads=leads,
        waveform_frequency=waveform_frequency,
        number_of_waveform_channels=n_channels,
    )


def _get_waveform_frequency(dataset: Any) -> float:
    """Extract waveform sampling frequency from DICOM dataset."""
    # Try WaveformSampleRate (003A,001A) first
    sample_rate = getattr(dataset, "WaveformSampleRate", None)
    if sample_rate is not None:
        try:
            return float(sample_rate)
        except (ValueError, TypeError):
            pass

    # Fallback: try to infer from FrameTime or sampling period
    sampling_period = getattr(dataset, "WaveformSamplingPeriod", None)
    if sampling_period is not None:
        try:
            period_us = float(sampling_period)
            if period_us > 0:
                return 1_000_000.0 / period_us
        except (ValueError, TypeError):
            pass

    # Default to 500 Hz (common for ECG)
    return 500.0


def _get_channel_label(ch_def: Any, channel_source: Any) -> str:
    """Extract channel label from channel definition."""
    # Try ChannelLabel first
    label = getattr(ch_def, "ChannelLabel", None)
    if label:
        return str(label)

    # Try ChannelSourceSequence → CodeValue
    if channel_source is not None:
        for source_item in channel_source:
            code_value = getattr(source_item, "CodeValue", None)
            if code_value:
                return str(code_value)
            code_meaning = getattr(source_item, "CodeMeaning", None)
            if code_meaning:
                return str(code_meaning)

    # Try ChannelNumber
    ch_num = getattr(ch_def, "WaveformChannelNumber", None)
    if ch_num is not None:
        return f"Ch{ch_num}"

    return "Unknown"


def _extract_channel_samples(
    sample_data: Any,
    channel_number: int,
    n_channels: int,
    bits_allocated: int,
    interpretation: str,
) -> np.ndarray | None:
    """Extract samples for a specific channel from interleaved waveform data."""
    if sample_data is None:
        return None

    # Convert sample_data to numpy array if needed
    if isinstance(sample_data, np.ndarray):
        raw = sample_data
    elif isinstance(sample_data, (bytes, bytearray)):
        dtype = _interpretation_to_dtype(interpretation, bits_allocated)
        raw = np.frombuffer(sample_data, dtype=dtype)
    else:
        try:
            raw = np.array(sample_data, dtype=np.float64)
        except (ValueError, TypeError):
            return None

    if raw.size == 0:
        return None

    # If multi-channel, reshape and extract the specific channel
    if n_channels > 1 and raw.size >= n_channels:
        n_samples = raw.size // n_channels
        if n_samples * n_channels == raw.size:
            raw = raw.reshape(n_samples, n_channels)
            ch_idx = min(channel_number, n_channels - 1)
            return raw[:, ch_idx].copy()

    return raw.astype(np.float64)


def _interpretation_to_dtype(interpretation: str, bits_allocated: int) -> np.dtype:
    """Map DICOM SampleInterpretation + BitsAllocated to numpy dtype."""
    interp = interpretation.upper().strip() if interpretation else "SS"
    if interp in ("SS", "SL"):
        if bits_allocated <= 8:
            return np.dtype(np.int8)
        if bits_allocated <= 16:
            return np.dtype(np.int16)
        return np.dtype(np.int32)
    if interp in ("US", "UB", "UL"):
        if bits_allocated <= 8:
            return np.dtype(np.uint8)
        if bits_allocated <= 16:
            return np.dtype(np.uint16)
        return np.dtype(np.uint32)
    # Default to signed 16-bit
    return np.dtype(np.int16)
