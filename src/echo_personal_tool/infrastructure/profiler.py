"""Temporary profiling instrumentation for SonoForge.

Enable with ECHO_PROFILE=1 environment variable.
Logs timing, errors, and call counts for all major app functions.

This file is TEMPORARY — remove after profiling session.
"""

from __future__ import annotations

import functools
import logging
import os
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, TypeVar

_ENABLED = os.environ.get("ECHO_PROFILE", "0") == "1"
_LOG = logging.getLogger("echo_personal_tool.profiler")

# Aggregate stats
_call_counts: dict[str, int] = defaultdict(int)
_total_times: dict[str, float] = defaultdict(float)
_slow_calls: list[tuple[float, str, str]] = []  # (elapsed, func_name, detail)
_errors: list[tuple[str, str, str]] = []  # (func_name, error_type, message)
_freeze_threshold_ms = 500.0  # calls > 500ms are flagged as freezes

F = TypeVar("F", bound=Callable[..., Any])


def profiled(func: F) -> F:
    """Decorator: log timing + errors for a function."""
    if not _ENABLED:
        return func

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        name = f"{func.__qualname__}"
        t0 = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = (time.perf_counter() - t0) * 1000.0
            _call_counts[name] += 1
            _total_times[name] += elapsed
            if elapsed > _freeze_threshold_ms:
                _slow_calls.append((elapsed, name, "slow"))
                _LOG.warning("[PROFILE] FREEZE %.1f ms  %s", elapsed, name)
            elif elapsed > 50.0:
                _LOG.info("[PROFILE] SLOW %.1f ms  %s", elapsed, name)
            return result
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000.0
            _call_counts[name] += 1
            _total_times[name] += elapsed
            exc_type = type(exc).__name__
            exc_msg = str(exc)[:200]
            _errors.append((name, exc_type, exc_msg))
            _LOG.error("[PROFILE] ERROR %.1f ms  %s  %s: %s", elapsed, name, exc_type, exc_msg)
            raise

    return wrapper  # type: ignore[return-value]


@contextmanager
def profile_block(label: str):
    """Context manager: log timing for a block of code."""
    if not _ENABLED:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000.0
        exc_type = type(exc).__name__
        _errors.append((label, exc_type, str(exc)[:200]))
        _LOG.error("[PROFILE] ERROR %.1f ms  %s  %s", elapsed, label, exc_type)
        raise
    else:
        elapsed = (time.perf_counter() - t0) * 1000.0
        if elapsed > _freeze_threshold_ms:
            _LOG.warning("[PROFILE] FREEZE %.1f ms  %s", elapsed, label)
        elif elapsed > 50.0:
            _LOG.info("[PROFILE] SLOW %.1f ms  %s", elapsed, label)


def print_summary() -> None:
    """Print aggregate profiling stats to log."""
    if not _ENABLED:
        return
    _LOG.info("=" * 70)
    _LOG.info("[PROFILE] SUMMARY — %d unique functions called", len(_call_counts))
    _LOG.info("=" * 70)

    # Sort by total time descending
    sorted_funcs = sorted(_total_times.items(), key=lambda x: -x[1])
    _LOG.info("%-50s %8s %12s %10s", "Function", "Calls", "Total(ms)", "Avg(ms)")
    _LOG.info("-" * 70)
    for name, total in sorted_funcs[:40]:
        count = _call_counts[name]
        avg = total / count if count else 0
        _LOG.info("%-50s %8d %12.1f %10.1f", name[:50], count, total, avg)

    if _slow_calls:
        _LOG.info("-" * 70)
        _LOG.info("[PROFILE] SLOW/FROZEN calls (%d):", len(_slow_calls))
        for elapsed, name, detail in sorted(_slow_calls, key=lambda x: -x[0])[:20]:
            _LOG.info("  %.1f ms  %s  (%s)", elapsed, name, detail)

    if _errors:
        _LOG.info("-" * 70)
        _LOG.info("[PROFILE] ERRORS (%d):", len(_errors))
        for name, exc_type, msg in _errors[-20:]:
            _LOG.info("  %s  %s: %s", name, exc_type, msg)

    _LOG.info("=" * 70)


def is_enabled() -> bool:
    return _ENABLED
