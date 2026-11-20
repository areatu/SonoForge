"""Variant В of the 2026-10-17 decision (issue #275): the rail is bound to the catalog.

The row and the rail are one table (:data:`buttons.TOOL_BUTTONS`), and every
measurement button of it carries the **catalog id as its own id**
(``id == ref``), so ``action_requested`` reports the same identity the panel
rows and the Measures menu use.  The visible set, order, captions and icons do
not change — only the identity is bound.  The tests below pin the binding and
the empty-catalog behaviour the acceptance checklist asks about.
"""

from __future__ import annotations

from echo_personal_tool.domain.measurement_catalog import CATALOG
from echo_personal_tool.presentation.tool_buttons import buttons
from echo_personal_tool.presentation.tool_buttons.buttons import (
    SOURCE_CATALOG,
    TOOL_BUTTON_STATE_EMPTY,
    TOOL_BUTTONS,
    caption,
    tool_button_spec,
    visible_buttons,
)


def test_every_catalog_button_carries_the_catalog_id() -> None:
    catalog_specs = [spec for spec in TOOL_BUTTONS if spec.source == SOURCE_CATALOG]
    assert catalog_specs, "the strip must have measurement buttons"
    for spec in catalog_specs:
        assert spec.ref in CATALOG, f"{spec.ref} is not in the catalog"
        assert spec.catalog_id == spec.ref
        if not spec.label_key:
            # A plain measurement button IS the catalog entry (variant В).
            assert spec.id == spec.ref, f"{spec.id} is not bound to its catalog id {spec.ref}"
        else:
            # A mode variant (the freehand pair) keeps its own id but still
            # resolves through the catalog.
            assert spec.id not in CATALOG


def test_mode_buttons_keep_their_own_ids() -> None:
    for spec in TOOL_BUTTONS:
        if spec.source != SOURCE_CATALOG:
            assert spec.catalog_id == ""


def test_catalog_button_caption_comes_from_the_catalog() -> None:
    # UD-15: no third copy of the captions — the button reads the catalog label.
    for spec in TOOL_BUTTONS:
        if spec.source != SOURCE_CATALOG or spec.label_key:
            continue
        tool = CATALOG[spec.ref]
        assert caption(spec, "ru") == tool.label("ru").short
        assert caption(spec, "en") == tool.label("en").short


def test_lookup_by_catalog_id() -> None:
    for spec in TOOL_BUTTONS:
        assert tool_button_spec(spec.id) is spec


def test_visible_buttons_drops_a_catalog_entry_the_catalog_lost(monkeypatch) -> None:
    # «Поведение при пустом каталоге»: an empty catalog leaves the mode buttons
    # and the panels toggle, never a button that answers nothing.
    empty = type(CATALOG)({})
    monkeypatch.setattr(buttons, "CATALOG", empty)
    remaining = visible_buttons(TOOL_BUTTON_STATE_EMPTY, None)
    assert remaining
    assert all(spec.source != SOURCE_CATALOG for spec in remaining)
    monkeypatch.setattr(buttons, "CATALOG", {"tool.caliper": CATALOG["tool.caliper"]})
    remaining = visible_buttons(TOOL_BUTTON_STATE_EMPTY, None)
    assert [spec.id for spec in remaining if spec.source == SOURCE_CATALOG] == ["tool.caliper"]
