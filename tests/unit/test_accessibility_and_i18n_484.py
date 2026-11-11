"""Accessibility inventory, keyboard tab-order, and UI i18n gates (#484, #485).

Covers all acceptance criteria of issue #484:
1. Offscreen pytest-qt inventory across MainWindow, ToolPanel/ToolRail, Viewer
   transport, ReportModePage, UserPreferencesDialog, and OrthancStudyDialog:
   every focusable ``QAbstractButton`` without alphabetic visible text has a
   non-empty ``accessibleName()`` (ratchet ceiling = 0).
2. Main clinical workflow controls (open -> calibration -> contour -> results
   overlay -> report/export + cine transport) expose localized ``accessibleName``
   and ``accessibleDescription`` in both RU and EN and update on live language
   reload.
3. Explicit ``setTabOrder`` and keyboard-only navigation (#286 UA-19) across
   UserPreferencesDialog, ReportModePage / PhraseEditorDialog, and
   OrthancStudyDialog.
4. Migrated UI strings (PropertiesPanel, CommandPalette, SpeckleSettingsDialog,
   ServerSettingsWidget, ToolPanel, StrainWindow/ControlPanel, Constructor) use
   ``tr()`` with RU/EN parity, guarded by ``scripts/check_untranslated_ui_strings.py``.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget

from echo_personal_tool.application.localization import set_language, tr

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_untranslated_ui_strings  # noqa: E402


@pytest.fixture(autouse=True)
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _restore_russian():
    set_language("ru")
    yield
    set_language("ru")


def _nameless_icon_or_symbol_buttons(root: QWidget) -> list[str]:
    """Return descriptions of focusable buttons lacking alphabetic text AND accessibleName."""
    offenders: list[str] = []
    for button in root.findChildren(QAbstractButton):
        if button.focusPolicy() == Qt.FocusPolicy.NoFocus:
            continue
        visible = button.text().strip()
        has_alpha = any(ch.isalpha() for ch in visible)
        if not has_alpha and not button.accessibleName().strip():
            parent_name = type(button.parentWidget()).__name__ if button.parentWidget() else "None"
            offenders.append(
                f"{type(button).__name__}(objectName={button.objectName()!r}, text={visible!r}, parent={parent_name})"
            )
    return offenders


def _assert_focus_chain_order(chain: list[QWidget] | tuple[QWidget, ...]) -> None:
    """Verify that walking ``nextInFocusChain()`` visits ``chain`` in order."""
    assert len(chain) >= 2
    for prev_widget, target in zip(chain, chain[1:]):
        cursor = prev_widget.nextInFocusChain()
        steps = 0
        visited: list[QWidget] = []
        while cursor is not None and cursor is not prev_widget and steps < 64:
            if cursor is target:
                break
            visited.append(cursor)
            cursor = cursor.nextInFocusChain()
            steps += 1
        assert cursor is target, (
            f"Expected focus to move from {type(prev_widget).__name__}({prev_widget.objectName()!r}) "
            f"to {type(target).__name__}({target.objectName()!r}), visited={len(visited)}"
        )


# ── 1. Accessible-name inventory & zero-ceiling ratchet ───────────────────


class TestAccessibleNameInventoryRatchet:
    def test_main_window_has_zero_nameless_icon_or_symbol_buttons(self, qtbot, app_services) -> None:
        from echo_personal_tool.application.app_controller import AppController
        from echo_personal_tool.presentation.main_window import MainWindow

        controller = AppController(services=app_services)
        window = MainWindow(controller=controller, services=app_services)
        qtbot.addWidget(window)

        assert _nameless_icon_or_symbol_buttons(window) == []

    def test_report_preferences_and_pacs_dialogs_have_zero_nameless_buttons(self, qtbot) -> None:
        from echo_personal_tool.presentation.orthanc_study_dialog import OrthancStudyDialog
        from echo_personal_tool.presentation.report_mode import ReportModePage
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        report_page = ReportModePage(translate=tr)
        qtbot.addWidget(report_page)
        assert _nameless_icon_or_symbol_buttons(report_page) == []

        prefs_dialog = UserPreferencesDialog()
        qtbot.addWidget(prefs_dialog)
        assert _nameless_icon_or_symbol_buttons(prefs_dialog) == []

        cache_mock = MagicMock()
        cache_mock.list_cached_studies.return_value = []
        pacs_dialog = OrthancStudyDialog(MagicMock(), cache_mock)
        qtbot.addWidget(pacs_dialog)
        assert _nameless_icon_or_symbol_buttons(pacs_dialog) == []


# ── 2. Main workflow accessibleName + accessibleDescription (RU <-> EN) ──


class TestMainWorkflowAccessibleDescriptions:
    def test_system_bar_rail_viewer_and_report_workflow_controls_retranslate(self, qtbot) -> None:
        from echo_personal_tool.presentation.report_mode.export import ReportExportPanel
        from echo_personal_tool.presentation.system_bar import SystemBar
        from echo_personal_tool.presentation.tool_buttons.rail import ToolButtonRail
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        set_language("ru")
        bar = SystemBar()
        rail = ToolButtonRail()
        viewer = ViewerWidget()
        export_panel = ReportExportPanel()
        for widget in (bar, rail, viewer, export_panel):
            qtbot.addWidget(widget)

        # Open -> Calibration -> Contour/Area -> Results overlay -> Report/PDF
        cal_btn = rail.button("calibration")
        area_btn = rail.button("spline_area")
        assert cal_btn is not None and area_btn is not None

        workflow_controls = (
            bar._btn_open,
            bar._btn_calibration,
            bar._btn_mode_report,
            cal_btn,
            area_btn,
            viewer._first_frame_button,
            viewer._play_button,
            viewer._last_frame_button,
            viewer._results_overlay_label,
            export_panel.pdf_button,
            export_panel.finish_button,
        )
        ru_pairs = [(w.accessibleName(), w.accessibleDescription()) for w in workflow_controls]
        for name, desc in ru_pairs:
            assert name.strip()
            assert desc.strip()

        set_language("en")
        bar.reload_text()
        rail.set_language("en")
        viewer.reload_text()
        export_panel.reload_text()

        en_pairs = [(w.accessibleName(), w.accessibleDescription()) for w in workflow_controls]
        for (ru_name, ru_desc), (en_name, en_desc) in zip(ru_pairs, en_pairs):
            assert en_name.strip() and en_desc.strip()
            assert (ru_name, ru_desc) != (en_name, en_desc)


# ── 3. Explicit Tab-order & keyboard-only scenario (#286 UA-19) ───────────


class TestDialogTabOrderAndKeyboardOnly:
    def test_report_mode_page_and_phrase_editor_tab_order(self, qtbot) -> None:
        from echo_personal_tool.presentation.report_mode import PhraseEditorDialog, ReportModePage

        page = ReportModePage(translate=tr)
        qtbot.addWidget(page)
        page.show()
        qtbot.waitExposed(page)

        patient_chain = page.patient_editor.tab_chain_widgets()
        phrases_chain = page.phrases.tab_chain_widgets()
        full_chain = (
            patient_chain[0],
            patient_chain[-1],
            phrases_chain[0],
            phrases_chain[-1],
            page.export.pdf_button,
            page.export.csv_button,
            page.export.json_button,
            page.export.print_button,
            page.export.finish_button,
        )
        _assert_focus_chain_order(full_chain)

        # Keyboard-only activation on the final export chain
        triggered: list[str] = []
        page.export_requested.connect(lambda: triggered.append("pdf"))
        page.export.pdf_button.setFocus()
        qtbot.keyClick(page.export.pdf_button, Qt.Key.Key_Space)
        assert triggered == ["pdf"]

        phrase_dlg = PhraseEditorDialog()
        qtbot.addWidget(phrase_dlg)
        _assert_focus_chain_order((phrase_dlg._section, phrase_dlg._ru, phrase_dlg._en))

    def test_user_preferences_dialog_tab_order_and_keyboard_section_switch(self, qtbot) -> None:
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)

        assert dlg._section_list.focusPolicy() == Qt.FocusPolicy.StrongFocus
        assert dlg._section_list.accessibleName() == tr("a11y.settings_sections")
        _assert_focus_chain_order(
            (
                dlg._search,
                dlg._section_list,
                *dlg._footer_buttons,
                dlg._close_btn,
            )
        )

        # Keyboard-only Down arrow in section list switches active settings page
        initial_section = dlg._current_section
        dlg._section_list.setFocus()
        qtbot.keyClick(dlg._section_list, Qt.Key.Key_Down)
        assert dlg._current_section != initial_section

    def test_orthanc_study_dialog_tab_order_and_keyboard_actions(self, qtbot) -> None:
        from echo_personal_tool.presentation.orthanc_study_dialog import OrthancStudyDialog

        cache_mock = MagicMock()
        cache_mock.list_cached_studies.return_value = []
        dlg = OrthancStudyDialog(MagicMock(), cache_mock)
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)

        _assert_focus_chain_order(
            (
                dlg._search_edit,
                dlg._find_btn,
                dlg._source_combo,
                dlg._sort_combo,
                dlg._thumbs_check,
                dlg._select_all_btn,
                dlg._clear_selection_btn,
                dlg._device_combo,
                dlg._modality_combo,
                dlg._studies_list,
                dlg._series_all_btn,
                dlg._series_none_btn,
                dlg._series_list,
                dlg._cancel_btn,
                dlg._close_btn,
            )
        )


# ── 4. Migrated UI strings & static AST gate ──────────────────────────────


class TestMigratedUiStringsAndAstGate:
    def test_command_palette_and_properties_panel_use_dictionary_keys(self, qtbot) -> None:
        from PySide6.QtCore import QSettings

        from echo_personal_tool.presentation.command_palette import CommandPalette
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "SonoForgeTest", "Palette484")
        settings.clear()

        set_language("ru")
        ru_palette = CommandPalette("full", settings=settings)
        qtbot.addWidget(ru_palette)
        assert ru_palette.windowTitle() == "Команды"
        assert ru_palette._query.placeholderText() == "Найти команду…"

        set_language("en")
        en_palette = CommandPalette("full", settings=settings)
        qtbot.addWidget(en_palette)
        assert en_palette.windowTitle() == "Commands"
        assert en_palette._query.placeholderText() == "Search commands…"

        set_language("ru")
        props = PropertiesPanel()
        qtbot.addWidget(props)
        props.update_measurement_info(label="IVSd", value_mm=10.2, start=(0.0, 0.0), end=(3.0, 4.0))
        props.update_contour_info(chamber="LV", phase="ED", point_count=24, area_px=512.0)
        labels_ru = [w.text() for w in props.findChildren(QWidget) if hasattr(w, "text")]
        assert "Метка:" in labels_ru
        assert "Длина в пикселях:" in labels_ru
        assert "Камера:" in labels_ru

    def test_ast_gate_passes_on_repository_and_flags_untranslated_literals(self) -> None:
        assert check_untranslated_ui_strings.main([]) == 0

        bad_source = textwrap.dedent(
            """
            from PySide6.QtWidgets import QLabel
            lbl = QLabel("Raw untranslated text")
            dlg.setWindowTitle("Команды" if _language() == "ru" else "Commands")
            form.addRow("Pixel length:", lbl)
            """
        )
        violations = check_untranslated_ui_strings.scan_source(bad_source, "demo.py")
        assert len(violations) == 4

        good_source = textwrap.dedent(
            """
            from PySide6.QtWidgets import QLabel, QLineEdit
            lbl = QLabel(tr("properties.measurement.label"))
            unit_lbl = QLabel(f"{val} mm")
            edit = QLineEdit()
            edit.setPlaceholderText("http://192.168.1.111:8042/dicom-web")
            """
        )
        assert check_untranslated_ui_strings.scan_source(good_source, "good.py") == []
