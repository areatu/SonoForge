"""Non-modal research IMT editor: two source-pixel overlays on the main viewer.

No clinical caliper/report mutation. Only explicit Save writes structured data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any, cast

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from echo_personal_tool.application.composition import services_of
from echo_personal_tool.application.imt import propose_imt
from echo_personal_tool.application.imt_review import ImtReview
from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.imt import ImtPolicy, ImtRefusal, ImtSource
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.services.imt_validation import imt_key


class ImtEditor(QDialog):
    """Operator-selected ROI/guides and explicit research policy, never defaults."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("imt.open"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.host = window
        self.review: ImtReview | None = None
        self.overlays: list[Any] = []
        self.setModal(False)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("imt.warning")))
        form = QFormLayout()
        self.side = QComboBox()
        self.side.addItems(["R", "L"])
        form.addRow(tr("imt.side"), self.side)
        self.fields = {}
        for key, placeholder in (
            ("roi", "x0,y0,x1,y1"),
            ("guides", "LI-left,LI-right,MA-left,MA-right"),
            ("policy", "min-mm,max-mm,coverage,contrast"),
        ):
            field = QLineEdit()
            field.setPlaceholderText(placeholder)
            self.fields[key] = field
            form.addRow(tr(f"imt.{key}"), field)
        layout.addLayout(form)
        self.status = QLabel(tr("imt.unreviewed"))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        for key, callback in (
            ("propose", self.propose),
            ("load", self.load),
            ("revalidate", self.revalidate),
            ("confirm", self.confirm),
            ("save", self.save),
        ):
            button = QPushButton(tr(f"imt.{key}"))
            button.clicked.connect(lambda _checked=False, fn=callback: self.run(fn))
            layout.addWidget(button)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_context)
        self.timer.start(100)
        self.finished.connect(lambda _result: self.clear_overlays())

    def run(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except (ImtRefusal, ValueError, TypeError) as exc:
            self.status.setText(f"{tr('imt.refused')}: {exc}")

    def state(self) -> ViewerState:
        if self.host._comparison.tool_blocked("imt"):
            raise ImtRefusal("readonly_pane")
        state = cast(ViewerState, self.host._controller.state_manager.snapshot)
        if state.instance is None or state.is_playing or state.decode_in_progress:
            raise ImtRefusal("paused_frame_required")
        return state

    def source(self) -> ImtSource:
        state = self.state()
        assert state.instance is not None
        values = [int(v.strip()) for v in self.fields["roi"].text().split(",")]
        if len(values) != 4:
            raise ImtRefusal("four_roi_coordinates_required")
        roi = (values[0], values[1], values[2], values[3])
        calibration = state.calibration_for_geometry(bbox=roi).context
        if calibration is None:
            raise ImtRefusal("calibration_required")
        return ImtSource(
            study_uid=self.host._controller.resolve_study_uid(state.instance),
            instance_uid=state.instance.sop_instance_uid,
            generation=self.host._viewer.get_viewer_context().generation,
            frame_index=state.current_frame_index,
            frame_count=state.total_frames,
            side=self.side.currentText(),
            phase="operator_selected",
            calibration=calibration,
            roi=roi,
            clip_mode=state.instance.clip_mode,
        )

    def pixels(self) -> np.ndarray:
        state = self.state()
        assert state.instance is not None
        image = self.host._controller.frame_access.frame(state.instance.path, state.current_frame_index)
        if image is None:
            raise ImtRefusal("frame_not_resident")
        return cast(np.ndarray, image)

    def store(self) -> Any:
        services = services_of(self.host._controller)
        if services is None:
            raise ImtRefusal("services_unavailable")
        return services

    def propose(self) -> None:
        source = self.source()
        values = [float(v) for v in self.fields["policy"].text().split(",")]
        if len(values) != 4:
            raise ImtRefusal("four_policy_values_required")
        policy = ImtPolicy(values[0], values[1], values[2], values[3])
        guides = [float(v) for v in self.fields["guides"].text().split(",")]
        if len(guides) != 4:
            raise ImtRefusal("four_guides_required")
        draft = propose_imt(
            self.pixels(), source, policy, lumen_y=(guides[0], guides[1]), adventitia_y=(guides[2], guides[3])
        )
        prior = list(self.store().measurement_store.get(source.study_uid).imt_measurements)
        if self.review is not None:
            prior.append(self.review.draft)
        revisions = [item.revision for item in prior if imt_key(item) == imt_key(draft)]
        if revisions:
            draft = replace(draft, revision=max(revisions) + 1)
        self.review = ImtReview(draft, live=True)
        self.draw()

    def load(self) -> None:
        state = self.state()
        assert state.instance is not None
        uid = self.host._controller.resolve_study_uid(state.instance)
        candidates = [
            d
            for d in self.store().measurement_store.get(uid).imt_measurements
            if d.source.instance_uid == state.instance.sop_instance_uid
            and d.source.frame_index == state.current_frame_index
            and d.source.side == self.side.currentText()
        ]
        if not candidates:
            raise ImtRefusal("no_saved_record")
        self.review = ImtReview(candidates[-1])
        policy = self.review.draft.policy
        self.fields["policy"].setText(
            ",".join(
                str(v)
                for v in (
                    policy.min_thickness_mm,
                    policy.max_thickness_mm,
                    policy.min_coverage,
                    policy.min_edge_contrast,
                )
            )
        )
        self.review.invalidate()
        self.fields["roi"].setText(",".join(str(v) for v in self.review.draft.source.roi))
        self.draw()

    def revalidate(self) -> None:
        if self.review is None:
            raise ImtRefusal("draft_required")
        self.review.revalidate(self.source(), self.pixels())
        self.draw()

    def confirm(self) -> None:
        if self.review is None:
            raise ImtRefusal("draft_required")
        self.review.confirm(self.source())
        self.summary()

    def save(self) -> None:
        if self.review is None or not self.review.live or self.review.draft.source != self.source():
            raise ImtRefusal("review_required")
        draft = self.review.draft
        self.store().measurement_store.set_imt_measurement(draft.source.study_uid, draft)
        self.summary()

    def clear_overlays(self) -> None:
        for overlay in self.overlays:
            self.host._viewer.overlay_view.removeItem(overlay)
        self.overlays = []

    def draw(self) -> None:
        assert self.review is not None
        self.clear_overlays()
        for boundary, color in ((self.review.draft.lumen_intima, "c"), (self.review.draft.media_adventitia, "y")):
            overlay = pg.PolyLineROI(boundary, closed=False, movable=False, pen=pg.mkPen(color, width=2))
            overlay.setZValue(100)
            overlay.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
            overlay.sigRegionChangeStarted.connect(self.edit_started)
            overlay.sigRegionChangeFinished.connect(lambda _roi: self.run(self.edited))
            self.host._viewer.overlay_view.addItem(overlay)
            self.overlays.append(overlay)
        self.summary()

    def edit_started(self) -> None:
        if self.review is not None:
            # An in-progress drag must never retain operator acceptance.
            self.review.draft = replace(self.review.draft, confirmed=False)
            self.summary()

    def edited(self) -> None:
        if self.review is None or len(self.overlays) != 2:
            return
        boundaries = [
            tuple((float(p.x()), float(p.y())) for _, p in roi.getLocalHandlePositions()) for roi in self.overlays
        ]
        try:
            self.review.edit(self.source(), self.pixels(), *boundaries)
        except (ImtRefusal, ValueError, TypeError):
            self.review.invalidate()
            self.draw()
            raise
        self.summary()

    def summary(self) -> None:
        assert self.review is not None
        d = self.review.draft
        decision = tr("imt.confirmed") if d.confirmed and self.review.live else tr("imt.unreviewed")
        self.status.setText(
            tr(
                "imt.summary",
                decision=decision,
                mean=f"{d.mean_mm:.3f}",
                maximum=f"{d.max_mm:.3f}",
                sd=f"{d.sd_mm:.3f}",
                coverage=f"{d.coverage:.1%}",
                length=f"{d.sampled_length_mm:.2f}",
                revision=d.revision,
            )
        )

    def check_context(self) -> None:
        if self.review is None:
            return
        try:
            current = self.source()
            if current == self.review.draft.source:
                return
        except (ImtRefusal, ValueError, TypeError):
            pass
        self.review.invalidate()
        self.clear_overlays()
        self.summary()


def show_imt_editor(window: Any) -> None:
    """Open one modeless editor; the previous-study pane remains read-only."""
    if window._comparison.tool_blocked("imt"):
        return
    existing = window.findChild(ImtEditor)
    if existing is not None:
        existing.raise_()
        return
    editor = ImtEditor(window)
    editor.show()
