from __future__ import annotations

import pytest

from echo_personal_tool.infrastructure.system_profiler import (
    PlaybackConfig,
    _is_remote_windows_session,
    classify_renderer,
    detect_opengl_capability,
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
    assert cfg.evict_window == 12
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
    assert cfg.evict_window == 20
    assert cfg.scroll_debounce_ms == 50
    assert cfg.scroll_batch_size == 8


def test_playback_config_includes_scroll_fields() -> None:
    cfg = detect_playback_config()
    assert cfg.scroll_debounce_ms in (50, 80)
    assert cfg.scroll_batch_size in (3, 8)


def _patch_machine(monkeypatch: pytest.MonkeyPatch, cores: int, total_gib: float, available_gib: float) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.os.cpu_count",
        lambda: cores,
    )
    total = int(total_gib * 1024**3)
    available = int(available_gib * 1024**3)

    class _Mem:
        pass

    _Mem.total = total  # type: ignore[attr-defined]
    _Mem.available = available  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.psutil.virtual_memory",
        lambda: _Mem(),
    )


def test_detect_8gib_machine_is_low_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """8 GiB is 8.59e9 bytes: dividing by 1e9 used to send it to the high-end profile."""
    _patch_machine(monkeypatch, cores=8, total_gib=8.0, available_gib=6.0)

    cfg = detect_playback_config()

    assert cfg.prefetch_radius == 5
    assert cfg.evict_window == 12
    assert cfg.batch_size == 5


def test_detect_bigger_machine_with_room_is_high_end(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_machine(monkeypatch, cores=8, total_gib=16.0, available_gib=9.0)

    cfg = detect_playback_config()

    assert cfg.prefetch_radius == 10
    assert cfg.evict_window == 20


def test_detect_exhausted_machine_is_low_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """Installed RAM does not matter when almost none of it is free."""
    _patch_machine(monkeypatch, cores=16, total_gib=64.0, available_gib=1.5)

    cfg = detect_playback_config()

    assert cfg.prefetch_radius == 5
    assert cfg.evict_window == 12


def test_detect_without_available_falls_back_to_total(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shims that only report installed memory must still classify correctly."""
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.os.cpu_count",
        lambda: 12,
    )

    class _Mem:
        total = int(32 * 1024**3)

    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.psutil.virtual_memory",
        lambda: _Mem(),
    )

    assert detect_playback_config().prefetch_radius == 10


# ── OpenGL capability detection (software GL falls back to raster) ────────────────


@pytest.mark.parametrize(
    "renderer",
    [
        "llvmpipe (LLVM 15.0.6, 256 bits)",
        "softpipe",
        "Gallium 0.4 on swrast",
        "Apple Software Renderer",
        "ANGLE (Software Adapter Device, Direct3D11 vs_5_0 ps_5_0)",
        "Microsoft Basic Render Driver",
        "GDI Generic",
    ],
)
def test_software_renderers_fall_back_to_raster(renderer: str):
    use_gl, reason = classify_renderer(renderer)
    assert use_gl is False
    assert renderer in reason


@pytest.mark.parametrize(
    "renderer",
    [
        "ANGLE (Intel(R) UHD Graphics 620, Direct3D11 vs_5_0 ps_5_0)",
        "NVIDIA GeForce GTX 1650/PCIe/SSE2",
        "Mesa Intel(R) Iris(R) Xe Graphics (TGL GT2)",
        "Apple M2 Pro",
        "AMD Radeon RX 6600 (navi23, LLVM 15.0.7)",
    ],
)
def test_hardware_renderers_keep_opengl(renderer: str):
    use_gl, _ = classify_renderer(renderer)
    assert use_gl is True


@pytest.mark.parametrize("renderer", [None, ""])
def test_missing_renderer_falls_back_to_raster(renderer):
    use_gl, reason = classify_renderer(renderer)
    assert use_gl is False
    assert "no usable OpenGL context" in reason


def test_opengl_env_override_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ECHO_USE_OPENGL", "1")
    assert detect_opengl_capability() == (True, "forced by ECHO_USE_OPENGL")
    monkeypatch.setenv("ECHO_USE_OPENGL", "off")
    assert detect_opengl_capability() == (False, "disabled by ECHO_USE_OPENGL")


def test_headless_platform_skips_the_gl_probe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ECHO_USE_OPENGL", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    def _boom():  # pragma: no cover - must not be reached
        raise AssertionError("probed GL on a headless platform")

    monkeypatch.setattr("echo_personal_tool.infrastructure.system_profiler._probe_gl_renderer", _boom)

    use_gl, reason = detect_opengl_capability()

    assert use_gl is False
    assert "offscreen" in reason


def test_failed_probe_falls_back_to_raster(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ECHO_USE_OPENGL", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr("echo_personal_tool.infrastructure.system_profiler._probe_gl_renderer", lambda: None)

    use_gl, reason = detect_opengl_capability()

    assert use_gl is False
    assert "no usable OpenGL context" in reason


def test_remote_session_detection_is_false_off_windows(monkeypatch: pytest.MonkeyPatch):
    assert _is_remote_windows_session() is False
    # A lying sys.platform must not raise: ctypes.windll does not exist here.
    monkeypatch.setattr("echo_personal_tool.infrastructure.system_profiler.sys.platform", "win32")
    assert _is_remote_windows_session() is False


def test_remote_windows_session_skips_the_probe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ECHO_USE_OPENGL", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler._is_remote_windows_session",
        lambda: True,
    )

    def _boom():  # pragma: no cover - must not be reached
        raise AssertionError("probed GL inside a remote session")

    monkeypatch.setattr("echo_personal_tool.infrastructure.system_profiler._probe_gl_renderer", _boom)

    use_gl, reason = detect_opengl_capability()

    assert use_gl is False
    assert "remote Windows session" in reason
