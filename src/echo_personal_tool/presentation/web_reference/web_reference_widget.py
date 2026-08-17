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
        settings.setAttribute(QWebEngineSettings.WebAttribute.DeveloperExtrasEnabled, True)

        self._channel = QWebChannel(self)
        self._channel.registerObject("backend", self._bridge)
        self._web_view.page().setWebChannel(self._channel)

        self._status_label = QLabel("Загрузка справочника...")
        self._status_label.setStyleSheet(
            "color: #9fa8da; font-size: 14px; padding: 40px; qproperty-alignment: AlignCenter; background: #1a1a2e;"
        )

        html_path = _WEB_DIR / "index.html"
        if html_path.exists():
            file_url = QUrl.fromLocalFile(str(html_path))
            log.info("Loading web reference: %s", file_url.toString())
            self._web_view.loadFinished.connect(self._on_load_finished)
            self._web_view.setUrl(file_url)
        else:
            log.error("HTML not found: %s", html_path)
            self._status_label.setText(f"Файл не найден: {html_path}")

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
            self._status_label.setText("Ошибка загрузки")
            self._web_failed.emit()
            return
        log.info("Page loaded, checking bridge")
        self._init_attempts = 0
        self._try_init_bridge()

    def _try_init_bridge(self) -> None:
        self._init_attempts += 1
        if self._init_attempts > 30:
            log.warning("Bridge init timed out")
            self._status_label.setText("Веб-интерфейс не загрузился")
            self._web_failed.emit()
            return
        self._web_view.page().runJavaScript(
            "typeof bridge !== 'undefined' ? 'ok' : 'wait'",
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
            self._status_label.setText("Веб-недоступен — Qt-вид")
            self._web_failed.emit()

    def reload(self) -> None:
        self._store.load()
        self._bridge.configure(self._store)
        if self._bridge_ready:
            self._web_view.page().runJavaScript("if(typeof init==='function')init();")
        else:
            self._init_attempts = 0
            self._try_init_bridge()

    def set_maximized_mode(self, maximized: bool) -> None:
        pass
