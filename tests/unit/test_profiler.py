"""Unit tests for profiler instrumentation."""

from __future__ import annotations

import os

import pytest

from echo_personal_tool.infrastructure.profiler import (
    _call_counts,
    _errors,
    _slow_calls,
    _total_times,
    is_enabled,
    profile_block,
    profiled,
    print_summary,
)


class TestIsEnabled:
    def test_default_disabled(self) -> None:
        # Without ECHO_PROFILE=1, profiler is disabled
        assert is_enabled() is False


class TestProfiledDecorator:
    def test_passthrough_when_disabled(self) -> None:
        @profiled
        def my_func(x: int) -> int:
            return x * 2

        assert my_func(5) == 10

    def test_preserves_function_name(self) -> None:
        @profiled
        def named_func() -> None:
            pass

        assert named_func.__name__ == "named_func"


class TestProfileBlock:
    def test_passthrough_when_disabled(self) -> None:
        with profile_block("test"):
            x = 1 + 1
        assert x == 2

    def test_exception_propagates(self) -> None:
        with pytest.raises(ValueError, match="boom"):
            with profile_block("test"):
                raise ValueError("boom")


class TestPrintSummary:
    def test_does_not_raise(self) -> None:
        print_summary()


class TestAggregateStats:
    def test_call_counts_is_dict(self) -> None:
        assert isinstance(_call_counts, dict)

    def test_total_times_is_dict(self) -> None:
        assert isinstance(_total_times, dict)

    def test_slow_calls_is_list(self) -> None:
        assert isinstance(_slow_calls, list)

    def test_errors_is_list(self) -> None:
        assert isinstance(_errors, list)
