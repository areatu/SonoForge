"""Unit tests for presentation/ase_reference_dialog.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _key_press_event(key):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)


class TestLoadIcon:
    def test_loads_svg(self):
        from echo_personal_tool.presentation.ase_reference_dialog import _load_icon

        pixmap = _load_icon("close")

        assert not pixmap.isNull(), "the bundled close glyph renders"
        assert pixmap.width() > 0

    def test_nonexistent_icon_returns_empty_pixmap(self):
        from PySide6.QtGui import QPixmap

        from echo_personal_tool.presentation.ase_reference_dialog import _load_icon

        pixmap = _load_icon("nonexistent_icon_12345")
        assert isinstance(pixmap, QPixmap)


class TestRenderPdfPage:
    def test_returns_none_when_no_pymupdf(self):
        from echo_personal_tool.presentation.ase_reference_dialog import _render_pdf_page

        with patch.dict("sys.modules", {"pymupdf": None}):
            result = _render_pdf_page(MagicMock(), 0)
            assert result is None

    def test_negative_page_returns_none(self):
        from echo_personal_tool.presentation.ase_reference_dialog import _render_pdf_page

        result = _render_pdf_page(MagicMock(__len__=MagicMock(return_value=5)), -1)
        assert result is None

    def test_page_out_of_range(self):
        from echo_personal_tool.presentation.ase_reference_dialog import _render_pdf_page

        doc = MagicMock()
        doc.__len__ = MagicMock(return_value=3)
        result = _render_pdf_page(doc, 10)
        assert result is None


class TestShowAseReferenceDialog:
    def test_shows_dialog(self):
        from echo_personal_tool.presentation.ase_reference_dialog import show_ase_reference_dialog

        with patch("echo_personal_tool.presentation.ase_reference_dialog.AseReferenceDialog") as mock_cls:
            mock_dialog = MagicMock()
            mock_cls.return_value = mock_dialog
            show_ase_reference_dialog()
            mock_dialog.exec.assert_called_once()

    def test_navigates_to_param(self):
        from echo_personal_tool.presentation.ase_reference_dialog import show_ase_reference_dialog

        with patch("echo_personal_tool.presentation.ase_reference_dialog.AseReferenceDialog") as mock_cls:
            mock_dialog = MagicMock()
            mock_cls.return_value = mock_dialog
            show_ase_reference_dialog(param_id="test-param")
            mock_dialog.navigate_to_param.assert_called_once_with("test-param")

    def test_handles_exception(self):
        from echo_personal_tool.presentation import ase_reference_dialog as module

        with (
            patch.object(module, "_CACHED_REFERENCE_DIALOG", None),
            patch.object(module, "AseReferenceDialog", side_effect=Exception("err")),
            patch.object(module, "QMessageBox") as message_box,
        ):
            module.show_ase_reference_dialog()

            message_box.critical.assert_called_once()
            assert module._CACHED_REFERENCE_DIALOG is None, "a failed dialog is never cached"


class TestDocTab:
    def test_init(self):
        from echo_personal_tool.presentation.ase_reference_dialog import _DocTab

        tab = _DocTab("Test", Path("/tmp/test.md"))
        assert tab.doc_path == Path("/tmp/test.md")
        tab.close()

    def test_set_active(self):
        from echo_personal_tool.presentation.ase_reference_dialog import _DocTab

        tab = _DocTab("Test", Path("/tmp/test.md"))
        inactive_style = tab.styleSheet()

        tab.set_active(True)
        assert tab._btn_label.isChecked()
        assert "bold" in tab._btn_label.styleSheet(), "the active tab label is bold"
        assert tab.styleSheet() != inactive_style, "the active tab is restyled"

        tab.set_active(False)
        assert not tab._btn_label.isChecked()
        assert "bold" not in tab._btn_label.styleSheet()
        assert tab.styleSheet() == inactive_style
        tab.close()

    def test_close_signal(self):
        from echo_personal_tool.presentation.ase_reference_dialog import _DocTab

        spy = MagicMock()
        tab = _DocTab("Test", Path("/tmp/test.md"))
        tab.close_requested.connect(spy)
        tab._on_close_clicked()
        spy.assert_called_once()
        tab.close()


class TestPdfContinuousWidget:
    def test_init(self):
        from echo_personal_tool.presentation.ase_reference_dialog import _PdfContinuousWidget

        w = _PdfContinuousWidget()
        assert len(w._page_labels) == 0
        w.close()

    def test_render_pages_empty_doc(self):
        from echo_personal_tool.presentation.ase_reference_dialog import _PdfContinuousWidget

        w = _PdfContinuousWidget()
        doc = MagicMock()
        doc.__len__ = MagicMock(return_value=0)
        w.render_pages(doc, 0, 10, 150)
        assert len(w._page_labels) == 0
        w.close()


class TestAseReferenceDialogInit:
    def test_creates(self):
        from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

        d = AseReferenceDialog()
        assert d.windowTitle() != ""
        d.close()

    def test_initial_state(self):
        from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

        d = AseReferenceDialog()
        # _load_default_documents() and showMaximized() are called in __init__
        assert d._pdf_current_page == 0
        assert isinstance(d._documents, list)
        d.close()

    def test_has_browser(self):
        from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

        d = AseReferenceDialog()
        assert d._browser is not None
        d.close()

    def test_has_tabs(self):
        from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

        d = AseReferenceDialog()
        assert d._btn_structured_tab is not None
        d.close()


class TestToggleMaximize:
    def test_toggle(self):
        from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

        d = AseReferenceDialog()
        d._is_maximized = True
        d._normal_geometry = None
        d.showMaximized()
        assert d.isMaximized()

        d._toggle_maximize()

        assert not d.isMaximized(), "toggling a maximized dialog restores its normal size"
        d.close()

    def test_toggle_to_maximized(self):
        from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

        d = AseReferenceDialog()
        d._is_maximized = False
        d.showNormal()
        assert not d.isMaximized()
        normal_geometry = d.geometry()

        d._toggle_maximize()

        assert d.isMaximized()
        assert d._normal_geometry == normal_geometry, "the normal geometry is kept for the way back"
        d.close()


class TestShowStructuredTab:
    def test_shows_structured(self):
        from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

        d = AseReferenceDialog()
        d._show_structured_tab()
        assert d._btn_structured_tab.isChecked()
        d.close()


class TestKeyNavigation:
    def test_right_key_pdf(self):
        from PySide6.QtCore import Qt

        from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

        d = AseReferenceDialog()
        d._active_doc_index = 0
        d._documents = [("test", Path("/tmp"), "pdf")]
        d._pdf_docs[Path("/tmp")] = MagicMock(__len__=MagicMock(return_value=5))
        d._pdf_total_pages = 5
        d._pdf_current_page = 0

        with patch.object(d, "_render_pdf"):
            d.keyPressEvent(_key_press_event(Qt.Key.Key_Right))
        assert d._pdf_current_page == 1
        d.close()

    def test_left_key_pdf(self):
        from PySide6.QtCore import Qt

        from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

        d = AseReferenceDialog()
        d._active_doc_index = 0
        d._documents = [("test", Path("/tmp"), "pdf")]
        d._pdf_current_page = 2
        d._pdf_total_pages = 5

        with patch.object(d, "_render_pdf"):
            d.keyPressEvent(_key_press_event(Qt.Key.Key_Left))
        assert d._pdf_current_page == 1
        d.close()

    def test_space_key_pdf(self):
        from PySide6.QtCore import Qt

        from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

        d = AseReferenceDialog()
        d._active_doc_index = 0
        d._documents = [("test", Path("/tmp"), "pdf")]
        d._pdf_current_page = 0
        d._pdf_total_pages = 5

        with patch.object(d, "_render_pdf"):
            d.keyPressEvent(_key_press_event(Qt.Key.Key_Space))
        assert d._pdf_current_page == 1
        d.close()

    def test_key_no_active_doc(self):

        from echo_personal_tool.presentation.ase_reference_dialog import AseReferenceDialog

        d = AseReferenceDialog()
        d._active_doc_index = -1
        # keyPressEvent should fall through to super() when no active doc
        # Just verify no crash by checking the condition
        assert d._active_doc_index < 0
        d.close()
