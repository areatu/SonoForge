"""Focus view of a single file (UI-6, spec §4.8) — the Qt-free decisions.

Everything the mode decides without a window lives here: what counts as one
file, when the automatic entry may fire, which slots the view keeps, how the
floating plates are placed and what «Копировать» puts on the clipboard.
"""

from __future__ import annotations

from datetime import datetime

from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.presentation.focus_mode import (
    FOCUS_CARD_HEIGHT,
    FOCUS_CARD_WIDTH,
    FOCUS_CINE_HEIGHT,
    FOCUS_CINE_WIDTH,
    FOCUS_MARGIN,
    PLATE_FADE_DISTANCE,
    PLATE_FADE_OPACITY,
    SINGLE_FILE_CLIP_COUNT,
    FocusHeaderInfo,
    FocusRect,
    clip_count,
    copy_text,
    focus_header_text,
    focus_plan,
    is_single_file,
    measurement_lines,
    place_focus_panels,
    plate_opacity,
    should_enter_focus,
    split_measurement_line,
)
from echo_personal_tool.presentation.layout.presets import SLOT_RAIL, SLOT_VIEWER


def _instance(uid: str = "1.2.3") -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid=f"{uid}.series",
        modality="US",
        number_of_frames=4,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="A4C",
    )


def _study(*instances: InstanceMetadata) -> StudyMetadata:
    return StudyMetadata(
        study_uid="1.2.3.study",
        study_datetime=datetime(2026, 10, 1),
        series=(
            SeriesMetadata(
                series_uid="1.2.3.study.series",
                study_uid="1.2.3.study",
                modality="US",
                description="A4C",
                instances=tuple(instances),
            ),
        ),
    )


# ── what counts as a single file ────────────────────────────────────


def test_one_clip_is_a_single_file() -> None:
    studies = [_study(_instance())]
    assert clip_count(studies) == SINGLE_FILE_CLIP_COUNT
    assert is_single_file(studies)


def test_two_clips_are_not_a_single_file() -> None:
    studies = [_study(_instance("1.2.3.a"), _instance("1.2.3.b"))]
    assert clip_count(studies) == 2
    assert not is_single_file(studies)


def test_clips_are_counted_across_series_and_studies() -> None:
    first = _study(_instance("a"))
    second = _study(_instance("b"), _instance("c"))
    assert clip_count([first, second]) == 3
    assert not is_single_file([first, second])


def test_an_empty_workspace_is_not_a_single_file() -> None:
    assert clip_count([]) == 0
    assert not is_single_file([])


# ── automatic entry (§4.8, UQ-02) ───────────────────────────────────


def test_auto_entry_needs_both_the_switch_and_one_file() -> None:
    single = [_study(_instance())]
    pair = [_study(_instance("a"), _instance("b"))]
    assert should_enter_focus(enabled=True, studies=single)
    assert not should_enter_focus(enabled=False, studies=single)
    assert not should_enter_focus(enabled=True, studies=pair)


def test_auto_entry_is_off_for_an_empty_workspace() -> None:
    assert not should_enter_focus(enabled=True, studies=[])


# ── layout plan (§4.8, F1) ──────────────────────────────────────────


def test_focus_plan_keeps_the_rail_and_drops_the_panels() -> None:
    plan = focus_plan()
    assert plan.left == SLOT_RAIL
    assert plan.center == SLOT_VIEWER
    assert plan.right is None
    assert plan.bottom is None
    # The strip lives in the column slot of the tool row, not in the row itself.
    assert plan.top is None


# ── header facts ────────────────────────────────────────────────────


def test_header_text_joins_only_known_facts() -> None:
    info = FocusHeaderInfo(file_label="a.avi", projection="A4C", patient="Иванов И. И.", date="01.10.2026")
    assert focus_header_text(info) == "A4C · Иванов И. И. · 01.10.2026"


def test_header_text_of_a_video_without_demographics_is_empty() -> None:
    info = FocusHeaderInfo(file_label="clip.mp4")
    assert info.parts() == ()
    assert focus_header_text(info) == ""


def test_header_separator_is_configurable() -> None:
    info = FocusHeaderInfo(projection="A4C", patient="П.")
    assert focus_header_text(info, separator=" — ") == "A4C — П."


# ── the card rows ───────────────────────────────────────────────────


def test_measurement_line_splits_into_label_and_value() -> None:
    assert split_measurement_line("КДО 4C: 112 mL") == ("КДО 4C", "112 mL")


def test_a_line_without_a_separator_keeps_its_whole_text() -> None:
    assert split_measurement_line("Диастолическая дисфункция I") == ("Диастолическая дисфункция I", "")


def test_a_value_that_itself_contains_a_colon_is_not_cut_twice() -> None:
    assert split_measurement_line("Индекс: 1:2") == ("Индекс", "1:2")


def test_measurement_lines_drop_the_blank_ones() -> None:
    assert measurement_lines("А: 1\n\n  Б: 2  \n") == ("А: 1", "Б: 2")
    assert measurement_lines("") == ()


# ── floating plates ─────────────────────────────────────────────────


def test_the_card_sits_top_right_and_the_plate_bottom_centre() -> None:
    rects = place_focus_panels(1600, 900)
    assert rects.card.right == 1600 - FOCUS_MARGIN
    assert rects.card.y == FOCUS_MARGIN
    assert rects.card.width == FOCUS_CARD_WIDTH
    assert rects.cine.y + rects.cine.height == 900 - FOCUS_MARGIN
    assert abs((rects.cine.x + rects.cine.width / 2) - 800) <= 1
    assert rects.cine.width == FOCUS_CINE_WIDTH


def test_the_plates_never_overlap_each_other() -> None:
    for width, height in ((1600, 900), (1280, 720), (900, 600), (640, 480), (320, 260)):
        rects = place_focus_panels(width, height)
        assert not rects.card.intersects(rects.cine), (width, height)
        assert rects.card.right <= width
        assert rects.cine.bottom <= height


def test_a_short_viewer_shrinks_the_card_first() -> None:
    rects = place_focus_panels(1280, 220)
    assert rects.card.height < FOCUS_CARD_HEIGHT
    assert rects.cine.height == FOCUS_CINE_HEIGHT
    assert rects.card.bottom + 8 <= rects.cine.y


def test_a_degenerate_area_still_yields_valid_geometry() -> None:
    for width, height in ((0, 0), (10, 10), (-5, -5)):
        rects = place_focus_panels(width, height)
        for rect in (rects.card, rects.cine):
            assert rect.x >= 0 and rect.y >= 0
            assert rect.width >= 0 and rect.height >= 0


def test_the_plate_height_is_clamped_by_the_area() -> None:
    rects = place_focus_panels(1280, 70)
    assert rects.cine.height <= 70 - 2 * FOCUS_MARGIN
    assert rects.cine.height < FOCUS_CINE_HEIGHT


def test_rect_touching_edges_do_not_intersect() -> None:
    left = FocusRect(0, 0, 10, 10)
    right = FocusRect(10, 0, 10, 10)
    assert not left.intersects(right)
    assert left.intersects(FocusRect(5, 5, 2, 2))


# ── «Копировать» ────────────────────────────────────────────────────


def test_copy_text_starts_with_the_title_and_the_file_facts() -> None:
    info = FocusHeaderInfo(file_label="a.avi", projection="A4C", patient="Иванов И. И.")
    text = copy_text(info, ["КДО: 112 mL"], title="Измерения в этом файле")
    assert text == "Измерения в этом файле\na.avi · A4C · Иванов И. И.\n\nКДО: 112 mL"


def test_copy_text_without_facts_keeps_a_blank_line_before_the_values() -> None:
    text = copy_text(FocusHeaderInfo(), ["КДО: 112 mL"], title="Измерения")
    assert text == "Измерения\n\nКДО: 112 mL"


def test_copy_text_of_an_empty_card_is_just_the_title() -> None:
    assert copy_text(FocusHeaderInfo(), [], title="Измерения") == "Измерения"


# ── the plates step back near the pointer (§4.8) ────────────────────


def test_a_plate_is_opaque_far_from_the_pointer() -> None:
    rect = FocusRect(100, 100, 200, 100)
    assert plate_opacity(0, 0, rect) == 1.0
    assert plate_opacity(500, 500, rect) == 1.0


def test_a_plate_fades_under_the_pointer() -> None:
    rect = FocusRect(100, 100, 200, 100)
    assert plate_opacity(150, 150, rect) == PLATE_FADE_OPACITY


def test_a_plate_fades_within_the_reach_of_its_edge() -> None:
    rect = FocusRect(100, 100, 200, 100)
    assert plate_opacity(100 - PLATE_FADE_DISTANCE, 150, rect) == PLATE_FADE_OPACITY
    assert plate_opacity(100 - PLATE_FADE_DISTANCE - 2, 150, rect) == 1.0


def test_the_reach_is_measured_to_the_nearest_corner() -> None:
    rect = FocusRect(100, 100, 200, 100)
    # Diagonal approach: (94, 94) is ~8.5 px from the corner, inside the reach.
    assert plate_opacity(94, 94, rect) == PLATE_FADE_OPACITY
    # 30 px along both axes is ~42 px away — outside the 28 px reach.
    assert plate_opacity(70, 70, rect) == 1.0


def test_an_empty_plate_fades_only_under_the_pointer() -> None:
    empty = FocusRect(50, 50, 0, 0)
    assert plate_opacity(50, 50, empty) == PLATE_FADE_OPACITY
    assert plate_opacity(50 + PLATE_FADE_DISTANCE, 50, empty) == 1.0
