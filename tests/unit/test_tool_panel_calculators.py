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
    assert panel.is_section_expanded("continuity")
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
