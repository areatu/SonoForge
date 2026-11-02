"""Calculators tab inside the tool panel (Э11)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.calculator_inputs import resolve_standalone_inputs
from echo_personal_tool.domain.calculators import evaluate
from echo_personal_tool.domain.calculators.text import format_input_value
from echo_personal_tool.infrastructure.i18n import set_language, tr
from echo_personal_tool.presentation.tool_panel import ToolPanel


@pytest.fixture(autouse=True)
def _app():
    app = QApplication.instance() or QApplication([])
    set_language("en")
    yield app
    set_language("en")


def test_calculators_tab_sits_after_measures() -> None:
    panel = ToolPanel()
    tabs = panel._tabs
    assert tabs.indexOf(panel.measure) == 0
    assert tabs.indexOf(panel.calculators) == 1
    assert tabs.indexOf(panel.controls) == 2


def test_tab_captions_follow_the_language() -> None:
    panel = ToolPanel()
    set_language("ru")
    panel.reload_text()
    tabs = panel._tabs
    assert tabs.tabText(tabs.indexOf(panel.calculators)) == tr("tool_panel.calculators") == "Расчёты"
    assert tabs.tabText(tabs.indexOf(panel.controls)) == tr("tool_panel.controls")
    assert tabs.tabText(tabs.indexOf(panel.measure)) == tr("tool_panel.measures")


def test_set_calculations_and_forwarded_override() -> None:
    panel = ToolPanel()
    calculations = evaluate(resolve_standalone_inputs({"lvot_d": 2.0, "lvot_vti": 20.0}))
    panel.set_calculations(calculations, has_study=True)
    assert panel.calculators.current_calculations() is calculations
    seen: list[tuple[str, object]] = []
    panel.calculator_input_changed.connect(lambda key, value: seen.append((key, value)))
    panel.calculators.study_input_changed.emit("hr", 70.0)
    assert seen == [("hr", 70.0)]
    panel.show_calculators_tab()
    assert panel._tabs.currentWidget() is panel.calculators


def test_calculators_widgets_are_built_on_first_show(qtbot) -> None:
    """The hidden tab must not cost ~350 widgets per window (app-wide restyles repolish them all)."""
    from PySide6.QtWidgets import QWidget

    panel = ToolPanel()
    qtbot.addWidget(panel)
    calculators = panel.calculators
    assert not calculators.is_built
    assert calculators.findChildren(QWidget) == []
    # State set before the build is kept and rendered on first show.
    calculators.set_mode("standalone")
    calculations = evaluate(resolve_standalone_inputs({"lvot_d": 2.0, "lvot_vti": 20.0}))
    panel.set_calculations(calculations, has_study=True)
    set_language("ru")
    panel.reload_text()
    assert not calculators.is_built

    panel.show()
    panel.show_calculators_tab()
    qtbot.waitUntil(lambda: calculators.is_built)
    assert calculators.mode == "standalone"
    assert calculators._mode_combo.currentData() == "standalone"
    assert calculators._mode_combo.itemText(0) == tr("calc.mode.study")
    calculators.set_mode("study")
    assert calculators.current_calculations() is calculations
    lvot_d = next(item for item in calculations.inputs if item.id == "lvot_d")
    assert calculators._rows["lvot_d"].edit.text() == format_input_value(lvot_d) != ""


def test_lazy_panel_public_api_builds_on_demand() -> None:
    from echo_personal_tool.presentation.calculators_panel import CalculatorsPanel

    panel = CalculatorsPanel(lazy=True)
    assert not panel.is_built
    assert not panel.is_section_expanded("continuity")
    assert panel.is_built


def test_calculators_tab_widens_panel() -> None:
    """The narrow panel (280) grows ≥1.5× on the Calculators tab and back."""
    panel = ToolPanel()
    base = panel._base_width
    assert base >= 280
    panel.show_calculators_tab()
    assert panel.width() == panel.minimumWidth() == int(base * 1.5)
    panel._tabs.setCurrentWidget(panel.measure)
    assert panel.width() == panel.minimumWidth() == base


def test_calculators_tab_widens_panel_animated(qtbot) -> None:
    """Visible panel glides (not snaps) between the widths.

    The animation clock is driven manually: in a full suite earlier modules
    leave thousands of undisposed widgets behind and the event queue can stay
    saturated for seconds, starving wall-clock animations. Driving the clock
    checks the same plumbing (target, duration, width at rest) deterministically.
    """
    from PySide6.QtCore import QAbstractAnimation

    panel = ToolPanel()
    qtbot.addWidget(panel)
    panel.show()
    base = panel._base_width
    expanded = int(base * 1.5)
    panel.show_calculators_tab()
    anim = panel._width_anim
    assert anim is not None
    assert anim.state() == QAbstractAnimation.State.Running
    assert anim.duration() == panel._CALC_WIDTH_ANIM_MS
    assert anim.endValue() == expanded
    anim.setCurrentTime(anim.duration())
    assert panel.width() == expanded
    panel._tabs.setCurrentWidget(panel.controls)
    anim = panel._width_anim
    assert anim is not None
    anim.setCurrentTime(anim.duration())
    assert panel.width() == base


def test_calculators_glide_pins_content_width(qtbot) -> None:
    """Outer width animates; the calculators surface is not reflowed per frame."""
    panel = ToolPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.calculators._ensure_built()
    panel.setFixedWidth(panel._base_width)
    panel.show_calculators_tab()
    expanded = int(panel._base_width * panel._CALC_WIDTH_FACTOR)
    assert panel.calculators.clip_width() == expanded
    assert panel.calculators._surface.width() == expanded
    anim = panel._width_anim
    assert anim is not None
    anim.setCurrentTime(anim.duration() // 2)
    assert panel.width() != expanded
    assert panel.calculators._surface.width() == expanded
    anim.setCurrentTime(anim.duration())
    assert panel.width() == expanded
    assert panel.calculators.clip_width() is None


def test_crossfade_leaves_no_graphics_effect(qtbot) -> None:
    """Opacity effects are dropped at rest so later paints stay cheap."""
    panel = ToolPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel._tabs.setCurrentWidget(panel.controls)
    fade = panel._fade_anim
    assert fade is not None
    fade.setCurrentTime(fade.duration())
    assert panel.controls.graphicsEffect() is None


def test_controls_tab_follows_the_language() -> None:
    """Window/Level/DR sliders and checks re-render on language switch."""
    panel = ToolPanel()
    set_language("ru")
    panel.reload_text()
    assert panel.controls.window_slider._title.text() == tr("tools.window") == "Окно"
    assert panel.controls.level_slider._title.text() == tr("tools.level") == "Уровень"
    assert panel.controls.dr_slider._title.text() == tr("tools.dr") == "ДР"
    assert panel.controls._magnetic_snap_check.text() == tr("tools.magnetic_snap")
    assert panel.controls._despeckle_check.text() == tr("tools.grayscale")
    set_language("en")
    panel.reload_text()
    assert panel.controls.window_slider._title.text() == "Window"
    assert panel.controls.level_slider._title.text() == "Level"
    assert panel.controls.dr_slider._title.text() == "DR"


def test_bsa_label_shows_the_manual_value_and_its_source(qtbot) -> None:
    """QH-1b.2 slice 2: no second BSA on screen — the label uses the study's one."""
    from echo_personal_tool.domain.models.result_provenance import BSA_SOURCE_MANUAL, BsaBasis
    from echo_personal_tool.infrastructure.i18n import set_language, tr

    set_language("en")
    panel = ToolPanel()
    qtbot.addWidget(panel)
    panel.set_patient_metrics(170.0, 70.0, BsaBasis(1.55, BSA_SOURCE_MANUAL, 170.0, 70.0))

    label = panel.measure._bsa_label
    assert label.isVisible() or label.text()
    assert "1.55 m²" in label.text()
    assert tr("provenance.bsa_source_manual") in label.text()


def test_bsa_label_without_body_metrics_says_no_data(qtbot) -> None:
    from echo_personal_tool.infrastructure.i18n import set_language, tr

    set_language("en")
    panel = ToolPanel()
    qtbot.addWidget(panel)
    panel.set_patient_metrics(None, None, None)

    assert panel.measure._bsa_label.text() == tr("panel.bsa_missing")


def test_manual_rap_real_window_edit_restart_and_clear(tmp_path, qtbot) -> None:
    """QH-1d UI evidence: real line edit/reset in MainWindow round-trips through disk."""
    from datetime import datetime, timezone

    from PySide6.QtCore import Qt

    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.application.calculator_inputs import resolve_study_inputs
    from echo_personal_tool.application.measurement_persistence import MeasurementPersistence
    from echo_personal_tool.domain.calculators import evaluate
    from echo_personal_tool.domain.models import InstanceMetadata, StudyMetadata
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.main_window import MainWindow

    preferences = UserPreferences(measurement_persistence_enabled=True)
    uid = "1.2.826.0.1.3680043.10.999.177"
    instance = InstanceMetadata(
        sop_instance_uid=uid + ".1",
        series_uid=uid,
        modality="US",
        number_of_frames=1,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="Synthetic UI evidence",
    )
    study = StudyMetadata(
        study_uid=uid,
        study_datetime=datetime.now(timezone.utc),
        series=(),
    )

    def controller_for_disk() -> AppController:
        controller = AppController()
        controller.measurement_persistence.close()
        persistence = MeasurementPersistence(
            tmp_path / "records", controller._measurement_session, enabled=True, parent=controller
        )
        persistence.status.connect(controller.persistence_status.emit)
        persistence.restored.connect(controller._on_persisted_measurements_restored)
        persistence.saved.connect(controller._on_record_saved)
        controller.measurement_persistence = persistence
        controller.state_manager.set_instance(instance, total_frames=1, frame_time_ms=33.3, emit=False)
        return controller

    def wait_for_load(controller: AppController) -> None:
        done: list[bool] = []
        controller.measurement_persistence.load([study], lambda: done.append(True))
        qtbot.waitUntil(lambda: bool(done), timeout=5000)

    first = controller_for_disk()
    first_window = MainWindow(controller=first, user_preferences=preferences)
    qtbot.addWidget(first_window)
    wait_for_load(first)
    first_window._tool_panel.set_calculations(evaluate(resolve_study_inputs(doppler=None, manual={})), has_study=True)
    first_window.show()
    qtbot.waitExposed(first_window)
    first_window._tool_panel.show_calculators_tab()
    qtbot.waitUntil(lambda: first_window._tool_panel.calculators.is_built)

    rap = first_window._tool_panel.calculators._rows["rap"]
    rap.edit.setFocus()
    rap.edit.setText("8")
    qtbot.keyClick(rap.edit, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: first._calculator_inputs.manual(uid).get("rap") == 8.0)
    assert first._measurement_session.get(uid).manual_calculator_inputs[0].value == 8.0
    assert first.measurement_persistence.enabled
    assert uid in first.measurement_persistence._dirty
    assert uid in first.measurement_persistence._contexts
    assert first.measurement_persistence.flush()
    committed = first.measurement_persistence.repository.load(uid)
    assert committed is not None and committed["data"].manual_calculator_inputs[0].value == 8.0
    first_window.close()

    # A genuinely new controller/window must hydrate the same bytes before the
    # field is used; this is the UI-level restart half, not a stores-only test.
    restarted = controller_for_disk()
    wait_for_load(restarted)
    assert restarted._calculator_inputs.manual(uid) == {"rap": 8.0}
    restarted_window = MainWindow(controller=restarted, user_preferences=preferences)
    qtbot.addWidget(restarted_window)
    restarted_window._tool_panel.set_calculations(
        evaluate(resolve_study_inputs(doppler=None, manual=restarted._calculator_inputs.manual(uid))),
        has_study=True,
    )
    restarted_window.show()
    qtbot.waitExposed(restarted_window)
    restarted_window._tool_panel.show_calculators_tab()
    qtbot.waitUntil(lambda: restarted_window._tool_panel.calculators.is_built)
    rap = restarted_window._tool_panel.calculators._rows["rap"]
    assert rap.edit.text() == "8"
    assert rap.source.text().casefold() == "manual"

    rap.edit.setFocus()
    rap.edit.clear()
    qtbot.keyClick(rap.edit, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not restarted._calculator_inputs.manual(uid))
    assert restarted._measurement_session.get(uid).manual_calculator_inputs == ()
    assert restarted.measurement_persistence.flush()
    saved = restarted.measurement_persistence.repository.load(uid)
    assert saved is not None and saved["data"].manual_calculator_inputs == ()
    restarted_window.close()
