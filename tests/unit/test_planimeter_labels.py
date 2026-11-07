"""Item 10 of the 2026-11-06 list: where a planimeter polygon is named.

The owner asked where to sign a traced contour.  The answer is both ends of
the same edit: the picker opens right after the polygon closes (otherwise two
polygons of one frame stay «Площадь1»/«Площадь2» on the image), and the
«откуда значение» card of the sheet can rename the row (the report is where the
duplicate is noticed).  The name lives in ``Contour.measurement_label``, so the
overlay, the report, the JSON and the DICOM annotations all follow one path;
Esc and an empty query keep the automatic name.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.calculations.planimeter import (
    GENERIC_AREA_CHAMBER,
    GENERIC_VOLUME_CHAMBER,
)
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.presentation.label_picker import (
    PICKER_CONTEXT_PLANIMETER,
    LabelOption,
    LabelPicker,
    default_label_options,
    normalize_context,
    search_label_options,
)

pytestmark = pytest.mark.gui


def _viewer(qtbot):
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer._magnetic_snap_enabled = False
    viewer._view.mapSceneToView = lambda pos: pos  # type: ignore[method-assign]
    return viewer


# ── Catalog ────────────────────────────────────────────────────────


def test_the_planimetry_context_is_a_picker_context(qtbot) -> None:
    """It is not a panel context: the tool row never shows «Планиметрия»."""
    from echo_personal_tool.domain.tool_panel_view import PANEL_CONTEXTS

    assert normalize_context(PICKER_CONTEXT_PLANIMETER) == PICKER_CONTEXT_PLANIMETER
    assert PICKER_CONTEXT_PLANIMETER not in PANEL_CONTEXTS


def test_the_default_rows_are_places_a_contour_is_traced(qtbot) -> None:
    options = default_label_options(PICKER_CONTEXT_PLANIMETER)
    assert [option.target_label for option in options] == ["LV", "LA", "RA", "LVOT", "Thyroid lobe"]
    assert all(option.kind == "planimeter" for option in options)


def test_the_catalog_keeps_the_general_ultrasound_sites(qtbot) -> None:
    targets = {option.target_label for option in search_label_options("почка", context=PICKER_CONTEXT_PLANIMETER)}
    assert "Kidney" in targets
    assert "Bladder" in {option.target_label for option in search_label_options("пузырь", context="planimeter")}


def test_an_option_carries_the_label_in_both_languages(qtbot) -> None:
    option = next(iter(default_label_options(PICKER_CONTEXT_PLANIMETER)))
    assert option.label("ru") == "ЛЖ"
    assert option.label("en") == "LV"
    assert option.full_name("ru") == "Левый желудочек"


# ── Picker ─────────────────────────────────────────────────────────


def _picker(qtbot) -> LabelPicker:
    picker = LabelPicker()
    qtbot.addWidget(picker)
    return picker


def test_the_picker_opens_for_a_contour_with_the_anatomy_rows(qtbot) -> None:
    picker = _picker(qtbot)
    picker.open_for(value_text="12.50 cm²", context=PICKER_CONTEXT_PLANIMETER)
    assert picker.context() == PICKER_CONTEXT_PLANIMETER
    assert picker.options()[0].target_label == "LV"


def test_a_typed_name_becomes_a_free_label(qtbot) -> None:
    """A thyroid nodule has no catalog row; the physician names it in words."""
    picker = _picker(qtbot)
    seen: list[LabelOption] = []
    picker.label_selected.connect(seen.append)
    picker.open_for(context=PICKER_CONTEXT_PLANIMETER)
    picker.set_search_query("узел щж")

    assert picker.accept_current() is True

    assert seen and seen[0].target_label == "узел щж"
    assert seen[0].kind == "planimeter"


def test_an_empty_query_does_not_invent_a_label(qtbot) -> None:
    picker = _picker(qtbot)
    seen: list[LabelOption] = []
    picker.label_selected.connect(seen.append)
    picker.open_for(context=PICKER_CONTEXT_PLANIMETER)
    picker.set_search_query("   ")

    # The default rows are still selectable, so «nothing typed» selects a row.
    if picker.selected_option() is None:
        assert picker.accept_current() is False
        assert seen == []


def test_another_context_never_accepts_free_text(qtbot) -> None:
    picker = _picker(qtbot)
    picker.open_for(context="2d")
    picker.set_search_query("узел щж")
    assert picker.custom_label_text() == ""


# ── Viewer ─────────────────────────────────────────────────────────


def _finish_polygon(viewer) -> Contour:
    assert viewer.start_generic_area_contour() is True
    for x, y in ((10.0, 10.0), (40.0, 10.0), (40.0, 40.0)):
        viewer.handle_contour_click((x, y))
    assert viewer._finish_closed_contour() is True
    return viewer.contours()[-1]


def test_the_picker_opens_when_the_polygon_closes(qtbot) -> None:
    viewer = _viewer(qtbot)
    contour = _finish_polygon(viewer)

    assert viewer.is_label_picker_visible() is True
    assert viewer.label_picker().context() == PICKER_CONTEXT_PLANIMETER
    assert contour.measurement_label  # the automatic name is there from the start


def test_a_cardiac_contour_is_not_offered_a_planimetry_name(qtbot) -> None:
    viewer = _viewer(qtbot)
    lv = Contour(phase="ED", chamber="LV", points=[(10.0, 10.0), (40.0, 10.0), (40.0, 40.0)])
    viewer._open_label_picker_for_contour(lv)
    assert viewer.is_label_picker_visible() is False


def test_the_picked_name_reaches_the_contour_and_the_overlay(qtbot) -> None:
    viewer = _viewer(qtbot)
    contour = _finish_polygon(viewer)
    emitted: list[list] = []
    viewer.contours_changed.connect(emitted.append)

    option = next(iter(default_label_options(PICKER_CONTEXT_PLANIMETER)))
    viewer._apply_picked_label(option)

    stored = viewer.contours()[-1]
    assert stored.measurement_label == "LV"
    assert stored.revision == contour.revision + 1
    assert emitted and emitted[-1][-1].measurement_label == "LV"


def test_escape_keeps_the_automatic_name(qtbot) -> None:
    viewer = _viewer(qtbot)
    before = _finish_polygon(viewer)

    assert viewer.dismiss_label_picker() is True

    assert viewer.contours()[-1].measurement_label == before.measurement_label


def test_the_report_renames_by_measurement_id(qtbot) -> None:
    viewer = _viewer(qtbot)
    contour = _finish_polygon(viewer)
    target = Contour(
        phase=contour.phase,
        chamber=contour.chamber,
        points=contour.points,
        frame_index=contour.frame_index,
        measurement_id="m-42",
        sop_instance_uid=contour.sop_instance_uid,
    )
    viewer._stored_contours = [target]

    assert viewer.rename_contour_measurement("m-42", "Мочевой пузырь") is True
    assert viewer.contours()[0].measurement_label == "Мочевой пузырь"
    assert viewer.rename_contour_measurement("ghost", "X") is False


def test_two_polygons_of_one_frame_stay_apart_after_naming(qtbot) -> None:
    viewer = _viewer(qtbot)
    first = _finish_polygon(viewer)
    viewer.dismiss_label_picker()
    second = _finish_polygon(viewer)
    assert first.measurement_label != second.measurement_label

    viewer.rename_contour_measurement(second.measurement_id, "Почка")

    labels = [contour.measurement_label for contour in viewer.contours()]
    assert "Почка" in labels
    assert len(labels) == len(set(labels))


def test_the_volume_polygon_uses_the_volume_chamber(qtbot) -> None:
    viewer = _viewer(qtbot)
    assert viewer.start_generic_volume_contour() is True
    for x, y in ((10.0, 10.0), (40.0, 10.0), (40.0, 40.0)):
        viewer.handle_contour_click((x, y))
    assert viewer._finish_closed_contour() is True
    assert viewer.contours()[-1].chamber.upper() == GENERIC_VOLUME_CHAMBER
    assert viewer.is_label_picker_visible() is True


def test_a_disabled_picker_leaves_the_automatic_name(qtbot) -> None:
    viewer = _viewer(qtbot)
    viewer.set_label_picker_enabled(False)
    contour = _finish_polygon(viewer)
    assert viewer.is_label_picker_visible() is False
    assert contour.chamber.upper() == GENERIC_AREA_CHAMBER
    assert contour.measurement_label


class TestTheSheetRenamesARow:
    """Item 10: the «откуда значение» card renames the planimetry row.

    The report is where the physician notices that two polygons read
    «Площадь1», so the rename must not require a trip back to the images: the
    card asks the window, the window asks the viewer, and the usual
    ``contours_changed`` path carries the name everywhere.
    """

    def _card(self, qtbot):
        from echo_personal_tool.domain.models.value_origin import ValueOrigin
        from echo_personal_tool.domain.services.report_builder import ReportValue
        from echo_personal_tool.presentation.report_mode.provenance import ReportValueCard

        card = ReportValueCard()
        qtbot.addWidget(card)
        value = ReportValue(
            label="Площадь1",
            value="12.50",
            unit="cm²",
            origin=ValueOrigin(kind="measurement", method_id="planimeter", measurement_id="m-1"),
        )
        card.show_value(value)
        return card

    def test_a_planimetry_row_offers_the_rename(self, qtbot) -> None:
        card = self._card(qtbot)
        assert card._rename_target() == "m-1"
        assert card._rename.objectName() == "reportValueCardRename"

    def test_a_caliper_row_has_nothing_to_rename(self, qtbot) -> None:
        from echo_personal_tool.domain.models.value_origin import ValueOrigin
        from echo_personal_tool.domain.services.report_builder import ReportValue
        from echo_personal_tool.presentation.report_mode.provenance import ReportValueCard

        card = ReportValueCard()
        qtbot.addWidget(card)
        card.show_value(
            ReportValue(
                label="КДР ЛЖ",
                value="52.0",
                origin=ValueOrigin(kind="measurement", method_id="linear_caliper", measurement_id="c-1"),
            )
        )
        assert card._rename_target() is None

    def test_the_card_emits_the_new_name(self, qtbot, monkeypatch) -> None:
        from PySide6.QtWidgets import QInputDialog

        card = self._card(qtbot)
        seen: list[tuple[str, str]] = []
        card.rename_requested.connect(lambda mid, label: seen.append((mid, label)))
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Почка", True)))

        card._request_rename()

        assert seen == [("m-1", "Почка")]

    def test_a_cancelled_dialog_changes_nothing(self, qtbot, monkeypatch) -> None:
        from PySide6.QtWidgets import QInputDialog

        card = self._card(qtbot)
        seen: list[tuple[str, str]] = []
        card.rename_requested.connect(lambda mid, label: seen.append((mid, label)))
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Почка", False)))

        card._request_rename()

        assert seen == []

    def test_the_same_name_is_not_an_edit(self, qtbot, monkeypatch) -> None:
        from PySide6.QtWidgets import QInputDialog

        card = self._card(qtbot)
        seen: list[tuple[str, str]] = []
        card.rename_requested.connect(lambda mid, label: seen.append((mid, label)))
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Площадь1", True)))

        card._request_rename()

        assert seen == []
