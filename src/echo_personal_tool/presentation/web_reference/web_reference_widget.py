"""Web-based structured reference widget — QWebEngineView wrapper."""

from __future__ import annotations

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
        self._web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self._web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)

        # QWebChannel
        self._channel = QWebChannel(self)
        self._channel.registerObject("backend", self._bridge)
        self._web_view.page().setWebChannel(self._channel)

        # Load HTML
        html_path = _WEB_DIR / "index.html"
        if html_path.exists():
            self._web_view.setHtml(
                html_path.read_text(encoding="utf-8"),
                QUrl.fromLocalFile(str(html_path) + "/"),
            )
        else:
            self._web_view.setHtml(f"<h2>Файл не найден</h2><p>{html_path}</p>")

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._web_view)

    def reload(self) -> None:
        """Reload data and refresh the web view."""
        self._store.load()
        self._bridge.configure(self._store)
        # Trigger JS reload
        self._web_view.page().runJavaScript("if(typeof init==='function')init()")

    def set_maximized_mode(self, maximized: bool) -> None:
        """No-op for API compatibility with StructuredReferenceWidget."""
