"""Tests for extended playback diagnostics: instance switch tracking + prefetch cancellation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from echo_personal_tool.infrastructure.playback_diagnostics import (
    InstanceSwitchRecord,
    PlaybackDiagnostics,
)


@pytest.fixture
def diag_enabled():
    """Create a PlaybackDiagnostics instance with monitoring enabled."""
    diag = PlaybackDiagnostics()
    with patch("echo_personal_tool.infrastructure.playback_diagnostics._ENABLED", True):
        diag.start(fps_target=30, frame_count=60)
        yield diag


def test_on_instance_switch_start_records_timestamp(diag_enabled) -> None:
    assert diag_enabled._instance_switch_start == 0.0
    diag_enabled.on_instance_switch_start(prefetch_cancelled=True, frame_cache_bytes=4096)
    assert diag_enabled._instance_switch_start > 0.0
    assert diag_enabled._instance_switch_rss_start > 0.0
    assert diag_enabled._instance_switch_prefetch_cancelled is True
    assert diag_enabled._instance_switch_frame_cache_bytes == 4096


def test_on_instance_switch_end_returns_record(diag_enabled) -> None:
    diag_enabled.on_instance_switch_start()
    record = diag_enabled.on_instance_switch_end()
    assert record is not None
    assert isinstance(record, InstanceSwitchRecord)
    assert record.elapsed_ms >= 0.0
    assert record.rss_after_mb >= record.rss_before_mb
    assert record.prefetch_cancelled is False


def test_on_instance_switch_end_without_start_returns_none(diag_enabled) -> None:
    record = diag_enabled.on_instance_switch_end()
    assert record is None


def test_instance_switch_stored_in_report(diag_enabled) -> None:
    diag_enabled.on_instance_switch_start(prefetch_cancelled=True)
    diag_enabled.on_instance_switch_end()
    report = diag_enabled.stop()
    assert len(report.instance_switches) == 1
    rec = report.instance_switches[0]
    assert rec.prefetch_cancelled is True
    assert rec.rss_before_mb > 0


def test_on_prefetch_cancel_increments_counter(diag_enabled) -> None:
    diag_enabled.on_prefetch_cancel(reason="file_switch")
    diag_enabled.on_prefetch_cancel(reason="seek")
    report = diag_enabled.stop()
    assert report.prefetch_cancel_count == 2


def test_instance_switch_disabled_when_diag_off() -> None:
    diag = PlaybackDiagnostics()  # _ENABLED is False by default
    diag.on_instance_switch_start()  # should be no-op
    assert diag._instance_switch_start == 0.0
    result = diag.on_instance_switch_end()
    assert result is None
