"""Scrollable ASE reference viewer with multi-document tabs and PDF support."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSpacerItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.services.ase_reference_parser import (
    default_ase_reference_path,
    default_references_dir,
    load_ase_reference_text,
    markdown_to_html,
    scan_references_dir,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.echopac_theme import get_theme_palette
from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI

logger = logging.getLogger(__name__)

_SETTINGS_ORG = "echo-personal-tool"
_SETTINGS_APP = "ase-reference"
_DEFAULT_FONT_FAMILY = FONT_FAMILY_UI
_DEFAULT_FONT_SIZE = 12
_MIN_FONT_SIZE = 8
_MAX_FONT_SIZE = 28

_PDF_DPI_BASE = 150


def _load_icon(name: str) -> QPixmap:
    """Load an SVG icon from the resources/icons directory, recolored to theme text."""
    from PySide6.QtGui import QIcon
    import sys
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        icon_dir = Path(meipass) / "echo_personal_tool" / "resources" / "icons"
    else:
        icon_dir = Path(__file__).resolve().parents[1] / "resources" / "icons"
    svg_path = icon_dir / f"{name}.svg"
    if svg_path.is_file():
        svg_text = svg_path.read_text(encoding="utf-8")
        color = get_theme_palette().get("text", "#f1f5f9")
        svg_text = svg_text.replace("currentColor", color)
        pixmap = QPixmap()
        pixmap.loadFromData(svg_text.encode("utf-8"))
        return pixmap
    return QPixmap()


def show_ase_reference_dialog(parent: QWidget | None = None) -> None:
    try:
        dialog = AseReferenceDialog(parent)
    except Exception as exc:  # noqa: BLE001 — show load errors in UI
        QMessageBox.critical(
            parent,
            tr("ase_refs.load_error.title"),
            tr("ase_refs.load_error.body", exc=str(exc)),
        )
        return
    dialog.exec()


# ── Document tab widget ───────────────────────────────────────────


class _DocTab(QWidget):
    """Clickable tab for a loaded document with a close button."""

    def __init__(self, label: str, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.doc_path = path
        self.setFixedHeight(26)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 2, 0)
        layout.setSpacing(4)

        self._btn_label = QPushButton(label)
        self._btn_label.setCheckable(True)
        self._btn_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_label.setStyleSheet("QPushButton { border: none; padding: 0; background: transparent; }")
        layout.addWidget(self._btn_label)

        self._btn_close = QPushButton()
        self._btn_close.setFixedSize(16, 16)
        self._btn_close.setIconSize(self._btn_close.sizeHint())
        self._btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_close.clicked.connect(self._on_close_clicked)
        layout.addWidget(self._btn_close)

        self._active = False
        self._apply_style(False)
        self._apply_close_style(False)

    clicked = Signal()

    def _on_close_clicked(self) -> None:
        # Emit a signal so the dialog can handle tab removal
        self.close_requested.emit()

    close_requested = Signal()

    def _apply_style(self, active: bool) -> None:
        p = get_theme_palette()
        if active:
            self.setStyleSheet(
                f"_DocTab {{ background: {p['accent_tab']}; border-radius: 3px; }}"
            )
        else:
            self.setStyleSheet(
                f"_DocTab {{ background: {p['bg_control']}; border-radius: 3px; }}"
            )
        self._apply_label_style(active)

    def _apply_label_style(self, active: bool) -> None:
        p = get_theme_palette()
        if active:
            self._btn_label.setStyleSheet(
                f"QPushButton {{ border: none; padding: 0; background: transparent; "
                f"color: {p['text']}; font-weight: bold; }}"
            )
        else:
            self._btn_label.setStyleSheet(
                f"QPushButton {{ border: none; padding: 0; background: transparent; "
                f"color: {p['text_dim']}; }}"
            )

    def _apply_close_style(self, active: bool) -> None:
        from PySide6.QtGui import QIcon
        p = get_theme_palette()
        close_pixmap = _load_icon("close")
        if not close_pixmap.isNull():
            self._btn_close.setIcon(QIcon(close_pixmap))
        self._btn_close.setStyleSheet(
            f"QPushButton {{ border: none; padding: 0; background: transparent; }}"
            f"QPushButton:hover {{ background: {p['bg_button_hover']}; border-radius: 3px; }}"
        )

    def set_active(self, active: bool) -> None:
        self._active = active
        self._btn_label.setChecked(active)
        self._apply_style(active)


# ── PDF page renderer ─────────────────────────────────────────────


def _render_pdf_page(doc: Any, page_index: int, dpi: float = 150) -> QPixmap | None:
    """Render a single PDF page to QPixmap via pymupdf."""
    try:
        import fitz  # pymupdf
    except ImportError:
        return None
    if page_index < 0 or page_index >= len(doc):
        return None
    page = doc.load_page(page_index)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image)


# ── PDF continuous viewer widget ──────────────────────────────────


class _PdfContinuousWidget(QWidget):
    """Scrollable widget that renders multiple PDF pages vertically."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._page_labels: list[QLabel] = []

    def render_pages(self, doc: Any, start: int, count: int, dpi: float) -> None:
        for label in self._page_labels:
            self._layout.removeWidget(label)
            label.deleteLater()
        self._page_labels.clear()

        for i in range(start, min(start + count, len(doc))):
            pixmap = _render_pdf_page(doc, i, dpi)
            if pixmap is None:
                continue
            lbl = QLabel()
            lbl.setPixmap(pixmap)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._layout.addWidget(lbl)
            self._page_labels.append(lbl)
        self._layout.addStretch(1)


# ── Main dialog ───────────────────────────────────────────────────


class AseReferenceDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("ase_refs.title"))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(1020, 750)

        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._font_family = str(
            self._settings.value("font_family", _DEFAULT_FONT_FAMILY)
        )
        self._font_size = int(self._settings.value("font_size", _DEFAULT_FONT_SIZE))

        # Dragging state
        self._drag_pos: QPoint | None = None
        self._is_maximized = False
        self._normal_geometry: Any = None

        # Documents: list of (name, path, kind) where kind is "md" or "pdf"
        self._documents: list[tuple[str, Path, str]] = []
        self._active_doc_index: int = -1
        self._pdf_docs: dict[Path, Any] = {}  # fitz.Document cache

        # PDF state
        self._pdf_current_page: int = 0
        self._pdf_total_pages: int = 0
        self._pdf_zoom: float = 1.0
        self._pdf_view_mode: str = "single"  # "single" | "double" | "continuous"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Title bar (draggable) ──
        title_bar = self._build_title_bar()
        root.addWidget(title_bar)

        # ── Menu bar ──
        root.addWidget(self._build_menu())

        # ── Tabs bar ──
        self._tabs_widget = QWidget()
        self._tabs_layout = QHBoxLayout(self._tabs_widget)
        self._tabs_layout.setContentsMargins(4, 2, 4, 2)
        self._tabs_layout.setSpacing(2)
        self._tabs_layout.addStretch(1)
        self._btn_add_tab = QPushButton("+")
        self._btn_add_tab.setFixedSize(32, 24)
        self._btn_add_tab.setToolTip(tr("ase_refs.add_document"))
        self._btn_add_tab.setCursor(Qt.CursorShape.PointingHandCursor)
        p = get_theme_palette()
        self._btn_add_tab.setStyleSheet(
            f"QPushButton {{ background: {p['accent_tab']}; color: {p['text']}; "
            f"border: none; padding: 0; border-radius: 3px; font-weight: bold; font-size: 16px; }}"
            f"QPushButton:hover {{ background: {p['bg_button_hover']}; color: {p['text']}; }}"
            f"QPushButton:pressed {{ background: {p['bg_button_pressed']}; color: {p['text']}; }}"
        )
        self._btn_add_tab.clicked.connect(self._add_document)
        self._tabs_layout.addWidget(self._btn_add_tab)
        root.addWidget(self._tabs_widget)

        # ── Content area ──
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        p = get_theme_palette()
        self._browser.document().setDefaultStyleSheet(
            f"body {{ color: {p['text']}; }}"
            f"h1, h2, h3 {{ color: {p['text']}; }}"
            f"table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}"
            f"th, td {{ border: 1px solid {p['border']}; vertical-align: top; }}"
            f"th {{ background: {p['bg_control']}; }}"
            f"blockquote {{ color: {p['text_dim']}; margin: 8px 0 8px 12px; }}"
            f"hr {{ border: none; border-top: 1px solid {p['border']}; margin: 16px 0; }}"
        )

        # PDF single/double page view
        self._pdf_scroll = QScrollArea()
        self._pdf_scroll.setWidgetResizable(True)
        self._pdf_label = QLabel()
        self._pdf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pdf_scroll.setWidget(self._pdf_label)

        # PDF continuous view
        self._pdf_continuous_widget = _PdfContinuousWidget()
        self._pdf_continuous_scroll = QScrollArea()
        self._pdf_continuous_scroll.setWidgetResizable(True)
        self._pdf_continuous_scroll.setWidget(self._pdf_continuous_widget)

        # PDF toolbar: zoom +/-, view mode, page nav
        self._pdf_toolbar = QWidget()
        pdf_toolbar_layout = QHBoxLayout(self._pdf_toolbar)
        pdf_toolbar_layout.setContentsMargins(4, 2, 4, 2)
        pdf_toolbar_layout.setSpacing(4)

        self._btn_pdf_zoom_out = QPushButton("\u2212")  # −
        self._btn_pdf_zoom_out.setFixedSize(28, 24)
        self._btn_pdf_zoom_out.setToolTip(tr("ase_refs.pdf_zoom_out"))
        self._btn_pdf_zoom_out.clicked.connect(self._pdf_zoom_out)

        self._btn_pdf_zoom_in = QPushButton("+")
        self._btn_pdf_zoom_in.setFixedSize(28, 24)
        self._btn_pdf_zoom_in.setToolTip(tr("ase_refs.pdf_zoom_in"))
        self._btn_pdf_zoom_in.clicked.connect(self._pdf_zoom_in)

        self._pdf_zoom_label = QLabel("100%")
        self._pdf_zoom_label.setFixedWidth(48)
        self._pdf_zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._combo_pdf_view = QComboBox()
        self._combo_pdf_view.addItems([
            tr("ase_refs.pdf_view_single"),
            tr("ase_refs.pdf_view_double"),
            tr("ase_refs.pdf_view_continuous"),
        ])
        self._combo_pdf_view.currentIndexChanged.connect(self._pdf_view_mode_changed)

        self._btn_pdf_prev = QPushButton("\u25C0")
        self._btn_pdf_prev.setFixedSize(28, 24)
        self._btn_pdf_prev.clicked.connect(self._pdf_prev_page)
        self._btn_pdf_page = QLabel("1 / 1")
        self._btn_pdf_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_pdf_page.setFixedWidth(80)
        self._btn_pdf_next = QPushButton("\u25B6")
        self._btn_pdf_next.setFixedSize(28, 24)
        self._btn_pdf_next.clicked.connect(self._pdf_next_page)

        pdf_toolbar_layout.addStretch(1)
        pdf_toolbar_layout.addWidget(self._btn_pdf_zoom_out)
        pdf_toolbar_layout.addWidget(self._pdf_zoom_label)
        pdf_toolbar_layout.addWidget(self._btn_pdf_zoom_in)
        pdf_toolbar_layout.addWidget(self._combo_pdf_view)
        pdf_toolbar_layout.addSpacing(16)
        pdf_toolbar_layout.addWidget(self._btn_pdf_prev)
        pdf_toolbar_layout.addWidget(self._btn_pdf_page)
        pdf_toolbar_layout.addWidget(self._btn_pdf_next)
        pdf_toolbar_layout.addStretch(1)

        root.addWidget(self._browser, stretch=1)
        root.addWidget(self._pdf_scroll, stretch=1)
        root.addWidget(self._pdf_continuous_scroll, stretch=1)
        root.addWidget(self._pdf_toolbar)
        self._pdf_scroll.hide()
        self._pdf_continuous_scroll.hide()
        self._pdf_toolbar.hide()

        self._apply_font()
        self._load_default_documents()

    # ── Title bar ─────────────────────────────────────────────────

    def _build_title_bar(self) -> QWidget:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QSizePolicy
        p = get_theme_palette()
        bar = QWidget()
        bar.setFixedHeight(32)
        bar.setStyleSheet(f"background: {p['bg_panel']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel(tr("ase_refs.title"))
        title.setStyleSheet(f"color: {p['text']}; font-weight: bold; border: none;")
        layout.addWidget(title)
        layout.addStretch(1)

        # Window controls — use object names so theme CSS from echopac_theme applies
        window_controls = QWidget()
        window_controls.setObjectName("windowControls")
        window_controls.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        wc_layout = QHBoxLayout(window_controls)
        wc_layout.setContentsMargins(0, 0, 0, 0)
        wc_layout.setSpacing(0)

        self._btn_minimize = QPushButton()
        self._btn_minimize.setObjectName("minimizeButton")
        self._btn_minimize.setIcon(QIcon(_load_icon("minimize")))
        self._btn_minimize.setToolTip(tr("ase_refs.minimize"))
        self._btn_minimize.clicked.connect(self.showMinimized)
        self._btn_minimize.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; padding: 0; }}"
            f"QPushButton:hover {{ background: {p['bg_button']}; }}"
        )

        self._btn_maximize = QPushButton()
        self._btn_maximize.setObjectName("maximizeButton")
        self._btn_maximize.setIcon(QIcon(_load_icon("maximize")))
        self._btn_maximize.setToolTip(tr("ase_refs.maximize"))
        self._btn_maximize.clicked.connect(self._toggle_maximize)
        self._btn_maximize.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; padding: 0; }}"
            f"QPushButton:hover {{ background: {p['bg_button']}; }}"
        )

        btn_close = QPushButton()
        btn_close.setObjectName("closeButton")
        btn_close.setIcon(QIcon(_load_icon("close")))
        btn_close.setToolTip(tr("ase_refs.close"))
        btn_close.clicked.connect(self.reject)
        btn_close.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; padding: 0; }}"
            f"QPushButton:hover {{ background: #e81123; color: white; }}"
        )

        wc_layout.addWidget(self._btn_minimize)
        wc_layout.addWidget(self._btn_maximize)
        wc_layout.addWidget(btn_close)
        layout.addWidget(window_controls)

        return bar

    def _toggle_maximize(self) -> None:
        if self._is_maximized:
            self.showNormal()
            if self._normal_geometry is not None:
                self.setGeometry(self._normal_geometry)
            self._is_maximized = False
            self._btn_maximize.setIcon(QIcon(_load_icon("maximize")))
            self._btn_maximize.setToolTip(tr("ase_refs.maximize"))
        else:
            self._normal_geometry = self.geometry()
            screen = self.screen() or QApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                self.setGeometry(geo)
            self._is_maximized = True
            self._btn_maximize.setIcon(QIcon(_load_icon("restore")))
            self._btn_maximize.setToolTip(tr("ase_refs.restore"))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 32:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if self._active_doc_index >= 0:
            _, _, kind = self._documents[self._active_doc_index]
            if kind == "pdf":
                key = event.key()
                if key == Qt.Key.Key_Right or key == Qt.Key.Key_Down:
                    self._pdf_next_page()
                    event.accept()
                    return
                if key == Qt.Key.Key_Left or key == Qt.Key.Key_Up:
                    self._pdf_prev_page()
                    event.accept()
                    return
                if key == Qt.Key.Key_Space:
                    self._pdf_next_page()
                    event.accept()
                    return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if self._active_doc_index >= 0:
            _, _, kind = self._documents[self._active_doc_index]
            if kind == "pdf" and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self._pdf_zoom_in()
                elif delta < 0:
                    self._pdf_zoom_out()
                event.accept()
                return
        super().wheelEvent(event)

    # ── Menu ──────────────────────────────────────────────────────

    def _build_menu(self) -> QMenuBar:
        from PySide6.QtWidgets import QMenu

        menu_bar = QMenuBar(self)

        file_menu = QMenu(tr("ase_refs.file_menu"), menu_bar)
        file_menu.addAction(tr("ase_refs.add_document"), self._add_document)
        file_menu.addSeparator()
        file_menu.addAction(tr("ase_refs.reload"), self._reload_active_document)
        menu_bar.addMenu(file_menu)

        settings_menu = QMenu(tr("ase_refs.settings_menu"), menu_bar)
        settings_menu.addAction(tr("ase_refs.font_action"), self._show_font_settings)
        menu_bar.addMenu(settings_menu)

        return menu_bar

    # ── Documents ─────────────────────────────────────────────────

    def _load_default_documents(self) -> None:
        try:
            docs = scan_references_dir()
        except FileNotFoundError:
            try:
                md_path = default_ase_reference_path()
            except FileNotFoundError:
                return
            docs = [(md_path.name, md_path, "md")]
        for name, path, kind in docs:
            self._add_doc_tab(name, path, kind)
        if self._documents:
            self._switch_to_doc(0)

    def _add_doc_tab(self, name: str, path: Path, kind: str) -> int:
        self._documents.append((name, path, kind))
        index = len(self._documents) - 1

        tab = _DocTab(name, path)
        tab._btn_label.clicked.connect(lambda _checked, i=index: self._switch_to_doc(i))
        tab.close_requested.connect(lambda i=index: self._close_doc_tab(i))

        # Insert before the stretch + add button
        count = self._tabs_layout.count()
        self._tabs_layout.insertWidget(count - 2, tab)
        return index

    def _switch_to_doc(self, index: int) -> None:
        if index < 0 or index >= len(self._documents):
            return
        self._active_doc_index = index

        # Update tab states
        for i in range(self._tabs_layout.count()):
            widget = self._tabs_layout.itemAt(i).widget()
            if isinstance(widget, _DocTab):
                widget.set_active(self._tab_index_of(widget) == index)

        name, path, kind = self._documents[index]

        if kind == "md":
            self._show_markdown(path)
        elif kind == "pdf":
            self._show_pdf(path)

    def _tab_index_of(self, tab: _DocTab) -> int:
        """Return the document index corresponding to a tab widget."""
        for i in range(self._tabs_layout.count()):
            widget = self._tabs_layout.itemAt(i).widget()
            if widget is tab:
                return self._document_index_for_tab_position(i)
        return -1

    def _document_index_for_tab_position(self, tab_layout_pos: int) -> int:
        """Map a layout position to a document index by counting _DocTab widgets before it."""
        count = 0
        for i in range(tab_layout_pos):
            widget = self._tabs_layout.itemAt(i).widget()
            if isinstance(widget, _DocTab):
                count += 1
        return count

    def _close_doc_tab(self, index: int) -> None:
        if index < 0 or index >= len(self._documents):
            return
        # Don't close the last tab
        if len(self._documents) <= 1:
            return

        name, path, kind = self._documents[index]
        if kind == "pdf" and path in self._pdf_docs:
            try:
                self._pdf_docs[path].close()
            except Exception:  # noqa: BLE001
                pass
            del self._pdf_docs[path]

        # Find and remove the tab widget
        tab_widget = self._tab_widget_at_doc_index(index)
        if tab_widget is not None:
            self._tabs_layout.removeWidget(tab_widget)
            tab_widget.deleteLater()

        del self._documents[index]

        # Re-index remaining tab click signals
        self._reconnect_tab_signals()

        # Switch to adjacent tab
        if self._active_doc_index >= len(self._documents):
            self._active_doc_index = len(self._documents) - 1
        if self._active_doc_index >= 0:
            self._switch_to_doc(self._active_doc_index)
        else:
            self._active_doc_index = -1
            self._browser.hide()
            self._pdf_scroll.hide()
            self._pdf_continuous_scroll.hide()
            self._pdf_toolbar.hide()

    def _tab_widget_at_doc_index(self, doc_index: int) -> _DocTab | None:
        """Find the _DocTab widget at the given document index."""
        count = 0
        for i in range(self._tabs_layout.count()):
            widget = self._tabs_layout.itemAt(i).widget()
            if isinstance(widget, _DocTab):
                if count == doc_index:
                    return widget
                count += 1
        return None

    def _reconnect_tab_signals(self) -> None:
        """Reconnect click/close signals so doc indices stay correct."""
        doc_idx = 0
        for i in range(self._tabs_layout.count()):
            widget = self._tabs_layout.itemAt(i).widget()
            if isinstance(widget, _DocTab):
                # Disconnect old signals
                try:
                    widget._btn_label.clicked.disconnect()
                except RuntimeError:
                    pass
                try:
                    widget.close_requested.disconnect()
                except RuntimeError:
                    pass
                idx = doc_idx  # capture
                widget._btn_label.clicked.connect(
                    lambda _checked, ii=idx: self._switch_to_doc(ii)
                )
                widget.close_requested.connect(
                    lambda ii=idx: self._close_doc_tab(ii)
                )
                doc_idx += 1

    def _show_markdown(self, path: Path) -> None:
        self._browser.show()
        self._pdf_scroll.hide()
        self._pdf_continuous_scroll.hide()
        self._pdf_toolbar.hide()
        try:
            markdown = load_ase_reference_text(path)
        except OSError as exc:
            QMessageBox.warning(
                self,
                tr("ase_refs.read_error.title"),
                tr("ase_refs.read_error.body", path=str(path), exc=str(exc)),
            )
            return
        self._browser.setHtml(markdown_to_html(markdown))
        self._apply_font()

    def _show_pdf(self, path: Path) -> None:
        self._browser.hide()
        self._pdf_toolbar.show()

        try:
            import fitz
        except ImportError:
            self._pdf_label.setText(tr("ase_refs.pdf_missing"))
            self._pdf_scroll.show()
            self._pdf_continuous_scroll.hide()
            return

        if path not in self._pdf_docs:
            self._pdf_docs[path] = fitz.open(str(path))
        doc = self._pdf_docs[path]
        self._pdf_total_pages = len(doc)
        self._pdf_current_page = 0
        self._pdf_zoom = 1.0
        self._pdf_zoom_label.setText("100%")
        self._update_pdf_view_visibility()
        self._render_pdf()

    def _update_pdf_view_visibility(self) -> None:
        mode = self._combo_pdf_view.currentIndex()
        if mode == 2:  # continuous
            self._pdf_scroll.hide()
            self._pdf_continuous_scroll.show()
        else:
            self._pdf_scroll.show()
            self._pdf_continuous_scroll.hide()

    def _render_pdf(self) -> None:
        if self._active_doc_index < 0:
            return
        _, path, kind = self._documents[self._active_doc_index]
        if kind != "pdf" or path not in self._pdf_docs:
            return
        doc = self._pdf_docs[path]
        dpi = _PDF_DPI_BASE * self._pdf_zoom
        mode = self._combo_pdf_view.currentIndex()

        if mode == 2:  # continuous
            self._pdf_continuous_widget.render_pages(doc, 0, len(doc), dpi)
        elif mode == 1:  # double page
            end = min(self._pdf_current_page + 2, self._pdf_total_pages)
            combined = QPixmap()
            pixmaps = []
            for i in range(self._pdf_current_page, end):
                pm = _render_pdf_page(doc, i, dpi)
                if pm is not None:
                    pixmaps.append(pm)
            if pixmaps:
                total_w = sum(p.width() for p in pixmaps) + 4 * (len(pixmaps) - 1)
                max_h = max(p.height() for p in pixmaps)
                combined = QPixmap(total_w, max_h)
                combined.fill(0)
                from PySide6.QtGui import QPainter
                x = 0
                for p in pixmaps:
                    painter = QPainter(combined)
                    painter.drawPixmap(x, 0, p)
                    painter.end()
                    x += p.width() + 4
            self._pdf_label.setPixmap(combined)
        else:  # single page
            pixmap = _render_pdf_page(doc, self._pdf_current_page, dpi)
            if pixmap is not None:
                self._pdf_label.setPixmap(pixmap)

        self._pdf_zoom_label.setText(f"{int(self._pdf_zoom * 100)}%")
        self._btn_pdf_page.setText(
            f"{self._pdf_current_page + 1} / {self._pdf_total_pages}"
        )
        self._btn_pdf_prev.setEnabled(self._pdf_current_page > 0)
        self._btn_pdf_next.setEnabled(self._pdf_current_page < self._pdf_total_pages - 1)

    def _pdf_prev_page(self) -> None:
        if self._pdf_current_page > 0:
            self._pdf_current_page -= 1
            self._render_pdf()

    def _pdf_next_page(self) -> None:
        if self._pdf_current_page < self._pdf_total_pages - 1:
            self._pdf_current_page += 1
            self._render_pdf()

    def _pdf_zoom_in(self) -> None:
        if self._pdf_zoom < 4.0:
            self._pdf_zoom = min(4.0, self._pdf_zoom + 0.25)
            self._render_pdf()

    def _pdf_zoom_out(self) -> None:
        if self._pdf_zoom > 0.25:
            self._pdf_zoom = max(0.25, self._pdf_zoom - 0.25)
            self._render_pdf()

    def _pdf_view_mode_changed(self, index: int) -> None:
        self._update_pdf_view_visibility()
        self._render_pdf()

    def _add_document(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            tr("ase_refs.open_document"),
            "",
            tr("ase_refs.supported_files"),
        )
        if not path_str:
            return
        path = Path(path_str)
        kind = "pdf" if path.suffix.lower() == ".pdf" else "md"
        self._add_doc_tab(path.stem, path, kind)
        self._switch_to_doc(len(self._documents) - 1)

    def _reload_active_document(self) -> None:
        if self._active_doc_index < 0:
            return
        name, path, kind = self._documents[self._active_doc_index]
        if kind == "md":
            self._show_markdown(path)
        elif kind == "pdf" and path in self._pdf_docs:
            self._pdf_docs[path].close()
            del self._pdf_docs[path]
            self._show_pdf(path)

    # ── Font ──────────────────────────────────────────────────────

    def _show_font_settings(self) -> None:
        dialog = ReferenceFontSettingsDialog(
            self._font_family,
            self._font_size,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._font_family = dialog.selected_family()
        self._font_size = dialog.selected_size()
        self._settings.setValue("font_family", self._font_family)
        self._settings.setValue("font_size", self._font_size)
        self._apply_font()

    def _apply_font(self) -> None:
        font = QFont(self._font_family, self._font_size)
        self._browser.setFont(font)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        for doc in self._pdf_docs.values():
            try:
                doc.close()
            except Exception:  # noqa: BLE001
                pass
        self._pdf_docs.clear()
        super().closeEvent(event)


class ReferenceFontSettingsDialog(QDialog):
    def __init__(
        self,
        family: str,
        size: int,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("ase_refs.font_settings"))

        self._family = QFontComboBox()
        self._family.setCurrentFont(QFont(family))

        self._size = QSpinBox()
        self._size.setRange(_MIN_FONT_SIZE, _MAX_FONT_SIZE)
        self._size.setSuffix(" pt")
        self._size.setValue(size)

        form = QFormLayout()
        form.addRow(tr("ase_refs.font"), self._family)
        form.addRow(tr("ase_refs.font_size"), self._size)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def selected_family(self) -> str:
        return self._family.currentFont().family()

    def selected_size(self) -> int:
        return self._size.value()
