"""Tests for S2-04 measurement undo/redo.

Covers:
- delete → undo → redo round-trip for contours and linear measurements
- bounded stack eviction
- clear on close (tab life)
- no new silent pass paths
"""

from __future__ import annotations

import pytest

from echo_personal_tool.application.measurement_undo_redo import (
    UndoEntry,
    UndoRedoManager,
)
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement

# ── helpers ──────────────────────────────────────────────────────────


def _make_contour(*, points=((1.0, 2.0), (3.0, 4.0)), view="A4C", frame_index=0, phase="ED") -> Contour:
    return Contour(
        phase=phase,
        view=view,
        chamber="LV",
        points=list(points),
        source="manual",
        frame_index=frame_index,
        review_pending=False,
    )


def _make_measurement(
    *, label="LVEDD", pixel_length=10.0, millimeter_length=25.0, frame_index=0, sop_instance_uid="1.2.3"
) -> LinearMeasurement:
    return LinearMeasurement(
        label=label,
        pixel_length=pixel_length,
        millimeter_length=millimeter_length,
        frame_index=frame_index,
        sop_instance_uid=sop_instance_uid,
    )


# ── UndoRedoManager unit tests ──────────────────────────────────────


def test_undo_redo_round_trip_contour() -> None:
    mgr = UndoRedoManager()
    assert not mgr.can_undo
    assert not mgr.can_redo

    contour = _make_contour()
    mgr.push(UndoEntry(kind="contour", payload={"contour": contour, "index": 0}))
    assert mgr.can_undo
    assert not mgr.can_redo

    entry = mgr.undo()
    assert entry is not None
    assert entry.kind == "contour"
    assert entry.payload["contour"] is contour
    assert mgr.can_redo
    assert not mgr.can_undo

    entry = mgr.redo()
    assert entry is not None
    assert entry.kind == "contour"
    assert not mgr.can_redo
    assert mgr.can_undo  # entry is back on the undo stack


def test_undo_redo_round_trip_linear_measurement() -> None:
    mgr = UndoRedoManager()
    measurement = _make_measurement()
    key = ("1.2.3", 0)
    mgr.push(UndoEntry(kind="linear_measurement", payload={"key": key, "measurement": measurement}))
    assert mgr.can_undo

    entry = mgr.undo()
    assert entry is not None
    assert entry.kind == "linear_measurement"
    assert entry.payload["key"] == key
    assert entry.payload["measurement"] is measurement
    assert mgr.can_redo

    entry = mgr.redo()
    assert entry is not None
    assert not mgr.can_redo
    assert mgr.can_undo


def test_undo_clears_redo_on_new_push() -> None:
    mgr = UndoRedoManager()
    mgr.push(UndoEntry(kind="contour", payload={"contour": _make_contour(), "index": 0}))
    mgr.undo()  # moves entry to redo stack
    assert mgr.can_redo

    mgr.push(UndoEntry(kind="contour", payload={"contour": _make_contour(), "index": 1}))
    assert not mgr.can_redo  # new push clears redo stack


def test_stack_bounded_eviction() -> None:
    mgr = UndoRedoManager(max_entries=3)
    for i in range(5):
        mgr.push(UndoEntry(kind="contour", payload={"contour": _make_contour(frame_index=i), "index": i}))
    assert mgr.size == 3  # oldest evicted

    # Undo should return the most recent (frame_index=4), not the oldest
    entry = mgr.undo()
    assert entry is not None
    assert entry.payload["contour"].frame_index == 4


def test_clear_empties_stacks() -> None:
    mgr = UndoRedoManager()
    mgr.push(UndoEntry(kind="contour", payload={"contour": _make_contour(), "index": 0}))
    mgr.undo()
    assert mgr.can_undo or mgr.can_redo

    mgr.clear()
    assert not mgr.can_undo
    assert not mgr.can_redo
    assert mgr.size == 0


def test_undo_empty_returns_none() -> None:
    mgr = UndoRedoManager()
    assert mgr.undo() is None
    assert mgr.redo() is None


def test_max_entries_validation() -> None:
    with pytest.raises(ValueError):
        UndoRedoManager(max_entries=0)


# ── Integration: undo/redo restores state in viewer ─────────────────
# These require PySide6 (gui marker; skipped with -m 'not gui').


@pytest.mark.gui
class TestViewerUndoRedo:
    def test_contour_delete_undo_redo(self, tmp_path, monkeypatch) -> None:
        """Delete contour → undo restores it → redo removes it again."""
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        viewer = ViewerWidget()

        contour = _make_contour(frame_index=0, view="A4C")
        viewer._stored_contours = [contour]
        assert len(viewer._stored_contours) == 1

        # Delete
        assert viewer.delete_contour_for_current_phase(view="A4C") is True
        assert len(viewer._stored_contours) == 0
        assert viewer.can_undo()
        assert not viewer.can_redo()

        # Undo
        assert viewer.undo() is True
        assert len(viewer._stored_contours) == 1
        assert viewer.can_redo()
        assert not viewer.can_undo()

        # Redo
        assert viewer.redo() is True
        assert len(viewer._stored_contours) == 0
        assert not viewer.can_redo()
        assert viewer.can_undo()

    def test_linear_measurement_delete_undo_redo(self, tmp_path, monkeypatch) -> None:
        """Delete caliper → undo restores it → redo removes it again."""
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        viewer = ViewerWidget()
        measurement = _make_measurement()
        key = ("1.2.3", 0)
        viewer._stored_linear_measurements[key] = measurement
        assert len(viewer._stored_linear_measurements) == 1

        # Delete
        viewer._selected_caliper_key = key
        assert viewer._delete_selected_caliper() is True
        assert len(viewer._stored_linear_measurements) == 0
        assert viewer.can_undo()

        # Undo
        assert viewer.undo() is True
        assert key in viewer._stored_linear_measurements
        assert viewer._stored_linear_measurements[key] is measurement
        assert viewer.can_redo()

        # Redo
        assert viewer.redo() is True
        assert key not in viewer._stored_linear_measurements
        assert not viewer.can_redo()
        assert viewer.can_undo()

    def test_clear_undo_redo_on_close(self, tmp_path, monkeypatch) -> None:
        """Undo/redo stack is cleared on viewer dispose (tab close)."""
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        viewer = ViewerWidget()
        contour = _make_contour()
        viewer._stored_contours = [contour]
        viewer.delete_contour_for_current_phase(view="A4C")
        assert viewer.can_undo()

        viewer.clear_undo_redo()
        assert not viewer.can_undo()
        assert not viewer.can_redo()

    def test_undo_no_op_when_empty(self, tmp_path, monkeypatch) -> None:
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        viewer = ViewerWidget()
        assert viewer._caliper_drag_active is False
        assert viewer.undo() is False
        assert viewer.redo() is False
        assert not viewer.can_undo()
        assert not viewer.can_redo()
