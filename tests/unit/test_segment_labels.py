"""Segment naming: vendor-style short labels next to the wall, full AHA names elsewhere.

The cine overlay and the strain window label the *same* segments, so both call
this module — a segment must never read differently on the image and in the
panel. The tests pin three properties: all 18 standard ids are translated in
both locales, an unknown id degrades visibly instead of borrowing a name, and
the short labels are the compact vendor style (not the full prose names).
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.segment_map import SEGMENT_NAMES, view_segment_ids
from echo_personal_tool.infrastructure.i18n import set_language, tr
from echo_personal_tool.presentation.segment_labels import (
    full_segment_label,
    short_segment_label,
)

ALL_SEGMENT_IDS = tuple(range(1, 19))


@pytest.fixture(autouse=True)
def _restore_language():
    set_language("ru")
    yield
    set_language("en")


class TestShortLabels:
    def test_all_18_ids_are_translated_in_both_locales(self):
        for lang in ("ru", "en"):
            set_language(lang)
            for segment_id in ALL_SEGMENT_IDS:
                label = short_segment_label(segment_id)
                assert label, f"segment {segment_id} has no {lang} short label"
                assert not label.startswith("strain."), f"segment {segment_id} missing in {lang}: {label}"

    def test_short_labels_are_compact(self):
        """They are drawn on the image, so they must stay small."""
        for lang in ("ru", "en"):
            set_language(lang)
            for segment_id in ALL_SEGMENT_IDS:
                assert len(short_segment_label(segment_id)) <= 12

    def test_labels_are_distinct_within_a_view(self):
        """Two walls of one view must not be labelled identically."""
        for lang in ("ru", "en"):
            set_language(lang)
            for view in ("A4C", "A2C", "A3C"):
                labels = [short_segment_label(seg) for seg in view_segment_ids(view)]
                assert len(set(labels)) == len(labels), f"{view} in {lang}: {labels}"

    def test_known_vendor_style_names(self):
        set_language("ru")
        assert short_segment_label(3) == "БазПерг"
        assert short_segment_label(9) == "СрПерг"
        assert short_segment_label(18) == "АпБок"
        set_language("en")
        assert short_segment_label(3) == "BasSept"
        assert short_segment_label(18) == "ApLat"

    def test_unknown_id_falls_back_to_the_id_itself(self):
        set_language("en")
        assert short_segment_label(99) == tr("strain.segment_fallback", id="99")
        assert "99" in short_segment_label(99)


class TestFullLabels:
    def test_full_names_match_the_locale(self):
        set_language("ru")
        assert full_segment_label(15) == "Апикальный нижнеперегородочный"
        assert full_segment_label(2) == "Базальный переднеперегородочный"
        set_language("en")
        assert full_segment_label(15) == "Apical inferoseptal"

    def test_full_names_cover_the_canonical_aha_names(self):
        """Every canonical id resolves to a translated name, not to the id."""
        set_language("en")
        for segment_id in sorted(SEGMENT_NAMES):
            label = full_segment_label(segment_id)
            assert label and label != f"Segment {segment_id}"

    def test_unknown_id_degrades_to_the_id(self):
        set_language("en")
        assert "77" in full_segment_label(77)
