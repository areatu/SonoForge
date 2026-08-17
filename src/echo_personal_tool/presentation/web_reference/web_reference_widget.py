"""Web-based structured reference widget — QWebEngineView wrapper."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore
from echo_personal_tool.presentation.web_reference.web_reference_bridge import (
    WebReferenceBridge,
)

log = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).parent / "web"


class WebReferenceWidget(QWidget):
    """Drop-in replacement for StructuredReferenceWidget using QWebEngineView."""

    web_failed = Signal()  # emitted if web doesn't initialize in time

    def __init__(
        self,
        data_store: ReferenceDataStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = data_store
        self._bridge_ready = False

        # Bridge
        self._bridge = WebReferenceBridge(self)
        self._bridge.configure(data_store)

        # WebEngineView
        self._web_view = QWebEngineView(self)
        settings = self._web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.DeveloperExtrasEnabled, True)

        # QWebChannel
        self._channel = QWebChannel(self)
        self._channel.registerObject("backend", self._bridge)
        self._web_view.page().setWebChannel(self._channel)

        # Status label
        self._status_label = QLabel("Загрузка справочника...")
        self._status_label.setStyleSheet(
            "color: #9fa8da; font-size: 14px; padding: 40px; qproperty-alignment: AlignCenter;background: #1a1a2e;"
        )

        # Load HTML via file URL so qrc:/// resources resolve
        html_path = _WEB_DIR / "index.html"
        if html_path.exists():
            file_url = QUrl.fromLocalFile(str(html_path))
            log.info("Loading web reference: %s", file_url.toString())
            self._web_view.setUrl(file_url)
            self._web_view.loadFinished.connect(self._on_load_finished)
        else:
            log.error("HTML file not found: %s", html_path)
            self._status_label.setText(f"Файл не найден: {html_path}")

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._status_label)
        layout.addWidget(self._web_view)
        self._web_view.hide()  # show status until loaded

        # Fallback timer: if bridge doesn't connect in 5s, emit web_failed
        self._fallback_timer = QTimer(self)
        self._fallback_timer.setSingleShot(True)
        self._fallback_timer.timeout.connect(self._on_fallback)
        self._fallback_timer.start(5000)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            log.error("Web reference page failed to load")
            self._status_label.setText("Ошибка загрузки страницы")
            self._web_failed.emit()
            return
        log.info("Web reference page loaded, polling bridge")
        self._poll_bridge_ready(attempt=0)

    def _poll_bridge_ready(self, attempt: int) -> None:
        """Poll until bridge is ready, with max 50 attempts (5 seconds)."""
        if attempt > 50:
            log.warning("Bridge did not initialize after 5s")
            self._status_label.setText("Веб-интерфейс не инициализирован")
            self._web_failed.emit()
            return
        js = """
        (function() {
            if (typeof qt !== 'undefined' && typeof bridge !== 'undefined' && typeof init === 'function') {
                return 'ready';
            }
            return 'waiting';
        })()
        """
        self._web_view.page().runJavaScript(js, lambda result: self._on_poll_result(result, attempt))

    def _on_poll_result(self, result: str, attempt: int) -> None:
        if result == "ready":
            log.info("Bridge ready on attempt %d, initializing", attempt)
            self._bridge_ready = True
            self._fallback_timer.stop()
            self._status_label.hide()
            self._web_view.show()
            # Initialize bridge and app
            self._web_view.page().runJavaScript("bridge.init().then(function() { init(); });")
        else:
            QTimer.singleShot(100, lambda: self._poll_bridge_ready(attempt + 1))

    def _on_fallback(self) -> None:
        if not self._bridge_ready:
            log.warning("Web reference failed to initialize, switching to Qt fallback")
            self._status_label.setText("Веб-интерфейс недоступен — используется Qt-вид")
            self._web_failed.emit()

    def reload(self) -> None:
        """Reload data and refresh the web view."""
        self._store.load()
        self._bridge.configure(self._store)
        if self._bridge_ready:
            self._web_view.page().runJavaScript("if(typeof init==='function')init();")
        else:
            self._poll_bridge_ready(attempt=0)

    def set_maximized_mode(self, maximized: bool) -> None:
        """No-op for API compatibility with StructuredReferenceWidget."""
