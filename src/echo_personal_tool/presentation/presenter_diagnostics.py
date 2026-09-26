"""Presenter-mode diagnostics — a self-contained file log for real-machine runs.

The presentation window works on the developer's machine but has repeatedly
failed on a real Debian 12 / Qt 6.4 / Intel setup in ways offscreen tests
cannot reproduce.  This module writes a small, always-on (unless disabled)
per-session log next to the application's regular ``diag.log`` so one demo
run is enough to see:

- the Qt/pyqtgraph environment (platform, versions, ``useOpenGL`` config);
- every screen Qt knows about (name/geometry/DPR/primary) and which one the
  presentation window actually landed on;
- which viewport class the audience viewer got (GL vs raster);
- frame-forwarding counters, render-cost EMA, pacing skips;
- any exception swallowed by the forwarding chain (with traceback);
- a 1 Hz probe of both viewers' frame data (and the audience GL framebuffer
  brightness when GL is active — a black framebuffer with non-black frame
  data is the definitive GL-blank signature).

Disable with ``SONOFORGE_PRESENTER_DIAG=0``.  Under pytest the default is
disabled so tests never write to the user's diag directory; tests that
exercise the module construct it with an explicit path.
"""

from __future__ import annotations

import os
import time
import traceback
from pathlib import Path
from typing import Any

_DISABLE_ENV = "SONOFORGE_PRESENTER_DIAG"

_STR_LIMIT = 160


def default_log_path() -> Path:
    """Next to the regular diag.log (same directory, presenter-specific file)."""
    from echo_personal_tool.infrastructure.profile import diag_log_dir

    return Path(diag_log_dir()) / "presenter_diag.log"


def default_enabled() -> bool:
    raw = os.environ.get(_DISABLE_ENV, "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False  # tests construct PresenterDiagnostics(path=...) explicitly
    return True


class PresenterDiagnostics:
    """Append-only session log with counters; never raises."""

    def __init__(self, path: str | Path | None = None, enabled: bool | None = None) -> None:
        self.path = Path(path) if path is not None else default_log_path()
        self.enabled = default_enabled() if enabled is None else enabled
        self.counters: dict[str, int] = {}
        self._t0 = time.monotonic()
        self._session = time.strftime("%Y%m%d-%H%M%S")
        self.event("session_start", path=str(self.path))

    # ── writing ─────────────────────────────────────────────────────

    def event(self, kind: str, **fields: Any) -> None:
        if not self.enabled:
            return
        stamp = time.strftime("%H:%M:%S")
        parts = " ".join(f"{key}={self._fmt(value)}" for key, value in fields.items())
        self._write(f"{stamp} [{self._session}] {kind} {parts}".rstrip())

    def exception(self, kind: str, exc: BaseException) -> None:
        if not self.enabled:
            return
        self.event(kind, error=repr(exc))
        tb = "".join(traceback.format_exception(exc)).rstrip()
        if tb:
            self._write(tb)

    def counter(self, name: str, delta: int = 1) -> int:
        self.counters[name] = self.counters.get(name, 0) + delta
        return self.counters[name]

    def finish(self, reason: str) -> None:
        self.event(
            "session_end",
            reason=reason,
            duration_s=round(time.monotonic() - self._t0, 1),
            **dict(self.counters),
        )

    def _write(self, line: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    @staticmethod
    def _fmt(value: Any) -> str:
        if value is None:
            return "none"
        if isinstance(value, float):
            return f"{value:.1f}"
        text = str(value)
        if len(text) > _STR_LIMIT:
            text = text[:_STR_LIMIT] + "…"
        return text


# ── frame probes (pure, testable) ───────────────────────────────────


def summarize_array(arr: Any) -> dict[str, Any]:
    """Compact data-level summary of a viewer frame (no pixel copies)."""
    if arr is None:
        return {"frame": "none"}
    try:
        import numpy as np

        a = np.asarray(arr)
        if a.size == 0:
            return {"frame": "empty"}
        return {
            "frame": f"{a.shape[1]}x{a.shape[0]}" if a.ndim >= 2 else f"len={a.shape[0]}",
            "dtype": str(a.dtype),
            "min": int(a.min()),
            "max": int(a.max()),
        }
    except Exception as exc:  # noqa: BLE001 — probe must never raise
        return {"frame": f"error:{exc!r}"}


def qimage_brightness(image: Any) -> float | None:
    """Mean brightness (0-255) of a QImage, downsampled; None on failure.

    Used on the audience GL viewport: a ~0 value while the frame data is
    non-black is the definitive "GL renders black on this screen" probe.
    """
    try:
        import numpy as np

        small = image.scaled(32, 32)
        buf = small.constBits()
        arr = np.frombuffer(buf, dtype=np.uint8)
        arr = arr.reshape(small.height(), small.bytesPerLine())
        arr = arr[:, : small.width() * 4]
        return float(arr.mean())
    except Exception:  # noqa: BLE001 — probe must never raise
        return None
