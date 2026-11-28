"""The armed paired-tool chain state machine (``viewer.armed_next``).

Viewer-level behaviour is pinned in ``tests/unit/test_paired_tools.py``
through the widget; these tests pin the extracted pure machine itself: the
tuple shapes the status line and tests read, the frame gate (item 13), the
still-image escape, the other-clip release and the hint phase.
"""

from __future__ import annotations

from echo_personal_tool.presentation.viewer.armed_next import ArmedNextChain

CALIPER_STEP = ("caliper", "МЖП")
CONTOUR_STEP = ("contour", "LV", "A4C", "ES", False)


def test_a_fresh_chain_is_idle_and_never_gates() -> None:
    chain = ArmedNextChain()
    assert chain.pending() is None
    assert chain.kind() is None
    assert chain.hint_phase() == ""
    assert chain.waits_for_another_frame(current_frame=5, current_uid="uid-a") is False


def test_arm_caliper_keeps_the_historical_tuple_shape() -> None:
    chain = ArmedNextChain()
    chain.arm(CALIPER_STEP, current_frame=3, current_uid="uid-a")
    assert chain.pending() == ("caliper", "МЖП")
    assert chain.kind() == "caliper"
    assert chain.hint_phase() == ""


def test_arm_contour_keeps_the_historical_tuple_shape() -> None:
    chain = ArmedNextChain()
    chain.arm(CONTOUR_STEP, current_frame=3, current_uid="uid-a")
    assert chain.pending() == ("contour", "LV", "A4C", "ES", False)
    assert chain.kind() == "contour"
    assert chain.hint_phase() == "ES"


def test_the_gate_holds_while_the_operator_stands_on_the_arming_frame() -> None:
    chain = ArmedNextChain()
    chain.arm(CONTOUR_STEP, current_frame=3, current_uid="uid-a")
    assert chain.waits_for_another_frame(current_frame=3, current_uid="uid-a") is True


def test_scrolling_the_cine_releases_the_gate_and_keeps_the_chain() -> None:
    chain = ArmedNextChain()
    chain.arm(CONTOUR_STEP, current_frame=3, current_uid="uid-a")
    assert chain.waits_for_another_frame(current_frame=7, current_uid="uid-a") is False
    assert chain.pending() == CONTOUR_STEP


def test_a_still_image_arming_never_gates() -> None:
    chain = ArmedNextChain()
    chain.arm(CALIPER_STEP, current_frame=None, current_uid="uid-a")
    assert chain.waits_for_another_frame(current_frame=None, current_uid="uid-a") is False
    assert chain.waits_for_another_frame(current_frame=0, current_uid="uid-a") is False


def test_another_clip_releases_the_gate() -> None:
    chain = ArmedNextChain()
    chain.arm(CONTOUR_STEP, current_frame=3, current_uid="uid-a")
    assert chain.waits_for_another_frame(current_frame=3, current_uid="uid-b") is False


def test_clear_forgets_the_step_and_the_origin() -> None:
    chain = ArmedNextChain()
    chain.arm(CONTOUR_STEP, current_frame=3, current_uid="uid-a")
    chain.clear()
    assert chain.pending() is None
    assert chain.kind() is None
    assert chain.hint_phase() == ""
    assert chain.waits_for_another_frame(current_frame=3, current_uid="uid-a") is False


def test_rearming_replaces_the_previous_step() -> None:
    chain = ArmedNextChain()
    chain.arm(CALIPER_STEP, current_frame=2, current_uid="uid-a")
    chain.arm(CONTOUR_STEP, current_frame=9, current_uid="uid-b")
    assert chain.pending() == CONTOUR_STEP
    # The new origin rules: the old arming frame must not gate anything.
    assert chain.waits_for_another_frame(current_frame=9, current_uid="uid-b") is True
    assert chain.waits_for_another_frame(current_frame=2, current_uid="uid-a") is False
