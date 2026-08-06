"""Unit tests for domain/services/multi_beat_average.py."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.multi_beat_average import beat_average


class TestBeatAverage:
    def test_averages_values(self) -> None:
        result = beat_average([10.0, 12.0, 14.0])
        assert result is not None
        assert result.mean == pytest.approx(12.0)
        assert result.values == (10.0, 12.0, 14.0)
        assert result.count == 3

    def test_limits_to_max_beats(self) -> None:
        result = beat_average([10.0, 12.0, 14.0, 100.0], max_beats=3)
        assert result is not None
        assert result.count == 3
        assert result.mean == pytest.approx(12.0)

    def test_empty_returns_none(self) -> None:
        assert beat_average([]) is None

    def test_single_value(self) -> None:
        result = beat_average([42.0])
        assert result is not None
        assert result.mean == pytest.approx(42.0)
        assert result.count == 1
