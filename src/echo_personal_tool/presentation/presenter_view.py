"""Presenter mode — PowerPoint-style presenter view (second-display window).

Architecture (deliberate, mirrors PowerPoint / LibreOffice Impress):

The audience display gets a **real, independently rendered window** — a
dedicated :class:`~echo_personal_tool.presentation.viewer_widget.ViewerWidget`
living in its own fullscreen top-level window on the target screen.  The
speaker's viewer keeps rendering on the speaker's display exactly as
before.  There is **no pixel copying** between the two: the presentation
window receives the same decoded frames / viewer state via signals and
renders them itself, the way PowerPoint renders the slide show on the
second display while the presenter console renders on the first.

Why not grab/pixel-mirror: with a GL-backed pyqtgraph viewport
(``useOpenGL=True``, auto-detected in ``main()``), ``QWidget.grab()``
cannot composite the QOpenGLWidget content (it renders directly to the
native window, bypassing the backing store) — grabs come out black in the
image area while raster child widgets (overlay labels) still show.  Each
grab also reads the GL framebuffer back on the main thread, contending
with the on-screen render path and visibly blanking the speaker's viewer
when it is idle.  Both failure modes are eliminated by rendering on the
target display instead of copying pixels.

Window placement uses the Qt-documented/community-proven sequence for
putting a window on a specific screen (``QWidget.setScreen`` *before*
``show()`` does not survive platform window creation — the window is
created on the default screen and fullscreen lands on the primary)::

    window.show()                       # platform window created here
    window.windowHandle().setScreen(target)
    window.setGeometry(target.geometry())
    window.showFullScreen()

followed by a deferred verification: if the platform placed the window
elsewhere, ``setScreen`` is re-asserted and fullscreen re-applied.  The
screen the window actually landed on is reported via the status bar, and
can always be changed from the Presenter menu.

Extras:

- **Laser pointer** — a translucent red dot on the presentation window at
  the position the speaker's cursor maps to in the shared image domain
  (exact mapping through the two views' coordinate transforms).
- **Projector visual preset** (optional, non-destructive): while the mode
  is active a projector-friendly set of preferences (thicker lines,
  larger fonts, inline caliper labels) is applied; the speaker's own
  preferences are restored on exit.

Exit: ``F10`` anywhere, or the Presenter button in the system bar.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QKeyEvent, QPainter, QScreen
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.user_preferences import (
    PRESENTATION_PRESET_OVERRIDES,
    UserPreferences,
)
from echo_personal_tool.presentation.presenter_diagnostics import (
    PresenterDiagnostics,
    qimage_brightness,
    summarize_array,
)
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

#: Distance from the top edge (px) that reveals the system bar — used by
#: the fullscreen kiosk mode in MainWindow; kept here for a single home.
TOP_EDGE_REVEAL_PX = 8

#: Tick for the laser-pointer overlay (ms).
_POINTER_TICK_MS = 33


def enlarged_arrow_cursor(size_px: int) -> QCursor | None:
    """A scaled-up arrow cursor for the audience display.

    Returns ``None`` when the platform cursor pixmap is unavailable
    (e.g. offscreen builds) — callers should skip the override then.
    """
    base = QCursor(Qt.CursorShape.ArrowCursor).pixmap()
    if base.isNull() or base.width() <= 1:
        return None
    scaled = base.scaled(
        size_px,
        size_px,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if scaled.isNull():
        return None
    return QCursor(scaled, 0, 0)


# ── Screen selection (pure, testable) ───────────────────────────────


def select_audience_screen(
    screens: list,
    *,
    remembered: str,
    primary=None,
    host_screen=None,
):
    """Pick the audience display (pure function, testable with fakes).

    Resolution order:

    1. explicitly remembered screen name — a deliberate user choice is
       honored even when it equals the host screen, UNLESS another screen
       exists (a stale remembered name saved on a single-display machine
       would otherwise put the fullscreen presentation on top of the
       working window on a two-display machine — observed in the field);
    2. the first screen that is NOT the speaker's current screen — the
       presentation window must never land on the display the presenter
       works on (a fullscreen window there would cover the application);
    3. the first non-primary screen (host screen unknown — the classic
       laptop + projector setup);
    4. the primary screen (single-display demo).
    """
    if not screens:
        return None
    if len(screens) == 1:
        return screens[0]
    if remembered:
        for screen in screens:
            if screen.name() == remembered:
                if host_screen is not None and screen is host_screen:
                    break  # stale choice would cover the app — fall through
                return screen
    if host_screen is not None:
        for screen in screens:
            if screen is not host_screen:
                return screen
    if primary is not None:
        for screen in screens:
            if screen is not primary:
                return screen
    return primary


# ── Laser-pointer overlay ───────────────────────────────────────────


class _PointerOverlay(QWidget):
    """Transparent overlay painting the laser-pointer dot."""

    def __init__(self, parent: QWidget, map_pos: Callable[[], QPoint | None]) -> None:
        super().__init__(parent)
        self._map_pos = map_pos
        self._dot: QPoint | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._timer = QTimer(self)
        self._timer.setInterval(_POINTER_TICK_MS)
        self._timer.timeout.connect(self._recompute)

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()
            self._dot = None
            self.update()

    @property
    def enabled(self) -> bool:
        return self._timer.isActive()

    def _recompute(self) -> None:
        pos = self._map_pos()
        if pos != self._dot:
            self._dot = pos
            self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if self._dot is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = max(12.0, min(self.width(), self.height()) * 0.012)
        for alpha, extra in ((50, radius), (170, radius * 0.55)):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.GlobalColor.red)
            painter.setOpacity(alpha / 255.0)
            painter.drawEllipse(self._dot, int(extra), int(extra))
        painter.setOpacity(1.0)
        painter.end()


# ── Presentation window ─────────────────────────────────────────────


def _create_viewer(render_mode: str) -> ViewerWidget:
    """ViewerWidget with the requested pyqtgraph rendering backend.

    ``useOpenGL`` is a pyqtgraph *construction-time* config option: it is
    temporarily overridden around widget creation and immediately restored
    so the speaker's viewer (and anything else constructed later) keeps the
    backend auto-detected in ``main()``.
    """
    import pyqtgraph as pg

    requested = render_mode == "opengl"
    previous = bool(pg.getConfigOption("useOpenGL"))
    if previous != requested:
        pg.setConfigOption("useOpenGL", requested)
    try:
        return ViewerWidget()
    finally:
        if previous != requested:
            pg.setConfigOption("useOpenGL", previous)


class PresenterWindow(QWidget):
    """Fullscreen, independently rendered viewer on the audience display.

    Contains its own :class:`ViewerWidget` fed with the same frames/state
    as the speaker's viewer (see :class:`PresenterMode`), plus the laser
    pointer overlay.  The embedded viewer is read-only: all mouse input is
    swallowed so the audience can never trigger tools, and the window
    never takes focus or activation away from the speaker's window.
    """

    #: Emitted after placement, with the screen the window actually landed on.
    placed = Signal(object)

    #: User asked to leave presenter mode (Esc/F10 fallback if focused).
    exit_requested = Signal()

    def __init__(
        self,
        target_screen: QScreen,
        *,
        speaker_viewer_provider: Callable[[], QWidget | None],
        pointer: bool = True,
        parent: QWidget | None = None,
        render_mode: str = "raster",
        diag: PresenterDiagnostics | None = None,
    ) -> None:
        super().__init__(parent)
        self._target_screen = target_screen
        self._speaker_viewer_provider = speaker_viewer_provider
        self._closed = False
        self._diag = diag
        self._render_mode = "opengl" if render_mode == "opengl" else "raster"
        self._last_drift_log = 0.0

        self.setObjectName("presenterWindow")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        # X11 hint: the platform itself refuses to give this window focus.
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        self.setStyleSheet("background-color: #000000;")
        # Showing the window must never steal focus/activation from the
        # speaker's window (the presenter keeps typing/clicking there).
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        cursor = enlarged_arrow_cursor(48)
        if cursor is not None:
            self.setCursor(cursor)

        # The independently rendered viewer shown to the audience.  Its
        # rendering backend is deliberate: raster by default (see
        # ``UserPreferences.presenter_audience_render``) because GL
        # viewports in a second top-level window have been observed to
        # stay black on real multi-monitor Linux boxes while every raster
        # overlay in the same window renders fine.
        self._viewer = _create_viewer(self._render_mode)
        self._viewer.setObjectName("presenterViewer")
        self._hide_speaker_controls(self._viewer)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._viewer)

        # The embedded viewer is strictly read-only: swallow all input
        # before it reaches the scene (no tools, no wheel zoom, no menus).
        self._viewer.installEventFilter(self)
        graphics = self._viewer._graphics
        graphics.installEventFilter(self)
        viewport = graphics.viewport()
        if viewport is not None:
            viewport.installEventFilter(self)

        # In-progress drawing previews (contour clicks / freehand stroke /
        # linear-caliper drag): mirrored at ~30 Hz from the speaker's
        # viewer while the tools are active — the audience sees the
        # drawing process, not only the committed result.
        import pyqtgraph as pg

        self._live_contour_item = pg.PlotDataItem(
            pen=pg.mkPen("#ffd54f", width=3)
        )
        self._live_contour_item.setZValue(40)
        self._live_contour_item.hide()
        self._viewer._view.addItem(self._live_contour_item)
        self._live_caliper_item = pg.PlotDataItem(
            pen=pg.mkPen("#4dd0e1", width=3),
            symbol="+",
            symbolSize=12,
            symbolPen=pg.mkPen("#4dd0e1", width=2),
        )
        self._live_caliper_item.setZValue(40)
        self._live_caliper_item.hide()
        self._viewer._view.addItem(self._live_caliper_item)

        self._overlay = _PointerOverlay(self, self._map_speaker_cursor)
        self._overlay.set_enabled(pointer)
        self._overlay.raise_()

        # A cheap periodic guard: keep the presentation on the audience
        # display (display hot-plug can move windows) and on top of any
        # window some desktop environments let sneak above a frameless
        # fullscreen window.  Never activates.
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._keep_on_top)

    # ── construction helpers ────────────────────────────────────────

    @staticmethod
    def _hide_speaker_controls(viewer: ViewerWidget) -> None:
        """Hide the playback controls row — that is speaker UI."""
        for attr in (
            "_timeline_slider",
            "_play_button",
            "_step_back_button",
            "_step_forward_button",
            "_fps_label",
            "_source_label",
        ):
            widget = getattr(viewer, attr, None)
            if widget is not None:
                try:
                    widget.hide()
                except RuntimeError:
                    pass

    # ── accessors ───────────────────────────────────────────────────

    def viewer(self) -> ViewerWidget:
        """The presentation viewer rendered on the audience display."""
        return self._viewer

    @property
    def render_mode(self) -> str:
        """Rendering backend requested for the audience viewer."""
        return self._render_mode

    def viewport_class_name(self) -> str:
        """Actual viewport widget class — "OpenGL…" means GL, "QWidget" raster."""
        return _viewport_class(self._viewer)

    def gl_viewport_brightness(self) -> float | None:
        """Mean framebuffer brightness when the viewport is GL, else ``None``.

        A ~0 value while the frame data is non-black is the definitive
        "GL renders black on this screen" signature.
        """
        try:
            viewport = self._viewer._graphics.viewport()
        except (RuntimeError, AttributeError):
            return None
        if viewport is None or "opengl" not in type(viewport).__name__.lower():
            return None
        try:
            return qimage_brightness(viewport.grabFramebuffer())
        except Exception:  # noqa: BLE001
            return None

    @property
    def pointer_enabled(self) -> bool:
        return self._overlay.enabled

    def set_pointer_enabled(self, enabled: bool) -> None:
        self._overlay.set_enabled(enabled)

    def target_screen(self) -> QScreen:
        return self._target_screen

    # ── placement (the Qt multi-monitor recipe) ─────────────────────

    def start(self) -> None:
        """Show fullscreen on the target screen and verify placement.

        ``windowHandle()`` exists only after the widget is shown, and the
        platform window is created on the default screen — so the correct
        sequence is show → setScreen(handle) → geometry → fullscreen.
        """
        self._closed = False
        diag = self._diag
        if diag is not None:
            diag.event(
                "placement_begin",
                target=self._target_screen.name(),
                target_geometry=self._target_screen.geometry(),
                render_mode=self._render_mode,
            )
        self.show()  # realize the platform window (lands on default screen)
        handle = self.windowHandle()
        if diag is not None:
            diag.event(
                "placement_shown",
                handle_screen=handle.screen().name() if handle is not None else None,
            )
        if handle is not None:
            handle.setScreen(self._target_screen)
        self.setGeometry(self._target_screen.geometry())
        self.showFullScreen()
        if diag is not None and handle is not None:
            diag.event(
                "placement_fullscreen",
                handle_screen=handle.screen().name(),
                geometry=self.geometry(),
            )
        self._timer.start()
        QTimer.singleShot(0, self._verify_placement)

    def _verify_placement(self) -> None:
        handle = self.windowHandle()
        actual = handle.screen() if handle is not None else None
        if actual is not self._target_screen and handle is not None:
            # Platform put the window on another screen: re-assert.
            if self._diag is not None:
                self._diag.event(
                    "placement_reassert",
                    actual=actual.name() if actual is not None else None,
                    wanted=self._target_screen.name(),
                )
            handle.setScreen(self._target_screen)
            self.setGeometry(self._target_screen.geometry())
            self.showFullScreen()
            handle = self.windowHandle()
            actual = handle.screen() if handle is not None else actual
        if self._diag is not None:
            self._diag.event(
                "placement_done",
                actual=actual.name() if actual is not None else None,
                viewport=self.viewport_class_name(),
                fullscreen=self.isFullScreen(),
                visible=self.isVisible(),
            )
        self.placed.emit(actual)

    def _keep_on_top(self) -> None:
        """Stay on the audience display and on top; never activate."""
        if not self.isVisible() or self._closed:
            return
        handle = self.windowHandle()
        if handle is not None and handle.screen() is not self._target_screen:
            # The window drifted to another screen (display hot-plug):
            # bring it back to the audience display.
            if self._diag is not None:
                now = time.monotonic()
                if now - self._last_drift_log > 1.0:
                    self._last_drift_log = now
                    self._diag.event(
                        "placement_drift",
                        actual=handle.screen().name(),
                        wanted=self._target_screen.name(),
                    )
            handle.setScreen(self._target_screen)
            self.setGeometry(self._target_screen.geometry())
            self.showFullScreen()
        self.raise_()

    def stop(self) -> None:
        self._closed = True
        self._timer.stop()
        self._overlay.set_enabled(False)
        for item in (self._live_contour_item, self._live_caliper_item):
            try:
                self._viewer._view.removeItem(item)
            except (RuntimeError, Exception):  # noqa: BLE001 — teardown-safe
                pass
        try:
            self._viewer.disconnect_display_controls()
        except Exception:
            pass
        self.close()

    # ── laser pointer mapping ───────────────────────────────────────

    def _map_speaker_cursor(self) -> QPoint | None:
        """Cursor position over the speaker's viewer, in our local coords.

        Both viewers display the same image domain, so the mapping goes
        through the image (view) coordinates of each view — exact even
        when the two windows have different sizes.
        """
        speaker = self._speaker_viewer_provider()
        if speaker is None:
            return None
        try:
            local = speaker.mapFromGlobal(QCursor.pos())
            if not speaker.rect().contains(local):
                return None
            scene = speaker._graphics.mapToScene(local)
            image_pos = speaker._view.mapSceneToView(scene)
            scene_here = self._viewer._view.mapViewToScene(image_pos)
            return self._viewer._graphics.mapFromScene(scene_here)
        except Exception:
            return None

    # ── interaction (read-only audience window) ─────────────────────

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        event_type = event.type()
        if event_type in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
            QEvent.Type.ContextMenu,
        ):
            event.accept()
            return True  # never reach the scene
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        # Fallback only — the window normally never has focus.
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F10):
            event.accept()
            self.stop()
            self.exit_requested.emit()
            return
        event.ignore()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # WM/programmatic close: stop internals.  The PresenterMode
        # controller owns the lifecycle and reacts to ``destroyed`` —
        # emitting ``exit_requested`` here would re-enter stop().
        self._closed = True
        self._timer.stop()
        self._overlay.set_enabled(False)
        event.accept()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        event.accept()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.accept()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._overlay.resize(self.size())


# ── Preferences lifecycle helpers ───────────────────────────────────

#: Fields the projector preset owns — user edits to these on the host's
#: effective copy during a presentation are preset artifacts, not intent,
#: and are never merged back into the speaker's base preferences.
_PRESET_OWNED_FIELDS = frozenset(PRESENTATION_PRESET_OVERRIDES) | {
    "presenter_screen",
    "presenter_visual_preset",
    "presenter_pointer",
}


def sanitized_preset(base: UserPreferences) -> dict[str, object]:
    """Preset overrides clamped against the same ranges the dialogs use."""
    from echo_personal_tool.infrastructure.user_preferences import (
        MAX_LINE_WIDTH,
        MAX_OVERLAY_FONT_SIZE,
        MAX_OVERLAY_OPACITY,
        MAX_UI_FONT_SIZE,
        MIN_LINE_WIDTH,
        MIN_OVERLAY_FONT_SIZE,
        MIN_OVERLAY_OPACITY,
        MIN_UI_FONT_SIZE,
    )

    return {
        "ui_font_size": _clamp(
            PRESENTATION_PRESET_OVERRIDES["ui_font_size"],
            base.ui_font_size,
            MIN_UI_FONT_SIZE,
            MAX_UI_FONT_SIZE,
        ),
        "results_overlay_font_size": _clamp(
            PRESENTATION_PRESET_OVERRIDES["results_overlay_font_size"],
            base.results_overlay_font_size,
            MIN_OVERLAY_FONT_SIZE,
            MAX_OVERLAY_FONT_SIZE,
        ),
        "results_overlay_opacity": _clamp(
            PRESENTATION_PRESET_OVERRIDES["results_overlay_opacity"],
            base.results_overlay_opacity,
            MIN_OVERLAY_OPACITY,
            MAX_OVERLAY_OPACITY,
        ),
        "caliper_line_width": _clamp(
            PRESENTATION_PRESET_OVERRIDES["caliper_line_width"],
            base.caliper_line_width,
            MIN_LINE_WIDTH,
            MAX_LINE_WIDTH,
        ),
        "contour_pen_manual_width": _clamp(
            PRESENTATION_PRESET_OVERRIDES["contour_pen_manual_width"],
            base.contour_pen_manual_width,
            MIN_LINE_WIDTH,
            MAX_LINE_WIDTH,
        ),
        "contour_pen_ai_width": _clamp(
            PRESENTATION_PRESET_OVERRIDES["contour_pen_ai_width"],
            base.contour_pen_ai_width,
            MIN_LINE_WIDTH,
            MAX_LINE_WIDTH,
        ),
        "contour_pen_simpson_width": _clamp(
            PRESENTATION_PRESET_OVERRIDES["contour_pen_simpson_width"],
            base.contour_pen_simpson_width,
            MIN_LINE_WIDTH,
            MAX_LINE_WIDTH,
        ),
        "show_caliper_labels_on_frame": PRESENTATION_PRESET_OVERRIDES["show_caliper_labels_on_frame"],
        "show_caliper_inline_labels": PRESENTATION_PRESET_OVERRIDES["show_caliper_inline_labels"],
        "show_crosshair": PRESENTATION_PRESET_OVERRIDES["show_crosshair"],
    }


def _clamp(value: object, fallback: object, low: float, high: float) -> object:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, parsed))


class _PaintCounter(QObject):
    """Counts Paint events of a watched widget (diagnostics only)."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.Paint:
            self.count += 1
        return False


def _viewport_class(viewer: QWidget) -> str:
    """Class name of the viewer's viewport ("OpenGL…" = GL, "QWidget" = raster)."""
    try:
        viewport = viewer._graphics.viewport()
    except (RuntimeError, AttributeError):
        return "dead"
    return type(viewport).__name__ if viewport is not None else "?"


# ── Controller ──────────────────────────────────────────────────────


class PresenterMode(QObject):
    """Controller binding the presentation window to a ``MainWindow`` host.

    The host must expose: ``_viewer`` (default viewer widget),
    ``_active_viewer`` (multiview active viewer or ``None``),
    ``_apply_user_preferences(preferences)`` and ``_show_status(message)``.

    Content flow (no pixel copying): the host forwards decoded frames,
    viewer state and the results-overlay text to :meth:`forward_frame` /
    :meth:`forward_state` / :meth:`forward_results_overlay`; the
    presentation viewer renders them independently on the audience
    display.

    Preferences lifecycle (non-destructive preset):

    - every host ``_apply_user_preferences`` call goes through
      :meth:`intercept_preferences`, which records the caller's object as
      the *base* (the speaker's intent) and, while presenting with the
      preset enabled, applies a preset-overlaid copy instead;
    - in-place changes made to the host copy during a presentation
      (tool-panel toggles, layout saves) are merged back into the base on
      exit, so nothing the user did while presenting is lost;
    - option toggles (screen / preset / pointer) always edit the base
      object, never the transient overlay copy.
    """

    def __init__(self, host) -> None:
        super().__init__(host)
        self._host = host
        self._window: PresenterWindow | None = None
        # The speaker's own preferences object — option toggles (screen,
        # pointer, preset) must always edit THIS object, never the preset
        # copy that temporarily replaces it on the host while active.
        self._base_prefs: UserPreferences | None = None
        # The effective object currently installed on the host (identity)
        # and a pristine copy of it — the reference point for the
        # merge-back diff.
        self._installed: UserPreferences | None = None
        self._installed_snapshot: UserPreferences | None = None
        # Guard: start/stop/repin apply the already-final object and must
        # not be re-intercepted (which would rebase onto the overlay copy).
        self._internal_apply = False
        # Real-machine diagnostics (file log; disabled under pytest and by
        # SONOFORGE_PRESENTER_DIAG=0).  Everything the forwarding chain
        # used to swallow silently is recorded here with a traceback.
        self._diag = PresenterDiagnostics()
        # Forwarding cost EMA + frame sequence for adaptive pacing.
        self._fwd_ema_ms = 0.0
        self._fwd_seq = 0
        # Diagnostics helpers: host-viewer paint counter, 1 Hz content
        # probe, and a keepalive repaint against GL-idle blanking.
        self._paint_counter = _PaintCounter()
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(1000)
        self._probe_timer.timeout.connect(self._probe_tick)
        self._keepalive_timer = QTimer(self)
        self._keepalive_timer.setInterval(250)
        self._keepalive_timer.timeout.connect(self._keepalive_tick)
        # ~30 Hz mirror of the speaker's in-progress drawing.
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(33)
        self._live_timer.timeout.connect(self._sync_live_overlays)

    # ── state ───────────────────────────────────────────────────────

    @property
    def active(self) -> bool:
        return self._window is not None

    def prefs_for_options(self) -> UserPreferences:
        """The preferences object option toggles must edit.

        While active, the host holds a preset copy — edits go to the saved
        base object instead (restored on stop).  When inactive, the host's
        live object.
        """
        if self.active and self._base_prefs is not None:
            return self._base_prefs
        return self._host._user_preferences

    # Backward-compatible alias.
    _prefs_for_options = prefs_for_options

    def window(self) -> PresenterWindow | None:
        return self._window

    # ── host apply interception ─────────────────────────────────────

    def intercept_preferences(self, preferences: UserPreferences) -> UserPreferences:
        """Called from the host's ``_apply_user_preferences`` on every apply.

        Records the caller's object as the base and returns the effective
        object to apply (preset-overlaid while presenting with the preset
        enabled).  Internal applies pass through unchanged.
        """
        if self._internal_apply:
            return preferences
        self._base_prefs = preferences
        return self._effective_for(preferences)

    def _effective_for(self, base: UserPreferences) -> UserPreferences:
        if self.active and getattr(base, "presenter_visual_preset", True):
            return replace(base, **sanitized_preset(base))
        return base

    def _apply_final(self, preferences: UserPreferences) -> None:
        """Apply an already-final object without re-interception."""
        self._internal_apply = True
        try:
            self._host._apply_user_preferences(preferences)
            self._installed = self._host._user_preferences
            self._installed_snapshot = replace(self._installed)
            window = self._window
            if window is not None:
                try:
                    window.viewer().apply_user_preferences(preferences)
                except RuntimeError:
                    pass
        finally:
            self._internal_apply = False

    def _reapply_current(self) -> None:
        base = self._base_prefs or self._host._user_preferences
        self._apply_final(self._effective_for(base))

    # ── start / stop ────────────────────────────────────────────────

    def start(self) -> None:
        if self.active:
            self.stop()
            return
        screen = self.resolve_screen()
        if screen is None:
            self._diag.event(
                "start_aborted",
                reason="no_screen",
                remembered=getattr(self.prefs_for_options(), "presenter_screen", ""),
            )
            self._show_status(tr("presenter.no_screen"))
            return
        self._log_environment()
        self._diag.event(
            "screen_selected",
            chosen=screen.name(),
            host=(
                self._host_screen().name()
                if self._host_screen() is not None
                else None
            ),
            remembered=getattr(self.prefs_for_options(), "presenter_screen", ""),
        )

        # Always re-read the host's live preferences object: the Settings
        # dialog replaces it between presentations.
        preferences = self._host._user_preferences
        self._base_prefs = preferences
        render_mode = str(
            getattr(preferences, "presenter_audience_render", "raster") or "raster"
        ).strip().lower()
        if render_mode not in ("raster", "opengl"):
            render_mode = "raster"

        def speaker_provider() -> QWidget | None:
            return getattr(self._host, "_active_viewer", None) or self._host._viewer

        window = PresenterWindow(
            screen,
            speaker_viewer_provider=speaker_provider,
            pointer=bool(getattr(preferences, "presenter_pointer", True)),
            render_mode=render_mode,
            diag=self._diag,
        )
        window.destroyed.connect(self._on_window_destroyed)
        window.exit_requested.connect(self.stop)
        window.placed.connect(self._on_placed)
        viewer = window.viewer()
        try:
            viewer._controller_ref = self._host._controller
        except AttributeError:
            pass
        try:
            viewer.set_scroll_debounce_ms(
                self._host._controller.playback_config.scroll_debounce_ms
            )
        except Exception:
            pass
        # The same W/L/DR sliders drive both viewers — live tone
        # adjustments reach the audience immediately.
        try:
            controls = self._host._tool_panel.controls
            viewer.bind_display_controls(
                controls.window_slider, controls.level_slider, controls.dr_slider
            )
        except Exception:
            pass
        self._window = window
        window.start()

        self._apply_final(self._effective_for(preferences))
        self._sync_initial_content()
        self._notify_active()
        self._diag.event(
            "session_started",
            render_mode=render_mode,
            audience_viewport=window.viewport_class_name(),
            host_viewport=_viewport_class(self._host._viewer),
            speaker_viewer=_viewport_class(speaker_provider()),
        )
        self._paint_counter.count = 0
        try:
            self._host._viewer.installEventFilter(self._paint_counter)
        except (RuntimeError, AttributeError):
            pass
        self._probe_timer.start()
        self._keepalive_timer.start()
        self._live_timer.start()

    def _log_environment(self) -> None:
        """One-time environment dump at presenter start (diagnostics)."""
        diag = self._diag
        if not diag.enabled:
            return
        try:
            import pyqtgraph as pg

            pg_version = str(getattr(pg, "__version__", "?"))
            use_opengl = bool(pg.getConfigOption("useOpenGL"))
        except Exception:  # noqa: BLE001
            pg_version, use_opengl = "?", None
        try:
            from PySide6.QtCore import qVersion
            from PySide6.QtGui import QGuiApplication

            qt_version = qVersion()
            platform_name = QGuiApplication.platformName()
        except Exception:  # noqa: BLE001
            qt_version, platform_name = "?", "?"
        app = QApplication.instance()
        screens = [
            {
                "name": s.name(),
                "geometry": s.geometry(),
                "dpr": s.devicePixelRatio(),
                "primary": app is not None and s is app.primaryScreen(),
            }
            for s in (app.screens() if app is not None else [])
        ]
        diag.event(
            "environment",
            qt=qt_version,
            pyqtgraph=pg_version,
            useOpenGL_config=use_opengl,
            platform=platform_name,
            screens=screens,
        )

    def _probe_tick(self) -> None:
        """1 Hz data-level probe of both viewers (diagnostics file)."""
        diag = self._diag
        window = self._window
        if not diag.enabled or window is None:
            return
        fields: dict[str, object] = {
            "audience": self._viewer_frame_summary(window.viewer()),
            "audience_visible": window.isVisible(),
            "audience_screen": (
                window.windowHandle().screen().name()
                if window.windowHandle() is not None
                else None
            ),
            "host": self._viewer_frame_summary(getattr(self._host, "_viewer", None)),
            "host_paints": self._paint_counter.count,
            "rendered": diag.counters.get("frames_rendered", 0),
            "fwd_ema_ms": round(self._fwd_ema_ms, 1),
        }
        brightness = window.gl_viewport_brightness()
        if brightness is not None:
            fields["audience_gl_brightness"] = round(brightness, 1)
        diag.event("probe", **fields)

    @staticmethod
    def _viewer_frame_summary(viewer) -> dict:
        try:
            return summarize_array(viewer._current_frame)
        except (RuntimeError, AttributeError):
            return {"frame": "unavailable"}

    def _keepalive_tick(self) -> None:
        """Scheduled repaint of the speaker's viewer.

        Qt 6.4 (Debian 12) with GL viewports: a viewer that is not
        repainting can be left blank by backing-store recompositions
        triggered by other windows — observed as "the image appears and
        disappears on the speaker's monitor" while the cursor is over
        tool panels.  A cheap scheduled update keeps the content
        recomposited; it cannot blank anything by itself.
        """
        try:
            self._host._viewer.update()
        except (RuntimeError, AttributeError):
            return
        self._diag.counter("keepalive")

    def _sync_live_overlays(self) -> None:
        """~30 Hz mirror of the speaker's in-progress drawing.

        Both preview workflows keep their geometry in viewer-local plot
        items, which nothing re-broadcasts: the active-contour item
        (click-by-click nodes and the freehand stroke) and the linear
        caliper's line. Poll them and paint the same data on the audience
        view — the audience watches the drawing process, not just the
        committed result.
        """
        window = self._window
        if window is None:
            return
        try:
            host = self._host._viewer
            audience = window.viewer()
            # In-progress contour (click nodes / freehand stroke).
            host_item = getattr(host, "_active_contour_item", None)
            drawing = (
                bool(getattr(host, "_contour_mode_active", False))
                and host_item is not None
            )
            shown = False
            if drawing:
                x, y = host_item.getData()
                if x is not None and len(x) > 0:
                    pen = host_item.opts.get("pen")
                    if pen is not None:
                        window._live_contour_item.setPen(pen)
                    window._live_contour_item.setData(
                        [float(v) for v in x], [float(v) for v in y]
                    )
                    shown = True
            if shown:
                window._live_contour_item.show()
            else:
                window._live_contour_item.hide()
            # In-progress linear caliper (endpoint drag).
            cal_shown = False
            if bool(getattr(host, "_linear_caliper_active", False)):
                line_item = getattr(host, "_linear_caliper_line_item", None)
                if line_item is not None:
                    x, y = line_item.getData()
                    if x is not None and len(x) >= 2:
                        pen = line_item.opts.get("pen")
                        if pen is not None:
                            window._live_caliper_item.setPen(pen)
                        window._live_caliper_item.setData(
                            [float(v) for v in x], [float(v) for v in y]
                        )
                        cal_shown = True
            if cal_shown:
                window._live_caliper_item.show()
            else:
                window._live_caliper_item.hide()
        except (RuntimeError, AttributeError) as exc:
            self._diag.exception("live_preview", exc)
            return
        except Exception as exc:  # noqa: BLE001 — preview must never fatal
            self._diag.exception("live_preview", exc)

    def _record_forward_ms(self, ms: float) -> None:
        self._fwd_ema_ms = (
            ms if self._fwd_ema_ms <= 0.0 else 0.9 * self._fwd_ema_ms + 0.1 * ms
        )

    def _on_placed(self, actual_screen) -> None:
        """Report where the presentation window actually landed."""
        if self._window is None:
            return
        host_screen = self._host_screen()
        self._diag.event(
            "placed_report",
            actual=actual_screen.name() if actual_screen is not None else None,
            target=self._window.target_screen().name(),
            host=host_screen.name() if host_screen is not None else None,
            viewport=self._window.viewport_class_name(),
        )
        if host_screen is not None and actual_screen is host_screen:
            self._show_status(tr("presenter.same_screen_warning"))
            return
        if actual_screen is not None and actual_screen is not self._window.target_screen():
            self._show_status(
                tr("presenter.placement_mismatch").format(screen=actual_screen.name())
            )
            return
        name = actual_screen.name() if actual_screen is not None else "?"
        self._show_status(tr("presenter.status_on_screen").format(screen=name))

    def _sync_initial_content(self) -> None:
        """Push the currently shown frame/state/overlay to the presentation."""
        window = self._window
        if window is None:
            return
        viewer = window.viewer()
        pushed: dict[str, object] = {}
        try:
            frame = self._host._viewer._current_frame
            if frame is not None:
                viewer.show_frame(np.asarray(frame))
                pushed["initial_frame"] = summarize_array(frame)
        except (RuntimeError, AttributeError) as exc:
            self._diag.exception("sync_initial_frame", exc)
        try:
            viewer.set_state(self._host._controller.state_manager.snapshot)
            pushed["initial_state"] = True
        except Exception as exc:  # noqa: BLE001
            self._diag.exception("sync_initial_state", exc)
        try:
            text = self._host._viewer._results_overlay_label.text()
            if text:
                viewer.set_results_overlay(text)
                pushed["initial_overlay_chars"] = len(text)
        except (RuntimeError, AttributeError) as exc:
            self._diag.exception("sync_initial_overlay", exc)
        try:
            x_ratio, y_ratio = self._host._viewer.results_overlay_position()
            viewer.set_results_overlay_position(float(x_ratio), float(y_ratio))
            pushed["initial_overlay_pos"] = (round(float(x_ratio), 3), round(float(y_ratio), 3))
        except (RuntimeError, AttributeError):
            pass
        self.forward_doppler()
        self._diag.event("content_sync", **pushed)

    # ── content forwarding (no pixel copying) ───────────────────────

    def forward_frame(self, image: np.ndarray) -> None:
        """Render a decoded frame on the presentation viewer."""
        window = self._window
        if window is None:
            return
        diag = self._diag
        self._fwd_seq += 1
        started = time.perf_counter()
        try:
            viewer = window.viewer()
            snapshot = self._host._controller.state_manager.snapshot
            playing = bool(snapshot.is_playing) or bool(
                self._host._controller.is_scroll_active()
            )
            if playing:
                # Adaptive pacing: rendering the audience copy costs real
                # main-thread time; when it is expensive, skip intermediate
                # frames instead of stalling the speaker's playback.
                # NEVER pace idle frames: a file switch delivers exactly ONE
                # frame — skipping it left the old image on the audience
                # while contours already arrived (field report #3).
                limit = (
                    1
                    if self._fwd_ema_ms <= 12.0
                    else (2 if self._fwd_ema_ms <= 25.0 else 3)
                )
                if limit > 1 and self._fwd_seq % limit != 0:
                    diag.counter("frames_skipped")
                    return
                viewer.show_frame_fast(np.asarray(image))
            else:
                viewer.show_frame(np.asarray(image))
        except Exception as exc:  # noqa: BLE001 — recorded, never fatal
            diag.counter("forward_errors")
            diag.exception("forward_frame", exc)
            return
        diag.counter("frames_rendered")
        self._record_forward_ms((time.perf_counter() - started) * 1000.0)
        if not playing:
            # Idle path: the host has already re-animated the saved doppler
            # measurement for this frame (_on_frame_loaded) — mirror it.
            self.forward_doppler()

    def forward_state(self, state) -> None:
        """Mirror a viewer-state update onto the presentation viewer."""
        window = self._window
        if window is None:
            return
        try:
            window.viewer().set_state(state)
        except Exception as exc:  # noqa: BLE001
            self._diag.counter("forward_errors")
            self._diag.exception("forward_state", exc)
            return
        self._diag.counter("states_forwarded")

    def forward_results_overlay(self, text: str) -> None:
        """Mirror the results-overlay text onto the presentation viewer."""
        window = self._window
        if window is None:
            return
        try:
            window.viewer().set_results_overlay(text)
        except Exception as exc:  # noqa: BLE001
            self._diag.counter("forward_errors")
            self._diag.exception("forward_results_overlay", exc)
            return
        self._diag.counter("overlays_forwarded")

    def forward_contours(self, contours) -> None:
        """Mirror an edited contour set onto the presentation viewer.

        ``AppController.on_contours_changed`` stores contours with
        ``emit=False`` — ``state_changed`` never fires while the presenter
        drags contour points (Simpson manual / auto-Simpson refinement), so
        this explicit forward is the only path that reaches the audience.

        Two subtleties make a plain ``set_state`` re-render unreliable here:

        - the host mutates ``Contour.points`` **in place** during point
          drags, and the audience stored set aliases those lists — the
          value-equality check inside ``set_state`` then sees "no change"
          and skips the re-render (observed on a real machine: dragging
          contour points did not update the audience, while mitral-annulus
          edits — which create new Contour objects — did);
        - therefore the audience gets *fresh copies* via
          ``apply_contours`` (public API), which re-renders
          unconditionally.
        """
        window = self._window
        if window is None:
            return
        try:
            viewer = window.viewer()
            fresh = [
                replace(contour, points=list(contour.points))
                for contour in contours
            ]
            viewer.apply_contours(fresh)
            viewer._refresh_frame_overlays()
            window._live_contour_item.hide()
        except Exception as exc:  # noqa: BLE001
            self._diag.counter("forward_errors")
            self._diag.exception("forward_contours", exc)
            return
        self._diag.counter("contours_forwarded")

    def forward_linear_measurements(self, measurements) -> None:
        """Mirror edited linear measurements (calipers) onto the presentation.

        Same rationale as :meth:`forward_contours` — caliper edits reach the
        controller with ``emit=False`` and would never re-render the
        audience viewer through ``state_changed``.
        """
        window = self._window
        if window is None:
            return
        try:
            snapshot = self._host._controller.state_manager.snapshot
            window.viewer().set_state(
                replace(snapshot, linear_measurements=tuple(measurements))
            )
        except Exception as exc:  # noqa: BLE001
            self._diag.counter("forward_errors")
            self._diag.exception("forward_linear_measurements", exc)
            return
        self._diag.counter("linear_forwarded")

    def forward_results_overlay_position(self, x_ratio: float, y_ratio: float) -> None:
        """Mirror a results-overlay drag onto the presentation viewer."""
        window = self._window
        if window is None:
            return
        try:
            window.viewer().set_results_overlay_position(
                float(x_ratio), float(y_ratio)
            )
        except Exception as exc:  # noqa: BLE001
            self._diag.counter("forward_errors")
            self._diag.exception("forward_overlay_position", exc)
            return
        self._diag.counter("overlay_positions_forwarded")

    def forward_doppler(self, *_args) -> None:
        """Mirror the doppler display (markers/VTI traces/vessel) to the audience.

        The spectral strip's markers (peak dots, interval markers), VTI/vessel
        traces and the calibration state live viewer-locally: only explicit
        signals carry them, and none reach ``state_changed``.  Called from the
        host's ``doppler_markers_changed`` / ``doppler_calibration_changed`` /
        ``spectral_calibration_completed`` / overlay ``vessel_changed`` hooks,
        and after every idle frame forward (the host re-animates the saved
        measurement for the new frame before our hook runs).
        """
        window = self._window
        if window is None:
            return
        try:
            host_viewer = self._host._viewer
            audience = window.viewer()
            # 1. markers + traces (VTI etc.) — DTO round-trip; also clears
            #    previous audience markers/vessel so deletions propagate.
            audience.restore_doppler_measurements(host_viewer.get_doppler_dto())
            # 2. calibration (ROI/baseline/axis mapping) — markers are in
            #    view pixels; the audience needs the same axes mapping.
            calibration = host_viewer.get_doppler_calibration_state()
            if calibration is not None:
                audience.apply_doppler_calibration_state(calibration, persist=False)
            # 3. vessel caliper display (PSV/EDV dots and lines).
            vessel_values = host_viewer._doppler.get_vessel_values()
            if vessel_values is not None:
                psv, edv = vessel_values
                snapshot = self._host._controller.state_manager.snapshot
                audience._doppler.show_vessel_measurement(
                    VesselMeasurement(
                        psv_cm_s=float(psv),
                        edv_cm_s=float(edv),
                        ri=None,
                        sd=None,
                        mv_approx=0.0,
                        sop_instance_uid=(
                            snapshot.instance.sop_instance_uid
                            if snapshot.instance is not None
                            else ""
                        ),
                        frame_index=snapshot.current_frame_index,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            self._diag.counter("forward_errors")
            self._diag.exception("forward_doppler", exc)
            return
        self._diag.counter("doppler_forwarded")

    # ── stop / lifecycle ────────────────────────────────────────────

    def stop(self) -> None:
        self._stop_diagnostics_helpers()
        window = self._window
        if window is not None:
            self._window = None
            try:
                window.stop()
                window.deleteLater()
            except RuntimeError:
                pass
        self._diag.finish("stop")
        self._restore_preferences()
        self._show_status(tr("presenter.status_off"))
        self._notify_active()

    def _stop_diagnostics_helpers(self) -> None:
        self._probe_timer.stop()
        self._keepalive_timer.stop()
        self._live_timer.stop()
        try:
            self._host._viewer.removeEventFilter(self._paint_counter)
        except (RuntimeError, AttributeError):
            pass

    def toggle(self) -> None:
        if self.active:
            self.stop()
        else:
            self.start()

    def _notify_active(self) -> None:
        try:
            self._host._presenter_active_changed(self.active)
        except Exception:
            pass

    def _on_window_destroyed(self, *args) -> None:  # noqa: ANN002
        # Window destroyed externally (WM close during shutdown, etc.).
        if self._window is not None:
            self._window = None
            self._stop_diagnostics_helpers()
            self._diag.finish("window_destroyed")
            self._restore_preferences()
            self._show_status(tr("presenter.status_off"))
            self._notify_active()

    def _merge_back_user_changes(self) -> None:
        """Propagate in-place user changes made while presenting to base.

        Tool-panel toggles and layout saves mutate the host's effective
        copy in place.  Fields the preset does not own belong to the user
        and are copied into the base so they survive the restore.  When
        the host object was replaced wholesale (Settings dialog apply),
        the intercept has already rebased — nothing to merge.
        """
        installed = self._installed
        snapshot = self._installed_snapshot
        base = self._base_prefs
        if installed is None or snapshot is None or base is None:
            return
        current = self._host._user_preferences
        if current is base or current is not installed:
            return  # no overlay, or host object replaced (dialog) — rebased
        from dataclasses import fields

        for field in fields(UserPreferences):
            name = field.name
            if name in _PRESET_OWNED_FIELDS:
                continue
            try:
                value = getattr(current, name)
                if value != getattr(snapshot, name):
                    setattr(base, name, value)
            except Exception:
                continue

    def _restore_preferences(self) -> None:
        base = self._base_prefs
        if base is None:
            return
        if not self.active and self._installed is None:
            return  # already restored — idempotent re-entry guard
        # Keep anything the user changed while presenting, then re-apply
        # and persist the base.  Teardown-safe: when the window is
        # destroyed during application shutdown, the host's widgets may
        # already be gone — re-apply is pointless then.
        try:
            self._merge_back_user_changes()
        except RuntimeError:
            return
        self._installed = None
        self._installed_snapshot = None
        try:
            self._apply_final(base)
        except RuntimeError:
            return
        self._save_prefs(base)

    # ── screens ─────────────────────────────────────────────────────

    def _host_screen(self):
        """The screen the speaker's main window is currently on."""
        try:
            window = self._host.window()
        except (RuntimeError, AttributeError):
            return None
        if window is None:
            return None
        try:
            handle = window.windowHandle()
        except RuntimeError:
            return None
        return handle.screen() if handle is not None else None

    def resolve_screen(self):
        """Screen for the audience display (see :func:`select_audience_screen`)."""
        app = QApplication.instance()
        if app is None:
            return None
        base = self.prefs_for_options()
        return select_audience_screen(
            app.screens(),
            remembered=getattr(base, "presenter_screen", ""),
            primary=app.primaryScreen(),
            host_screen=self._host_screen(),
        )

    def screen_action_checked_name(self) -> str:
        screen = self.resolve_screen()
        return screen.name() if screen is not None else ""

    def set_screen(self, screen) -> None:
        """Remember the audience display and restart the window if active."""
        base = self.prefs_for_options()
        base.presenter_screen = screen.name()
        self._save_prefs(base)
        if self.active:
            window = self._window
            self._window = None
            try:
                window.stop()
                window.deleteLater()
            except RuntimeError:
                pass
            self._restore_preferences()
            self.start()

    # ── option toggles used by the system-bar menu ──────────────────

    def set_visual_preset_enabled(self, enabled: bool) -> None:
        base = self.prefs_for_options()
        base.presenter_visual_preset = enabled
        self._save_prefs(base)
        if self.active:
            self._reapply_current()

    def set_pointer_enabled(self, enabled: bool) -> None:
        base = self.prefs_for_options()
        base.presenter_pointer = enabled
        self._save_prefs(base)
        if self._window is not None:
            self._window.set_pointer_enabled(enabled)

    def _save_prefs(self, preferences: UserPreferences) -> None:
        try:
            from echo_personal_tool.infrastructure.user_preferences import (
                save_user_preferences,
            )

            save_user_preferences(preferences)
        except Exception:
            pass

    def _show_status(self, message: str) -> None:
        try:
            self._host._show_status(message)
        except Exception:
            pass
