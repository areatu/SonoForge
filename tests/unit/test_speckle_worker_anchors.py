"""Unit tests for one-sided manual ED/ES anchor resolution (Phase 2)."""

from __future__ import annotations

import pytest

from echo_personal_tool.application.workers.speckle_worker import _resolve_partial_manual_anchors

pytestmark = pytest.mark.gui


def test_pure_auto_keeps_mapping_pair() -> None:
    ed, es, source = _resolve_partial_manual_anchors(
        manual_ed=None,
        manual_es=None,
        auto_ed=4,
        auto_es=19,
        n_frames=30,
    )
    assert (ed, es) == (4, 19)
    assert source is None


def test_manual_ed_only_pins_ed() -> None:
    ed, es, source = _resolve_partial_manual_anchors(
        manual_ed=7,
        manual_es=None,
        auto_ed=2,  # ECG would pick a different ED — the pin must win
        auto_es=15,
        n_frames=30,
    )
    assert ed == 7
    assert source == "manual_ed+auto"
    assert 7 < es < 30


def test_manual_es_only_pins_es() -> None:
    ed, es, source = _resolve_partial_manual_anchors(
        manual_ed=None,
        manual_es=22,
        auto_ed=6,
        auto_es=25,
        n_frames=30,
    )
    assert es == 22
    assert source == "manual_es+auto"
    assert 0 <= ed < 22


def test_pinned_ed_wins_when_auto_es_equals_it() -> None:
    ed, es, source = _resolve_partial_manual_anchors(
        manual_ed=10,
        manual_es=None,
        auto_ed=10,
        auto_es=10,
        n_frames=40,
    )
    assert ed == 10
    assert source == "manual_ed+auto"
    assert es > ed


def test_pinned_es_repositions_auto_ed_after_it() -> None:
    ed, es, source = _resolve_partial_manual_anchors(
        manual_ed=None,
        manual_es=8,
        auto_ed=20,  # auto ED is after the pinned ES — must move before it
        auto_es=8,
        n_frames=40,
    )
    assert es == 8
    assert source == "manual_es+auto"
    assert 0 <= ed < es


def test_single_frame_returns_zeros() -> None:
    ed, es, source = _resolve_partial_manual_anchors(
        manual_ed=0,
        manual_es=0,
        auto_ed=0,
        auto_es=0,
        n_frames=1,
    )
    assert (ed, es) == (0, 0)
    assert source is None
