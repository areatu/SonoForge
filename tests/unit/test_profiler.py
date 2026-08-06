"""Unit tests for infrastructure/profiler.py."""

from __future__ import annotations

import logging
import time
from unittest.mock import patch

import pytest

from echo_personal_tool.infrastructure import profiler as prof_mod


@pytest.fixture(autouse=True)
def _reset_profiler_state():
    """Reset global profiler state between tests."""
    prof_mod._call_counts.clear()
    prof_mod._total_times.clear()
    prof_mod._slow_calls.clear()
    prof_mod._errors.clear()
    yield
    prof_mod._call_counts.clear()
    prof_mod._total_times.clear()
    prof_mod._slow_calls.clear()
    prof_mod._errors.clear()


class TestIsEnabled:
    def test_is_enabled_reflects_env(self):
        with patch.object(prof_mod, "_ENABLED", True):
            assert prof_mod.is_enabled() is True

    def test_is_enabled_default_false(self):
        with patch.object(prof_mod, "_ENABLED", False):
            assert prof_mod.is_enabled() is False


class TestProfiledDecorator:
    def test_decorator_enabled_records_call(self):
        with patch.object(prof_mod, "_ENABLED", True):

            @prof_mod.profiled
            def dummy_func():
                return 42

            result = dummy_func()
            assert result == 42
            # profiler uses func.__qualname__ as key
            assert prof_mod._call_counts[dummy_func.__qualname__] == 1

    def test_decorator_disabled_passthrough(self):
        with patch.object(prof_mod, "_ENABLED", False):

            @prof_mod.profiled
            def dummy_func():
                return 99

            result = dummy_func()
            assert result == 99
            # Not recorded when disabled
            assert len(prof_mod._call_counts) == 0

    def test_decorator_records_error(self):
        with patch.object(prof_mod, "_ENABLED", True):

            @prof_mod.profiled
            def failing_func():
                raise ValueError("boom")

            with pytest.raises(ValueError, match="boom"):
                failing_func()
            assert prof_mod._call_counts[failing_func.__qualname__] == 1
            assert len(prof_mod._errors) == 1
            assert prof_mod._errors[0][1] == "ValueError"
            assert "boom" in prof_mod._errors[0][2]

    def test_decorator_records_slow_call(self):
        with patch.object(prof_mod, "_ENABLED", True), patch.object(prof_mod, "_freeze_threshold_ms", 10.0):

            @prof_mod.profiled
            def slow_func():
                time.sleep(0.02)
                return "done"

            slow_func()
            assert prof_mod._call_counts[slow_func.__qualname__] == 1
            assert any(name == slow_func.__qualname__ for _, name, _ in prof_mod._slow_calls)

    def test_decorator_preserves_function_name(self):
        with patch.object(prof_mod, "_ENABLED", True):

            @prof_mod.profiled
            def named_func():
                pass

            assert named_func.__name__ == "named_func"


class TestProfileBlock:
    def test_context_manager_enabled(self):
        with patch.object(prof_mod, "_ENABLED", True):
            with prof_mod.profile_block("test_block"):
                time.sleep(0.001)
            # No assertion on timing; just verify no crash

    def test_context_manager_disabled(self):
        with patch.object(prof_mod, "_ENABLED", False):
            with prof_mod.profile_block("test_block"):
                pass

    def test_context_manager_records_error(self):
        with patch.object(prof_mod, "_ENABLED", True):
            with pytest.raises(RuntimeError):
                with prof_mod.profile_block("error_block"):
                    raise RuntimeError("block error")
            assert len(prof_mod._errors) == 1
            assert prof_mod._errors[0][0] == "error_block"


class TestPrintSummary:
    def test_print_summary_enabled(self, caplog):
        with patch.object(prof_mod, "_ENABLED", True):
            prof_mod._call_counts["func_a"] = 5
            prof_mod._total_times["func_a"] = 100.0
            with caplog.at_level(logging.INFO, logger="echo_personal_tool.profiler"):
                prof_mod.print_summary()
            assert "SUMMARY" in caplog.text

    def test_print_summary_disabled(self, caplog):
        with patch.object(prof_mod, "_ENABLED", False):
            with caplog.at_level(logging.INFO):
                prof_mod.print_summary()
            assert "SUMMARY" not in caplog.text

    def test_print_summary_with_slow(self, caplog):
        with patch.object(prof_mod, "_ENABLED", True):
            prof_mod._slow_calls = [(1000.0, "slow_func", "slow")]
            with caplog.at_level(logging.INFO, logger="echo_personal_tool.profiler"):
                prof_mod.print_summary()
            assert "SLOW/FROZEN" in caplog.text

    def test_print_summary_with_errors(self, caplog):
        with patch.object(prof_mod, "_ENABLED", True):
            prof_mod._errors = [("err_func", "ValueError", "bad value")]
            with caplog.at_level(logging.INFO, logger="echo_personal_tool.profiler"):
                prof_mod.print_summary()
            assert "ERRORS" in caplog.text
