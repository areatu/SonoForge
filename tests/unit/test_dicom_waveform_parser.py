"""Unit tests for DICOM waveform parser."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from echo_personal_tool.infrastructure.dicom_waveform_parser import (
    _extract_channel_samples,
    _get_channel_label,
    _get_waveform_frequency,
    _interpretation_to_dtype,
    parse_waveform_from_dicom,
)


class TestInterpretationToDtype:
    def test_signed_16bit(self) -> None:
        dtype = _interpretation_to_dtype("SS", 16)
        assert dtype == np.dtype(np.int16)

    def test_unsigned_16bit(self) -> None:
        dtype = _interpretation_to_dtype("US", 16)
        assert dtype == np.dtype(np.uint16)

    def test_signed_32bit(self) -> None:
        dtype = _interpretation_to_dtype("SL", 32)
        assert dtype == np.dtype(np.int32)

    def test_unsigned_8bit(self) -> None:
        dtype = _interpretation_to_dtype("UB", 8)
        assert dtype == np.dtype(np.uint8)

    def test_default(self) -> None:
        dtype = _interpretation_to_dtype("XX", 16)
        assert dtype == np.dtype(np.int16)


class TestGetWaveformFrequency:
    def test_from_sample_rate(self) -> None:
        ds = SimpleNamespace(WaveformSampleRate=500.0)
        assert _get_waveform_frequency(ds) == 500.0

    def test_from_sampling_period(self) -> None:
        ds = SimpleNamespace(WaveformSamplingPeriod=2000.0)  # 2000 μs = 500 Hz
        assert _get_waveform_frequency(ds) == 500.0

    def test_default_500hz(self) -> None:
        ds = SimpleNamespace()
        assert _get_waveform_frequency(ds) == 500.0


class TestGetChannelLabel:
    def test_from_label(self) -> None:
        ch_def = SimpleNamespace(ChannelLabel="II", WaveformChannelNumber=0, ChannelSourceSequence=None)
        result = _get_channel_label(ch_def, None)
        assert result == "II"

    def test_from_source_code_value(self) -> None:
        source = SimpleNamespace(CodeValue="MLII")
        ch_def = SimpleNamespace(ChannelLabel=None, WaveformChannelNumber=1, ChannelSourceSequence=[source])
        result = _get_channel_label(ch_def, ch_def.ChannelSourceSequence)
        assert result == "MLII"

    def test_from_channel_number(self) -> None:
        ch_def = SimpleNamespace(ChannelLabel=None, WaveformChannelNumber=2, ChannelSourceSequence=None)
        result = _get_channel_label(ch_def, None)
        assert result == "Ch2"

    def test_unknown(self) -> None:
        ch_def = SimpleNamespace(ChannelLabel=None, WaveformChannelNumber=None, ChannelSourceSequence=None)
        result = _get_channel_label(ch_def, None)
        assert result == "Unknown"


class TestExtractChannelSamples:
    def test_multi_channel(self) -> None:
        # 3 channels, 4 samples → interleaved
        data = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], dtype=np.int16)
        result = _extract_channel_samples(data, channel_number=1, n_channels=3, bits_allocated=16, interpretation="SS")
        assert result is not None
        np.testing.assert_array_equal(result, np.array([2.0, 5.0, 8.0, 11.0]))

    def test_single_channel(self) -> None:
        data = np.array([10, 20, 30], dtype=np.int16)
        result = _extract_channel_samples(data, channel_number=0, n_channels=1, bits_allocated=16, interpretation="SS")
        assert result is not None
        np.testing.assert_array_equal(result, np.array([10.0, 20.0, 30.0]))

    def test_none_input(self) -> None:
        result = _extract_channel_samples(None, 0, 1, 16, "SS")
        assert result is None

    def test_empty_data(self) -> None:
        data = np.array([], dtype=np.int16)
        result = _extract_channel_samples(data, 0, 1, 16, "SS")
        assert result is None


class TestParseWaveformFromDicom:
    def test_no_waveform_sequence(self) -> None:
        ds = SimpleNamespace(WaveformSequence=None)
        result = parse_waveform_from_dicom(ds)
        assert result is None

    def test_missing_waveform_sequence(self) -> None:
        ds = SimpleNamespace()
        result = parse_waveform_from_dicom(ds)
        assert result is None

    def test_empty_waveform_sequence(self) -> None:
        ds = SimpleNamespace(WaveformSequence=[])
        result = parse_waveform_from_dicom(ds)
        assert result is None

    def test_with_waveform_data(self) -> None:
        # Create a mock waveform sequence with channel definitions
        sample_data = np.zeros(100, dtype=np.int16).tobytes()
        ch_def = SimpleNamespace(
            WaveformChannelNumber=0,
            ChannelLabel="II",
            ChannelSourceSequence=None,
            ChannelMinimumValue=-1024,
            ChannelMaximumValue=1024,
        )
        waveform_item = SimpleNamespace(
            ChannelDefinitionSequence=[ch_def],
            WaveformSampleData=sample_data,
            WaveformBitsAllocated=16,
            WaveformSampleInterpretation="SS",
            WaveformBaseline=0,
            NumberOfWaveformChannels=1,
        )
        ds = SimpleNamespace(
            WaveformSequence=[waveform_item],
            WaveformSampleRate=500.0,
        )
        result = parse_waveform_from_dicom(ds)
        assert result is not None
        assert result.waveform_frequency == 500.0
        assert len(result.leads) == 1
        assert result.leads[0].name == "II"
