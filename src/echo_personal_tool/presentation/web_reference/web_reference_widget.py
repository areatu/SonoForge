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

from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.dark_theme import get_theme_palette
from echo_personal_tool.presentation.web_reference.web_reference_bridge import (
    WebReferenceBridge,
)

log = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).parent / "web"


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

        p = get_theme_palette()
        self._web_view.page().setBackgroundColor(QColor(p.get("bg_dark", "#102135")))

        self._status_label = QLabel(tr("web_ref.loading"))
        self._status_label.setStyleSheet(
            f"color: {p['text_dim']}; font-size: 14px; padding: 40px; "
            f"qproperty-alignment: AlignCenter; background: {p['bg_dark']};"
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
        from echo_personal_tool.presentation.dark_theme import (
            _current_theme_mode,
            _is_system_dark,
        )

        # Resolve 'system' to a concrete theme the CSS knows about.
        theme = _current_theme_mode
        if theme == "system":
            theme = "dark" if _is_system_dark() else "light"

        p = get_theme_palette()
        # Map the Qt palette onto the CSS custom properties so the web view
        # always matches the application theme (accent, borders, surfaces).
        css_vars = {
            "--bg-primary": p.get("bg_dark"),
            "--bg-secondary": p.get("bg_panel"),
            "--bg-tertiary": p.get("bg_control"),
            "--bg-surface": p.get("bg_panel"),
            "--bg-hover": p.get("bg_button_hover"),
            "--bg-active": p.get("bg_button"),
            "--text-primary": p.get("text"),
            "--text-secondary": p.get("text_dim"),
            "--text-muted": p.get("text_dim"),
            "--accent": p.get("accent_tab"),
            "--accent-hover": p.get("accent_bright"),
            "--border": p.get("border"),
            "--border-focus": p.get("accent_tab"),
            "--success": p.get("success"),
            "--warning": p.get("warning"),
            "--danger": p.get("error"),
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
        self._web_view.page().runJavaScript(js)

    def _try_init_bridge(self) -> None:
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
        if not self._bridge_ready:
            log.warning("Web fallback triggered")
            self._init_attempts = 999  # stop retry loop
            self._status_label.setText(tr("web_ref.fallback"))
            self.web_failed.emit()

    def reload(self) -> None:
        self._store.load()
        self._bridge.configure(self._store)
        p = get_theme_palette()
        self._web_view.page().setBackgroundColor(QColor(p.get("bg_dark", "#102135")))
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
        log.info("Reloading web reference: %s", url.toString())
        self._web_view.setUrl(url)

    def set_maximized_mode(self, maximized: bool) -> None:
        pass

    def apply_theme(self) -> None:
        """Apply current theme to the web view without full reload."""
        p = get_theme_palette()
        self._web_view.page().setBackgroundColor(QColor(p.get("bg_dark", "#102135")))
        if self._bridge_ready:
            self._apply_theme_to_web()
            # Force web view to re-render with new theme
            self._web_view.update()
