"""Widget tests for AutoEfResultDialog and EditableContourCanvas."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from echo_personal_tool.domain.models.result_provenance import QCStatus
from echo_personal_tool.domain.services.auto_ef_pipeline import (
    AutoEfClipCandidate,
    AutoEfPipelineResult,
    run_auto_ef_pipeline,
)
from echo_personal_tool.presentation.auto_ef_dialog import AutoEfResultDialog


class _DomeSeg:
    def is_available(self) -> bool:
        return True

    def segment(self, frame: np.ndarray, **_kwargs: Any) -> np.ndarray:
        return (frame > 127).astype(np.uint8)


def _sample_biplane_result() -> AutoEfPipelineResult:
    ed = np.zeros((160, 160), dtype=np.uint8)
    es = np.zeros((160, 160), dtype=np.uint8)
    cv2.circle(ed, (80, 92), 40, 255, -1)
    cv2.circle(es, (80, 92), 25, 255, -1)
    c4 = AutoEfClipCandidate("u.a4c", [ed, es], pixel_spacing_mm=(0.5, 0.5), view_override="A4C")
    c2 = AutoEfClipCandidate("u.a2c", [ed, es], pixel_spacing_mm=(0.5, 0.5), view_override="A2C")
    return run_auto_ef_pipeline([c4, c2], study_uid="study.dlg", a4c_segmenter=_DomeSeg(), bsa_m2=1.8)


def test_auto_ef_dialog_renders_switches_slots_edits_node_and_resets(qtbot: Any) -> None:
    initial = _sample_biplane_result()
    dlg = AutoEfResultDialog(initial, bsa_m2=1.8)
    qtbot.addWidget(dlg)
    dlg.show()

    assert initial.lvef_percent is not None
    initial_ef = initial.lvef_percent
    initial_rev = initial.provenance.revision

    dlg.select_slot("A2C", "es")
    dlg.select_slot("A4C", "ed")
    dlg.canvas.repaint()

    # Drag a lateral node outward on A4C ED and verify live LVEF recalculation
    ed_contour = next(c for c in dlg.current_result.contours if c.view == "A4C" and c.phase == "ed")
    mid_idx = len(ed_contour.points) // 2
    mx, my = ed_contour.points[mid_idx]
    dlg.canvas.move_node(mid_idx, (mx, max(2.0, my - 18.0)))

    edited_res = dlg.current_result
    assert edited_res.lvef_percent is not None
    assert edited_res.lvef_percent != initial_ef
    assert edited_res.provenance.revision == initial_rev + 1
    ed_after = next(c for c in edited_res.contours if c.view == "A4C" and c.phase == "ed")
    assert ed_after.source == "ai_edited"

    # Reset restores the original AI contour and revision
    dlg.reset_to_initial()
    assert dlg.current_result.provenance.revision == initial_rev
    assert dlg.current_result.lvef_percent == initial_ef

    # Mouse press/move/release on node 0 exercises interactive handle hit-testing
    w_pt = dlg.canvas._img_to_widget(ed_contour.points[0])
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        w_pt,
        w_pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(w_pt.x() - 6.0, w_pt.y()),
        QPointF(w_pt.x() - 6.0, w_pt.y()),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(w_pt.x() - 6.0, w_pt.y()),
        QPointF(w_pt.x() - 6.0, w_pt.y()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    dlg.canvas.mousePressEvent(press)
    dlg.canvas.mouseMoveEvent(move)
    dlg.canvas.mouseReleaseEvent(release)
    assert dlg.current_result.provenance.revision == initial_rev + 1

    accepted_payloads: list[AutoEfPipelineResult] = []
    dlg.result_accepted.connect(accepted_payloads.append)
    dlg._on_accept_clicked()
    assert len(accepted_payloads) == 1
    assert accepted_payloads[0].provenance.qc.status == QCStatus.VALID
    assert all(not c.review_pending for c in accepted_payloads[0].contours)
