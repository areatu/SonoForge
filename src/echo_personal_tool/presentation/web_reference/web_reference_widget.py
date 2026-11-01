"""Web-based structured reference widget — QWebEngineView wrapper."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.web_reference.web_reference_bridge import (
    WebReferenceBridge,
)

log = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).parent / "web"


def _is_alive(obj: object) -> bool:
    """PR1 stability: JS/timer callbacks must not touch a dead C++ object."""
    try:
        import shiboken6

        return shiboken6.isValid(obj)
    except ImportError:
        return True


class WebReferenceWidget(QWidget):
    """Drop-in replacement for StructuredReferenceWidget using QWebEngineView."""

    web_failed = Signal()

    def __init__(
        self,
        data_store: ReferenceDataStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = data_store
        self._bridge_ready = False
        self._init_attempts = 0

        self._bridge = WebReferenceBridge(self)
        self._bridge.configure(data_store)

        self._web_view = QWebEngineView(self)
        settings = self._web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        dev_extras = getattr(QWebEngineSettings.WebAttribute, "DeveloperExtrasEnabled", None)
        if dev_extras is not None:
            settings.setAttribute(dev_extras, True)

        self._channel = QWebChannel(self)
        self._channel.registerObject("backend", self._bridge)
        self._web_view.page().setWebChannel(self._channel)

        tokens = get_theme_tokens()
        self._web_view.page().setBackgroundColor(QColor(tokens["surface.0"]))

        self._status_label = QLabel(tr("web_ref.loading"))
        self._status_label.setStyleSheet(
            f"color: {tokens['text.2']}; font-size: 14px; padding: 40px; "
            f"qproperty-alignment: AlignCenter; background: {tokens['surface.0']};"
        )

        html_path = _WEB_DIR / "index.html"
        if html_path.exists():
            file_url = QUrl.fromLocalFile(str(html_path))
            log.info("Loading web reference: %s", file_url.toString())
            self._web_view.loadFinished.connect(self._on_load_finished)
            self._web_view.setUrl(file_url)
        else:
            log.error("HTML not found: %s", html_path)
            self._status_label.setText(tr("web_ref.file_not_found").format(path=html_path))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._status_label)
        layout.addWidget(self._web_view)
        self._web_view.hide()

        self._fallback_timer = QTimer(self)
        self._fallback_timer.setSingleShot(True)
        self._fallback_timer.timeout.connect(self._on_fallback)
        self._fallback_timer.start(5000)

    def _on_load_finished(self, ok: bool) -> None:
        if not _is_alive(self):
            return
        if not ok:
            self._fallback_timer.stop()
            self._status_label.setText(tr("web_ref.load_error"))
            self.web_failed.emit()
            return
        log.info("Page loaded, checking bridge")
        self._apply_theme_to_web()
        self._init_attempts = 0
        self._try_init_bridge()

    def _apply_theme_to_web(self) -> None:
        """Inject current theme name, palette colors and locale strings."""
        if not _is_alive(self):
            return
        from echo_personal_tool.presentation.dark_theme import (
            _current_theme_mode,
            _is_system_dark,
        )

        # Resolve 'system' to a concrete theme the CSS knows about.
        theme = _current_theme_mode
        if theme == "system":
            theme = "dark" if _is_system_dark() else "light"

        tokens = get_theme_tokens()
        # Map the theme tokens onto the CSS custom properties so the web view
        # always matches the application theme (accent, borders, surfaces).
        css_vars = {
            "--bg-primary": tokens["surface.0"],
            "--bg-secondary": tokens["surface.1"],
            "--bg-tertiary": tokens["surface.2"],
            "--bg-surface": tokens["surface.1"],
            "--bg-hover": tokens["surface.hover"],
            "--bg-active": tokens["surface.3"],
            "--text-primary": tokens["text.1"],
            "--text-secondary": tokens["text.2"],
            "--text-muted": tokens["text.2"],
            "--accent": tokens["accent.tab"],
            "--accent-hover": tokens["accent.text"],
            "--border": tokens["line.1"],
            "--border-focus": tokens["accent.tab"],
            "--success": tokens["state.ok"],
            "--warning": tokens["state.warn"],
            "--danger": tokens["state.err"],
        }

        title = tr("constructor.export.html_title")
        title_escaped = title.replace("\\", "\\\\").replace("'", "\\'")
        import json as _json

        vars_js = _json.dumps(css_vars, ensure_ascii=False)
        js = (
            f"document.documentElement.setAttribute('data-theme', '{theme}');"
            f"document.title='{title_escaped}';"
            f"var h1=document.querySelector('h1');if(h1)h1.textContent='{title_escaped}';"
            f"var _v={vars_js};var _s=document.documentElement.style;"
            f"Object.keys(_v).forEach(function(k){{_s.setProperty(k,_v[k]);}});"
        )
        try:
            self._web_view.page().runJavaScript(js)
        except RuntimeError:
            return

    def hideEvent(self, event) -> None:  # type: ignore[override]  # mypy does not check this file (outside tool.mypy.files)
        # PR1 stability: stop pending bridge retries while hidden so tab
        # switches during load cannot fire into a half-dead page.
        try:
            self._fallback_timer.stop()
        except RuntimeError:
            pass
        super().hideEvent(event)

    def _try_init_bridge(self) -> None:
        if not _is_alive(self):
            return
        self._init_attempts += 1
        if self._init_attempts > 30:
            log.warning("Bridge init timed out")
            self._status_label.setText(tr("web_ref.init_failed"))
            self.web_failed.emit()
            return
        # Only treat the bridge as ready once it is actually connected to the
        # Python backend — otherwise the fallback timer must fire.
        self._web_view.page().runJavaScript(
            "typeof bridge !== 'undefined' && bridge._backend ? 'ok' : 'wait'",
            lambda r: self._on_bridge_check(r),
        )

    def _on_bridge_check(self, result: str) -> None:
        if not _is_alive(self):
            return
        if result == "ok":
            log.info("Bridge found, initializing (attempt %d)", self._init_attempts)
            self._bridge_ready = True
            self._fallback_timer.stop()
            self._status_label.hide()
            self._web_view.show()
            self._web_view.page().runJavaScript(
                "bridge.init().then(function(){ if(typeof init==='function') init(); });"
            )
        else:
            QTimer.singleShot(150, self._try_init_bridge)

    def _on_fallback(self) -> None:
        if not _is_alive(self):
            return
        if not self._bridge_ready:
            log.warning("Web fallback triggered")
            self._init_attempts = 999  # stop retry loop
            self._status_label.setText(tr("web_ref.fallback"))
            self.web_failed.emit()

    def reload(self) -> None:
        self._store.load()
        self._bridge.configure(self._store)
        tokens = get_theme_tokens()
        self._web_view.page().setBackgroundColor(QColor(tokens["surface.0"]))
        self._apply_theme_to_web()
        if self._bridge_ready:
            self._web_view.page().runJavaScript("if(typeof init==='function')init(true);")
        else:
            self._init_attempts = 0
            self._try_init_bridge()

    def reload_page(self) -> None:
        """Full page reload from disk (picks up HTML/CSS/JS edits)."""
        self._store.load()
        self._bridge.configure(self._store)
        self._bridge_ready = False
        self._init_attempts = 0
        self._status_label.setText(tr("web_ref.reloading"))
        self._status_label.show()
        self._web_view.hide()
        self._fallback_timer.stop()
        self._fallback_timer.start(5000)
        url = QUrl.fromLocalFile(str(_WEB_DIR / "index.html"))
        url.setQuery(f"v={int(time.time())}")
        log.info("Reloading web reference")
        self._web_view.setUrl(url)

    def set_maximized_mode(self, maximized: bool) -> None:
        pass

    def apply_theme(self) -> None:
        """Apply current theme to the web view without full reload."""
        if not _is_alive(self):
            return
        try:
            page = self._web_view.page()
        except RuntimeError:
            return
        tokens = get_theme_tokens()
        page.setBackgroundColor(QColor(tokens["surface.0"]))
        if self._bridge_ready:
            self._apply_theme_to_web()
            # Force web view to re-render with new theme
            self._web_view.update()

    def shutdown(self) -> None:
        """Deterministically release the web view and its page.

        QtWebEngine keeps its renderer and profile alive until the engine page
        is destroyed. When a short-lived dialog that owns a ``QWebEngineView``
        is only garbage-collected, the page can outlive the view
        ("Release of profile requested but WebEnginePage still not deleted")
        and crash a later Qt operation (observed as a SIGSEGV in an xdist
        worker). Stopping the load and scheduling the page and view for
        deletion makes teardown deterministic instead of relying on the GC.
        """
        if not _is_alive(self):
            return
        try:
            self._fallback_timer.stop()
        except RuntimeError:
            return
        view = getattr(self, "_web_view", None)
        if view is None or not _is_alive(view):
            return
        try:
            view.stop()
            page = view.page()
            if page is not None and _is_alive(page):
                page.deleteLater()
            view.deleteLater()
        except (RuntimeError, TypeError):
            pass
