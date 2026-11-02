"""Unit tests for presentation/styled_dialogs.py."""

from __future__ import annotations

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


_DARK_PALETTE = {
    "bg_panel": "#1a1a1a",
    "text": "#ffffff",
    "bg_control": "#2a2a2a",
    "accent_tab": "#2196f3",
    "border": "#3a3a3a",
    "bg_button_hover": "#3a3a3a",
    "bg_button_pressed": "#4a4a4a",
}


def _make_mockFileDialog(*, accepted=False):
    """Create a mock QFileDialog with DialogCode enum set correctly."""

    mock_cls = MagicMock()
    mock_dialog = MagicMock()
    # Set the DialogCode.Accepted to be the same sentinel as exec() return
    sentinel = object()
    mock_cls.DialogCode.Accepted = sentinel
    mock_dialog.exec.return_value = sentinel if accepted else object()
    mock_cls.return_value = mock_dialog
    return mock_cls, mock_dialog


class TestStyleDialog:
    def test_button_box_is_localized_and_reloads_with_language(self):
        from PySide6.QtWidgets import QApplication, QDialogButtonBox

        from echo_personal_tool.infrastructure.i18n import get_language, set_language
        from echo_personal_tool.presentation.styled_dialogs import localize_dialog_button_box

        previous_language = get_language()
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Close
        )
        try:
            localize_dialog_button_box(box)
            set_language("ru")
            assert box.button(QDialogButtonBox.StandardButton.Ok).text() == "ОК"
            assert box.button(QDialogButtonBox.StandardButton.Cancel).text() == "Отмена"
            assert box.button(QDialogButtonBox.StandardButton.Close).text() == "Закрыть"
            set_language("en")
            assert box.button(QDialogButtonBox.StandardButton.Cancel).text() == "Cancel"
        finally:
            set_language(previous_language)
            box.deleteLater()
            app = QApplication.instance()
            if app is not None:
                app.processEvents()

    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette")
    def test_style_dialog_applies_palette(self, mock_palette):
        from PySide6.QtWidgets import QFileDialog

        from echo_personal_tool.presentation.styled_dialogs import _style_dialog

        mock_palette.return_value = _DARK_PALETTE
        dialog = QFileDialog()
        _style_dialog(dialog)
        assert dialog.palette() is not None
        dialog.close()


class TestStyledOpenFile:
    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_file_when_accepted(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_open_file

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=True)
        mock_dialog.selectedFiles.return_value = ["/tmp/test.dcm"]
        mock_dialog.selectedNameFilter.return_value = "DICOM (*.dcm)"

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_open_file(title="Open")
        assert result == ("/tmp/test.dcm", "DICOM (*.dcm)")

    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_empty_when_rejected(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_open_file

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=False)

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_open_file()
        assert result == ("", "")

    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_empty_when_no_files(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_open_file

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=True)
        mock_dialog.selectedFiles.return_value = []

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_open_file()
        assert result == ("", "")


class TestStyledOpenFiles:
    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_multiple_files(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_open_files

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=True)
        mock_dialog.selectedFiles.return_value = ["/tmp/a.dcm", "/tmp/b.dcm"]

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_open_files()
        assert result == ["/tmp/a.dcm", "/tmp/b.dcm"]

    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_empty_list_when_rejected(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_open_files

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=False)

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_open_files()
        assert result == []


class TestStyledSaveFile:
    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_saved_path(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=True)
        mock_dialog.selectedFiles.return_value = ["/tmp/report.pdf"]
        mock_dialog.selectedNameFilter.return_value = "PDF (*.pdf)"

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_save_file()
        assert result == ("/tmp/report.pdf", "PDF (*.pdf)")

    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_empty_when_rejected(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=False)

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_save_file()
        assert result == ("", "")


class TestStyledSelectDirectory:
    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_directory(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_select_directory

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=True)
        mock_dialog.selectedFiles.return_value = ["/data/dicoms"]

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_select_directory()
        assert result == "/data/dicoms"

    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_empty_when_rejected(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_select_directory

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=False)

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_select_directory()
        assert result == ""


class _StubScreen:
    """Minimal ``QScreen`` duck type: physical size, work area, DPR."""

    def __init__(self, width: int, height: int, dpr: float = 1.0, available: tuple[int, int] | None = None):
        from PySide6.QtCore import QRect

        self._geometry = QRect(0, 0, width, height)
        av_w, av_h = available if available is not None else (width, height)
        self._available = QRect(0, 0, av_w, av_h)
        self._dpr = dpr

    def geometry(self):
        return self._geometry

    def availableGeometry(self):
        return self._available

    def devicePixelRatio(self) -> float:
        return self._dpr


class TestOpenFolderGeometry:
    def test_reference_screen(self):
        from echo_personal_tool.presentation.styled_dialogs import open_folder_geometry

        assert open_folder_geometry(_StubScreen(1920, 1200)) == (750, 600, 200)

    def test_scale_factor_keeps_the_physical_layout(self):
        """125 % on 1920x1200 → logical 1536x960, DPR 1.25 → same layout."""
        from echo_personal_tool.presentation.styled_dialogs import open_folder_geometry

        assert open_folder_geometry(_StubScreen(1536, 960, dpr=1.25)) == (750, 600, 200)

    def test_wider_screen_scales_up(self):
        from echo_personal_tool.presentation.styled_dialogs import open_folder_geometry

        assert open_folder_geometry(_StubScreen(2560, 1440)) == (900, 720, 240)

    def test_small_screen_clamps_the_scale_and_the_divider(self):
        from echo_personal_tool.presentation.styled_dialogs import open_folder_geometry

        width, height, divider = open_folder_geometry(_StubScreen(1366, 768))
        assert (width, height) == (525, 420)  # scale clamped to 0.7
        assert divider == 160  # never narrower than the places column needs

    def test_never_exceeds_the_work_area(self):
        from echo_personal_tool.presentation.styled_dialogs import open_folder_geometry

        width, height, _divider = open_folder_geometry(_StubScreen(1920, 1200, available=(700, 500)))
        assert (width, height) == (668, 468)

    def test_no_screen_falls_back_to_the_reference_layout(self):
        from echo_personal_tool.presentation.styled_dialogs import open_folder_geometry

        assert open_folder_geometry(None) == (750, 600, 200)


class TestApplyOpenFolderGeometry:
    def test_sizes_dialog_and_places_the_divider(self):
        from PySide6.QtWidgets import QFileDialog, QSplitter

        from echo_personal_tool.presentation.styled_dialogs import _apply_open_folder_geometry

        dialog = QFileDialog()
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        try:
            _apply_open_folder_geometry(dialog, screen=_StubScreen(1920, 1200))
            assert (dialog.width(), dialog.height()) == (750, 600)

            splitter = dialog.findChild(QSplitter, "splitter")
            assert splitter is not None
            handle = splitter.handle(1)
            assert handle is not None
            # Centre of the section divider, measured from the dialog edge.
            divider_x = splitter.geometry().x() + handle.geometry().x() + splitter.handleWidth() // 2
            assert divider_x == 200
        finally:
            dialog.close()

    def test_never_raises_on_a_dialog_without_a_splitter(self):
        from echo_personal_tool.presentation.styled_dialogs import _apply_open_folder_geometry

        # No layout, no splitter, no screen: geometry must not break the dialog.
        dialog = MagicMock()
        _apply_open_folder_geometry(dialog, screen=_StubScreen(1920, 1200))
        dialog.resize.assert_called_once_with(750, 600)
