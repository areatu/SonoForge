"""Unit and GUI tests for TP-4 post-measurement label picker (spec §4.4, §8.1, §9)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QScrollArea

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.models.doppler_roi import (
    DopplerCalibrationState,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.infrastructure.i18n import set_language
from echo_personal_tool.infrastructure.user_preferences import default_user_preferences
from echo_personal_tool.presentation.label_picker import (
    DEFAULT_CONTEXT_OPTION_IDS,
    LabelPicker,
    all_label_options,
    default_label_options,
    option_for_target_label,
    option_for_tool_id,
    search_label_options,
)
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

_FRAME = 200
_ROI = DopplerSpectrogramRoi(x0=50.0, y0=50.0, width=100.0, height=80.0)
_BASELINE_Y = 90.0
_TIME_SPAN_MS = 1000.0
_VEL_SPAN_CM_S = 160.0


def _make_state(uid: str = "1.2.3.4.5.6") -> ViewerState:
    instance = InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="1.2.3.4.5",
        modality="US",
        number_of_frames=1,
        pixel_spacing=(1.0, 1.0),
        frame_time_ms=33.3,
        # The window is a cardiology affordance (ТЗ 2026-10-23, п. 1): the
        # fixtures are echocardiography, so the study has to say so.
        series_description="Adult Echo",
        path=None,
        media_format="dicom",
    )
    return ViewerState(
        instance=instance,
        current_frame_index=0,
        total_frames=1,
        frame_time_ms=33.3,
        is_playing=False,
    )


def _simulate_view_press(viewer: ViewerWidget, x: float, y: float) -> None:
    ev = SimpleNamespace(
        button=lambda: Qt.MouseButton.LeftButton,
        pos=lambda: QPointF(x, y),
    )
    viewer._map_view_event = lambda _e: (x, y)  # type: ignore[method-assign]
    assert viewer._handle_linear_caliper_mouse_press(ev)


def _place_caliper(
    viewer: ViewerWidget,
    start: tuple[float, float],
    end: tuple[float, float],
) -> None:
    _simulate_view_press(viewer, *start)
    _simulate_view_press(viewer, *end)


def _stored_labels(viewer: ViewerWidget) -> list[str]:
    return [m.label for m in viewer._stored_linear_measurements.values()]


# ── Pure domain / catalog options tests (not_gui) ──────────────────


class TestLabelPickerDomain:
    def test_all_label_options_excludes_generic_tools(self) -> None:
        options = all_label_options()
        ids = {opt.tool_id for opt in options}
        assert "tool.caliper" not in ids
        assert "tool.vti_trace" not in ids
        assert "lv.ivsd" in ids
        assert "lv.lvedd" in ids
        assert "mv.e" in ids
        assert "lvot.vti" in ids

    def test_option_lookup_by_tool_id_and_target_label(self) -> None:
        ivsd = option_for_tool_id("lv.ivsd")
        assert ivsd is not None
        assert ivsd.target_label == "IVSd"
        assert ivsd.kind == "caliper"
        assert option_for_tool_id("tool.ivsd") == ivsd
        assert option_for_target_label("IVSd") == ivsd

        mv_e = option_for_tool_id("mv.e")
        assert mv_e is not None
        assert mv_e.target_label == "E"
        assert mv_e.kind == "peak"

        lvot_vti = option_for_tool_id("lvot.vti")
        assert lvot_vti is not None
        assert lvot_vti.target_label == "LVOT VTI"
        assert lvot_vti.kind == "trace"

    def test_default_2d_options_match_spec_mockup(self) -> None:
        set_language("ru")
        opts = default_label_options("2d")
        assert len(opts) == 5
        assert tuple(o.tool_id for o in opts) == DEFAULT_CONTEXT_OPTION_IDS["2d"]
        assert [o.label("ru") for o in opts] == [
            "МЖП",
            "КДР ЛЖ",
            "ЗСЛЖ",
            "ЛП ПЗР",
            "Синусы аорты",
        ]
        assert [o.label("en") for o in opts] == [
            "IVSD",
            "LVEDD",
            "LVPWD",
            "LA AP",
            "AoSoV",
        ]

    def test_default_mmode_options(self) -> None:
        opts = default_label_options("m")
        assert len(opts) == 5
        assert tuple(o.tool_id for o in opts) == (
            "lv.ivsd",
            "lv.lvedd",
            "lv.lvpwd",
            "lv.lvesd",
            "rv.tapse",
        )

    def test_default_doppler_options_match_spec_section_4_4(self) -> None:
        opts = default_label_options("doppler")
        assert len(opts) == 5
        assert tuple(o.tool_id for o in opts) == (
            "mv.e",
            "mv.a",
            "lvot.vti",
            "av.vmax",
            "tr.vmax",
        )
        assert [o.label("ru") for o in opts] == [
            "E",
            "A",
            "VTI ВТЛЖ",
            "Vmax АК",
            "Vmax ТР",
        ]

    def test_search_matches_ru_en_synonyms_and_wrong_layout(self) -> None:
        # Russian short label
        res_ru = search_label_options("кдр", context="2d")
        assert res_ru and res_ru[0].tool_id == "lv.lvedd"

        # English code / synonym
        res_en = search_label_options("lvedd", context="2d")
        assert res_en and res_en[0].tool_id == "lv.lvedd"

        # Wrong keyboard layout: "rlh" typed on EN layout corresponds to "кдр"
        res_layout = search_label_options("rlh", context="2d")
        assert res_layout and res_layout[0].tool_id == "lv.lvedd"

        # Doppler search
        res_dop = search_label_options("втлж", context="doppler")
        assert any(o.tool_id == "lvot.vti" for o in res_dop)


# ── Widget tests (gui) ─────────────────────────────────────────────


@pytest.mark.gui
class TestLabelPickerWidget:
    def test_open_renders_header_and_five_rows(self, qtbot) -> None:
        parent = ViewerWidget()
        qtbot.addWidget(parent)
        parent.resize(640, 480)
        picker = LabelPicker(parent)
        picker.open_for(
            value_text="41 мм",
            context="2d",
            anchor=QPoint(200, 200),
            bounds=QRect(0, 0, 640, 480),
        )
        assert not picker.isHidden()
        assert "41 мм" in picker.title_text()
        assert len(picker.options()) == 5
        assert picker.selected_index() == 0
        assert picker.selected_option() is not None
        assert picker.selected_option().tool_id == "lv.ivsd"

    def test_digit_hotkey_selects_option(self, qtbot) -> None:
        parent = ViewerWidget()
        qtbot.addWidget(parent)
        picker = LabelPicker(parent)
        selected = []
        picker.label_selected.connect(selected.append)
        picker.open_for(value_text="41 мм", context="2d", anchor=QPoint(100, 100))

        ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_2, Qt.KeyboardModifier.NoModifier, "2")
        assert picker.handle_key_press(ev) is True
        assert len(selected) == 1
        assert selected[0].tool_id == "lv.lvedd"
        assert picker.isHidden()

    def test_tab_cycles_and_enter_accepts(self, qtbot) -> None:
        parent = ViewerWidget()
        qtbot.addWidget(parent)
        picker = LabelPicker(parent)
        selected = []
        tabs = []
        picker.label_selected.connect(selected.append)
        picker.tab_cycled.connect(lambda: tabs.append(True))
        picker.open_for(value_text="41 мм", context="2d", anchor=QPoint(100, 100))

        tab_ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
        assert picker.handle_key_press(tab_ev) is True
        assert picker.selected_index() == 1
        assert len(tabs) == 1

        enter_ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        assert picker.handle_key_press(enter_ev) is True
        assert len(selected) == 1
        assert selected[0].tool_id == "lv.lvedd"
        assert picker.isHidden()

    def test_escape_dismisses_without_selecting(self, qtbot) -> None:
        parent = ViewerWidget()
        qtbot.addWidget(parent)
        picker = LabelPicker(parent)
        selected = []
        dismissed = []
        picker.label_selected.connect(selected.append)
        picker.dismissed.connect(lambda: dismissed.append(True))
        picker.open_for(value_text="41 мм", context="2d", anchor=QPoint(100, 100))

        esc_ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        assert picker.handle_key_press(esc_ev) is True
        assert selected == []
        assert len(dismissed) == 1
        assert picker.isHidden()

    def test_search_filters_options_and_clamps_position(self, qtbot) -> None:
        parent = ViewerWidget()
        qtbot.addWidget(parent)
        parent.resize(400, 300)
        picker = LabelPicker(parent)
        picker.open_for(
            value_text="22 мм",
            context="2d",
            anchor=QPoint(395, 295),
            bounds=QRect(0, 0, 400, 300),
        )
        assert picker.x() + picker.width() <= 400
        assert picker.y() + picker.height() <= 300

        picker.set_search_query("tapse")
        assert picker.selected_option() is not None
        assert picker.selected_option().tool_id == "rv.tapse"

    def test_popup_never_leaves_small_bounds(self, qtbot) -> None:
        """Карточка не выходит за границы области, даже когда не помещается целиком.

        Регресс CI (миграция ubuntu-latest на Ubuntu 26): с ростом метрик
        шрифтов карточка стала выше (295 px) и вылезала за bounds 300 px вместе
        с полями 8 px (``y + height = 8 + 295 = 303 > 300``). Теперь размер
        карточки ограничен размером области при любых шрифтах.
        """
        parent = ViewerWidget()
        qtbot.addWidget(parent)
        parent.resize(260, 160)
        picker = LabelPicker(parent)
        area = QRect(0, 0, 260, 160)
        picker.open_for(
            value_text="22 мм",
            context="2d",
            anchor=QPoint(255, 155),
            bounds=area,
        )
        assert picker.width() <= area.width()
        assert picker.height() <= area.height()
        assert picker.x() >= area.left()
        assert picker.y() >= area.top()
        assert picker.x() + picker.width() <= area.left() + area.width()
        assert picker.y() + picker.height() <= area.top() + area.height()

    def test_small_bounds_shrink_list_but_keep_all_options(self, qtbot) -> None:
        """При сжатии список прокручивается: все 5 вариантов остаются доступны."""
        parent = ViewerWidget()
        qtbot.addWidget(parent)
        parent.resize(260, 160)
        picker = LabelPicker(parent)
        picker.open_for(
            value_text="22 мм",
            context="2d",
            anchor=QPoint(40, 40),
            bounds=QRect(0, 0, 260, 160),
        )
        assert picker.height() <= 160
        assert len(picker.options()) == 5
        assert all(row.option is not None for row in picker._rows)
        # Строки не срезаны: суммарная высота строк сохранена и прокручивается.
        scroll = picker.findChild(QScrollArea, "labelPickerScroll")
        assert scroll is not None
        assert scroll.maximumHeight() < 160
        assert scroll.widget().height() >= sum(row.height() for row in picker._rows)
        # Последний вариант выбирается с клавиатуры, хотя ниже края видимости.
        for _ in range(4):
            picker.cycle_next(emit_tab=False)
        selected = []
        picker.label_selected.connect(selected.append)
        assert picker.accept_current() is True
        assert selected and selected[0].tool_id == picker.options()[4].tool_id


# ── Viewer integration tests (gui) ─────────────────────────────────


@pytest.mark.gui
class TestViewerLabelPickerIntegration:
    def _make_viewer(self, qtbot) -> ViewerWidget:
        w = ViewerWidget()
        qtbot.addWidget(w)
        w.resize(640, 480)
        w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
        w.set_state(_make_state())
        return w

    def test_free_caliper_opens_picker_and_digit_relabels_measurement(self, qtbot) -> None:
        w = self._make_viewer(qtbot)
        emitted: list[list] = []
        w.linear_measurements_changed.connect(emitted.append)

        w.activate_generic_dist_caliper()
        _place_caliper(w, (10.0, 10.0), (51.0, 10.0))

        assert w.is_label_picker_visible()
        assert "41" in w.label_picker().title_text()
        assert _stored_labels(w) == ["Dist1"]

        # Press '2' -> КДР ЛЖ (LVEDD)
        ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_2, Qt.KeyboardModifier.NoModifier, "2")
        assert w.handle_label_picker_key(ev) is True
        assert not w.is_label_picker_visible()

        assert _stored_labels(w) == ["LVEDD"]
        assert emitted[-1][0].label == "LVEDD"
        # Repeat mode stays armed with Dist2 for the next measurement
        assert w.is_linear_caliper_active
        assert w._current_caliper_label() == "Dist2"

    def test_tab_cycles_picker_and_enter_applies_label(self, qtbot) -> None:
        w = self._make_viewer(qtbot)
        w.activate_generic_dist_caliper()
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        assert w.is_label_picker_visible()

        w.cycle_caliper_label()
        assert w.label_picker().selected_index() == 1
        assert w._current_caliper_label() == "Dist2"

        assert w.accept_label_picker() is True
        assert not w.is_label_picker_visible()
        assert _stored_labels(w) == ["LVEDD"]

    def test_escape_leaves_caliper_unlabeled(self, qtbot) -> None:
        w = self._make_viewer(qtbot)
        w.activate_generic_dist_caliper()
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        assert w.is_label_picker_visible()

        assert w.dismiss_label_picker() is True
        assert not w.is_label_picker_visible()
        assert _stored_labels(w) == ["Dist1"]

    def test_anatomical_and_sequence_calipers_do_not_open_picker(self, qtbot) -> None:
        w = self._make_viewer(qtbot)
        w.start_linear_caliper_for("LVEDD")
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        assert not w.is_label_picker_visible()

        w.start_linear_caliper_sequence(["IVSd", "LVEDD"])
        _place_caliper(w, (10.0, 20.0), (20.0, 20.0))
        assert not w.is_label_picker_visible()

    def test_a_general_ultrasound_study_never_opens_the_picker(self, qtbot) -> None:
        """Abdomen/thyroid/kidneys have no closed set of caliper names (ТЗ п. 1).

        Naming a free caliper there means searching a cardiology catalog for a
        word that is not in it; the measurement stays a plain «Dist1» instead.
        """
        from echo_personal_tool.domain.models.viewer_state import ViewerState

        w = ViewerWidget()
        qtbot.addWidget(w)
        w.resize(640, 480)
        w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
        state = _make_state()
        w.set_state(
            ViewerState(
                instance=type(state.instance)(
                    sop_instance_uid=state.instance.sop_instance_uid,
                    series_uid=state.instance.series_uid,
                    modality="US",
                    number_of_frames=1,
                    pixel_spacing=(1.0, 1.0),
                    frame_time_ms=33.3,
                    series_description="Abdomen",
                    body_part="ABDOMEN",
                    path=None,
                    media_format="dicom",
                ),
                current_frame_index=0,
                total_frames=1,
                frame_time_ms=33.3,
                is_playing=False,
            )
        )
        assert w.is_cardiac_context() is False

        w.activate_generic_dist_caliper()
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        assert not w.is_label_picker_visible()
        assert _stored_labels(w) == ["Dist1"]

    def test_an_unknown_study_type_keeps_the_picker_out(self, qtbot) -> None:
        """No evidence is «no»: the window never guesses (ТЗ п. 1)."""
        w = ViewerWidget()
        qtbot.addWidget(w)
        w.resize(640, 480)
        w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
        assert w.is_cardiac_context() is False

    def test_the_host_can_override_the_study_type(self, qtbot) -> None:
        w = self._make_viewer(qtbot)
        assert w.is_cardiac_context() is True
        w.set_cardiac_context(False)
        assert w.is_cardiac_context() is False
        w.activate_generic_dist_caliper()
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        assert not w.is_label_picker_visible()

        w.set_cardiac_context(None)  # back to the header-derived rule
        assert w.is_cardiac_context() is True

    def test_active_protocol_suppresses_picker(self, qtbot) -> None:
        w = self._make_viewer(qtbot)
        w.set_protocol_active(True)
        w.activate_generic_dist_caliper()
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        assert not w.is_label_picker_visible()

    def test_preference_disables_picker(self, qtbot) -> None:
        w = self._make_viewer(qtbot)
        prefs = default_user_preferences()
        prefs.label_picker_enabled = False
        w.apply_user_preferences(prefs)

        w.activate_generic_dist_caliper()
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        assert not w.is_label_picker_visible()

    def test_doppler_caliper_and_free_trace_relabeling(self, qtbot) -> None:
        w = self._make_viewer(qtbot)
        cal = DopplerCalibrationState(
            roi=_ROI,
            baseline_y_px=_BASELINE_Y,
            time_span_ms=_TIME_SPAN_MS,
            velocity_span_cm_s=_VEL_SPAN_CM_S,
        )
        w.apply_doppler_calibration_state(cal, persist=False)

        # 1) Free caliper inside Doppler ROI -> opens Doppler picker
        w.activate_generic_dist_caliper()
        _place_caliper(w, (60.0, _BASELINE_Y), (70.0, 70.0))
        assert w.is_label_picker_visible()
        assert w.label_picker().context() == "doppler"

        # Select 1 -> E (mv.e)
        ev1 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_1, Qt.KeyboardModifier.NoModifier, "1")
        assert w.handle_label_picker_key(ev1) is True
        assert "E" in _stored_labels(w)
        dto = w.get_doppler_dto()
        assert any(p.label == "E" for p in dto.peaks)

        # 2) Free Doppler trace ("VTI") -> opens Doppler picker and relabels trace
        w.set_doppler_tool_mode("trace", trace_label="VTI")
        w._doppler._active_partial_points = [(100.0, 0.0), (150.0, 80.0), (200.0, 0.0)]
        assert w.finish_doppler_trace() is True
        assert w.is_label_picker_visible()

        # Select 3 -> VTI ВТЛЖ (LVOT VTI)
        ev3 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_3, Qt.KeyboardModifier.NoModifier, "3")
        assert w.handle_label_picker_key(ev3) is True
        dto = w.get_doppler_dto()
        assert dto.traces[-1].label == "LVOT VTI"

    def test_specific_doppler_trace_does_not_open_picker(self, qtbot) -> None:
        w = self._make_viewer(qtbot)
        cal = DopplerCalibrationState(
            roi=_ROI,
            baseline_y_px=_BASELINE_Y,
            time_span_ms=_TIME_SPAN_MS,
            velocity_span_cm_s=_VEL_SPAN_CM_S,
        )
        w.apply_doppler_calibration_state(cal, persist=False)

        w.set_doppler_tool_mode("trace", trace_label="AV VTI")
        w._doppler._active_partial_points = [(100.0, 0.0), (150.0, 80.0), (200.0, 0.0)]
        assert w.finish_doppler_trace() is True
        assert not w.is_label_picker_visible()

    def test_viewer_key_press_routes_russian_typing_to_picker_search(self, qtbot) -> None:
        w = self._make_viewer(qtbot)
        w.activate_generic_dist_caliper()
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        assert w.is_label_picker_visible()

        # Type 'к', 'д', 'р' directly via ViewerWidget.keyPressEvent
        for key, ch in ((Qt.Key.Key_R, "к"), (Qt.Key.Key_L, "д"), (Qt.Key.Key_H, "р")):
            ev = QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, ch)
            w.keyPressEvent(ev)

        assert w.label_picker().search_query() == "кдр"
        assert w.label_picker().selected_option() is not None
        assert w.label_picker().selected_option().tool_id == "lv.lvedd"
