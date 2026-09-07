"""Runtime detection for playback tuning on low-end vs high-end systems."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

import psutil

_LOG = logging.getLogger(__name__)

_LOW_END_CORES = 2
_LOW_END_RAM_GIB = 8.0
# Below this much *free* memory the economical profile is used no matter how big the
# machine is: a 32 GB box with 1.5 GB left behaves like a weak one for the next minutes.
_LOW_END_AVAILABLE_GIB = 2.0


@dataclass(frozen=True)
class PlaybackConfig:
    """Adaptive playback tuning detected at startup."""

    prefetch_radius: int  # floor for decoded frames ahead of playhead; stop prefetch when reached
    min_buffer: int  # minimum ahead before playback is considered healthy (lag-skip threshold input)
    batch_size: int  # max frames per prefetch worker run (capped by prefetch_radius - ahead)
    max_lag_frames: int  # skip forward when loaded ahead exceeds this but next frame missing
    evict_window: int  # FrameCache LRU half-width around current index
    scroll_debounce_ms: int  # wheel coalesce window
    scroll_batch_size: int  # neighbor prefetch after scroll target frame
    # Buffer depth in seconds of playback ahead of the playhead. A radius counted in frames
    # (5/10) is only 0.08-0.33 s at 30-60 fps and does not survive one slow decode batch;
    # the controller converts this to frames and caps it by what the frame cache can hold.
    # Defaulted so existing PlaybackConfig(...) constructions keep working.
    prefetch_seconds: float = 1.0


_LOW_END = PlaybackConfig(
    prefetch_radius=5,
    min_buffer=3,
    batch_size=5,
    max_lag_frames=2,
    evict_window=12,
    scroll_debounce_ms=80,
    scroll_batch_size=3,
    prefetch_seconds=1.0,
)

_HIGH_END = PlaybackConfig(
    prefetch_radius=10,
    min_buffer=5,
    batch_size=8,
    max_lag_frames=4,
    evict_window=20,
    scroll_debounce_ms=50,
    scroll_batch_size=8,
    prefetch_seconds=1.5,
)


def detect_playback_config() -> PlaybackConfig:
    """Pick the playback tuning profile from core count and memory.

    Memory is measured in GiB (1024**3) and against what is *available*, not installed.
    The previous ``total / 1e9 <= 8.0`` test classified an 8 GiB machine as 8.59 "GB" and
    therefore handed it the high-end profile - the more demanding one - exactly where the
    economical one was needed, and it ignored a nearly exhausted machine of any size.
    """
    cores = os.cpu_count() or 2
    mem = psutil.virtual_memory()
    total_gib = mem.total / 1024**3
    # `available` is what the kernel reports as reclaimable+free; fall back to `total` for
    # callers (and test shims) that only provide the installed amount.
    available_gib = getattr(mem, "available", mem.total) / 1024**3
    is_low_end = cores <= _LOW_END_CORES or total_gib <= _LOW_END_RAM_GIB or available_gib < _LOW_END_AVAILABLE_GIB
    return _LOW_END if is_low_end else _HIGH_END


# ── OpenGL capability ──────────────────────────────────────────────────────────────

# Software rasterisers. pyqtgraph's `useOpenGL` swaps the QGraphicsView viewport to a GL
# surface (ImageItem still goes through QImage + QPainter in pyqtgraph 0.13/0.14), so the
# only thing it buys this viewer is GL compositing of 2D blits - which a software GL stack
# does slower than Qt's raster paint engine, while also costing a context and a driver.
_SOFTWARE_GL_TOKENS = (
    "llvmpipe",
    "softpipe",
    "swrast",
    "software rasterizer",
    "software renderer",
    "software adapter",
    "basic render driver",
    "gdi generic",
    "warp",
)

# Qt platform plugins with no real display: probing GL there is either meaningless or
# (offscreen in CI) a way to make a headless run depend on a GL stack it does not need.
_HEADLESS_QPA_PLATFORMS = ("offscreen", "minimal", "vnc", "minimalgl")


def _is_remote_windows_session() -> bool:
    """True inside an RDP/Citrix session, where Windows hands out WARP software GL."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        sm_remotesession = 0x1000
        return bool(ctypes.windll.user32.GetSystemMetrics(sm_remotesession))
    except Exception:  # noqa: BLE001 - never let a probe decide whether the app starts
        return False


def _probe_gl_renderer() -> str | None:
    """Renderer string of a throwaway GL context, or None when no context can be made.

    Needs a QApplication (created before this is called in main()). The context is
    destroyed again: keeping it would make the viewer's first real context share with a
    probe that has no swap chain.
    """
    try:
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
    except Exception:  # noqa: BLE001
        return None
    context = None
    surface = None
    try:
        context = QOpenGLContext()
        if not context.create():
            return None
        surface = QOffscreenSurface()
        surface.setFormat(context.format())
        surface.create()
        if not surface.isValid() or not context.makeCurrent(surface):
            return None
        gl_renderer = 0x1F01
        value = context.functions().glGetString(gl_renderer)
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", "replace")
        return str(value).strip() or None
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            if context is not None:
                context.doneCurrent()
                context.destroy()
            if surface is not None:
                surface.destroy()
        except Exception:  # noqa: BLE001
            pass


def classify_renderer(renderer: str | None) -> tuple[bool, str]:
    """Decide ``useOpenGL`` from a GL renderer string. Split out so it is testable
    without a GL stack: the interesting cases (WARP over RDP, llvmpipe in a VM) are
    exactly the ones a dev machine cannot reproduce."""
    if not renderer:
        return False, "no usable OpenGL context"
    lowered = renderer.lower()
    for token in _SOFTWARE_GL_TOKENS:
        if token in lowered:
            return False, f"software GL renderer: {renderer}"
    return True, f"hardware GL renderer: {renderer}"


def detect_opengl_capability() -> tuple[bool, str]:
    """Whether pyqtgraph should render through OpenGL, and why (logged once).

    Falls back to raster on headless platforms, remote Windows sessions and software GL,
    all of which are slower than Qt's raster engine for this viewer's 2D blits.
    ``ECHO_USE_OPENGL=0|1`` overrides the probe (support, CI, driver regressions).
    """
    use_opengl, reason = _detect_opengl_capability()
    _LOG.info("pyqtgraph useOpenGL=%s (%s)", use_opengl, reason)
    return use_opengl, reason


def _detect_opengl_capability() -> tuple[bool, str]:
    override = os.environ.get("ECHO_USE_OPENGL", "").strip().lower()
    if override in ("0", "false", "no", "off"):
        return False, "disabled by ECHO_USE_OPENGL"
    if override in ("1", "true", "yes", "on"):
        return True, "forced by ECHO_USE_OPENGL"

    qpa = os.environ.get("QT_QPA_PLATFORM", "").strip().lower()
    if qpa in _HEADLESS_QPA_PLATFORMS:
        return False, f"QT_QPA_PLATFORM={qpa} has no real display"
    if _is_remote_windows_session():
        return False, "remote Windows session (WARP software GL)"
    return classify_renderer(_probe_gl_renderer())
