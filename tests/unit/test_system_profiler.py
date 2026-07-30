from __future__ import annotations

import pytest

from echo_personal_tool.infrastructure.system_profiler import (
    PlaybackConfig,
    detect_playback_config,
)


def test_playback_config_is_frozen():
    cfg = PlaybackConfig(
        prefetch_radius=3,
        min_buffer=2,
        batch_size=3,
        max_lag_frames=2,
        evict_window=30,
        scroll_debounce_ms=80,
        scroll_batch_size=3,
    )
    with pytest.raises(AttributeError):
        cfg.prefetch_radius = 5  # type: ignore[misc]


def test_detect_playback_config_low_end(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.os.cpu_count",
        lambda: 2,
    )

    class _Mem:
        total = int(4e9)

    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.psutil.virtual_memory",
        lambda: _Mem(),
    )
    cfg = detect_playback_config()
    assert cfg.prefetch_radius == 5
    assert cfg.batch_size == 5
    assert cfg.evict_window == 30
    assert cfg.scroll_debounce_ms == 80
    assert cfg.scroll_batch_size == 3


def test_detect_playback_config_high_end(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.os.cpu_count",
        lambda: 12,
    )

    class _Mem:
        total = int(32e9)

    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.psutil.virtual_memory",
        lambda: _Mem(),
    )
    cfg = detect_playback_config()
    assert cfg.prefetch_radius == 10
    assert cfg.batch_size == 8
    assert cfg.evict_window == 40
    assert cfg.scroll_debounce_ms == 50
    assert cfg.scroll_batch_size == 8


def test_playback_config_includes_scroll_fields() -> None:
    cfg = detect_playback_config()
    assert cfg.scroll_debounce_ms in (50, 80)
    assert cfg.scroll_batch_size in (3, 8)
