"""Web-based structured reference widget — QWebEngineView wrapper."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore
from echo_personal_tool.presentation.web_reference.web_reference_bridge import (
    WebReferenceBridge,
)

log = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).parent / "web"


class WebReferenceWidget(QWidget):
    """Drop-in replacement for StructuredReferenceWidget using QWebEngineView."""

    def __init__(
        self,
        data_store: ReferenceDataStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = data_store

        # Bridge
        self._bridge = WebReferenceBridge(self)
        self._bridge.configure(data_store)

        # WebEngineView
        self._web_view = QWebEngineView(self)
        settings = self._web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        # Enable developer extras for debugging
        settings.setAttribute(QWebEngineSettings.WebAttribute.DeveloperExtrasEnabled, True)

        # QWebChannel
        self._channel = QWebChannel(self)
        self._channel.registerObject("backend", self._bridge)
        self._web_view.page().setWebChannel(self._channel)

        # Load HTML via file URL so qrc:/// resources resolve
        html_path = _WEB_DIR / "index.html"
        if html_path.exists():
            file_url = QUrl.fromLocalFile(str(html_path))
            log.info("Loading web reference: %s", file_url.toString())
            self._web_view.setUrl(file_url)
            # After page loads, ensure JS bridge is initialized
            self._web_view.loadFinished.connect(self._on_load_finished)
        else:
            log.error("HTML file not found: %s", html_path)
            self._web_view.setHtml(f"<h2>File not found</h2><p>{html_path}</p>")

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._web_view)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            log.error("Web reference page failed to load")
            return
        log.info("Web reference page loaded, initializing bridge")
        # Ensure the JS bridge connects to Python backend
        self._web_view.page().runJavaScript(
            "if(typeof bridge!=='undefined'&&typeof bridge.init==='function')bridge.init();"
        )

    def reload(self) -> None:
        """Reload data and refresh the web view."""
        self._store.load()
        self._bridge.configure(self._store)
        self._web_view.page().runJavaScript("if(typeof init==='function')init()")

    def set_maximized_mode(self, maximized: bool) -> None:
        """No-op for API compatibility with StructuredReferenceWidget."""
