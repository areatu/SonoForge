"""Non-modal research IMT editor: two source-pixel overlays on the main viewer.

No clinical caliper/report mutation. Only explicit Save writes structured data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from math import ceil, floor
from typing import Any, cast

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
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
from echo_personal_tool.presentation.dark_theme import get_theme_tokens


class ImtEditor(QDialog):
    """Main-image wall selection, editable boundaries and explicit acceptance."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("imt.open"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.host = window
        self.review: ImtReview | None = None
        self.overlays: list[Any] = []
        self.wall_roi: pg.RectROI | None = None
        self.selection_armed = False
        self.drag_origin: QPointF | None = None
        self.selection_source: ImtSource | None = None
        self.selection_frame: tuple[object, ...] | None = None
        self.scene = self.host._viewer.overlay_view.scene()
        self.scene.installEventFilter(self)
        self.setModal(False)
        layout = QVBoxLayout(self)
        warning = QLabel(tr("imt.warning"))
        warning.setWordWrap(True)
        layout.addWidget(warning)
        select = QPushButton(tr("imt.select"))
        select.clicked.connect(lambda: self.run(self.start_selection))
        layout.addWidget(select)
        form = QFormLayout()
        self.side = QComboBox()
        self.side.addItems(["R", "L"])
        form.addRow(tr("imt.side"), self.side)
        layout.addLayout(form)
        advanced = QGroupBox(tr("imt.advanced"))
        advanced.setCheckable(True)
        advanced.setChecked(False)
        advanced_form = QFormLayout(advanced)
        self.fields = {}
        for key, placeholder in (
            ("roi", "x0,y0,x1,y1"),
            ("guides", "LI-left,LI-right,MA-left,MA-right"),
            ("policy", "min-mm,max-mm,coverage,contrast"),
        ):
            field = QLineEdit()
            field.setPlaceholderText(placeholder)
            self.fields[key] = field
            advanced_form.addRow(tr(f"imt.{key}"), field)
            label = advanced_form.labelForField(field)
            field.setVisible(False)
            label.setVisible(False)
            advanced.toggled.connect(field.setVisible)
            advanced.toggled.connect(label.setVisible)
        self.fields["guides"].setPlaceholderText(tr("imt.auto_guides"))
        self.fields["policy"].setText("0.2,2.0,0.7,0.03")
        layout.addWidget(advanced)
        metrics = QHBoxLayout()
        self.metrics: dict[str, QLabel] = {}
        for key in ("minimum", "mean", "maximum"):
            label = QLabel(tr(f"imt.{key}") + ": —")
            label.setToolTip(tr("imt.legend"))
            metrics.addWidget(label)
            self.metrics[key] = label
        layout.addLayout(metrics)
        legend = QLabel(tr("imt.legend"))
        legend.setWordWrap(True)
        layout.addWidget(legend)
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
        # State changes must revoke the lease synchronously: polling alone can
        # miss frame/calibration A→B→A between timer ticks.
        self.host._controller.state_manager.state_changed.connect(self.context_changed)
        self.side.currentTextChanged.connect(self.context_changed)
        self.fields["roi"].textChanged.connect(self.context_changed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_context)
        self.timer.start(100)
        self.finished.connect(self.cleanup)

    def cleanup(self, _result: int = 0) -> None:
        self.timer.stop()
        self.scene.removeEventFilter(self)
        self.clear_selection()
        self.clear_overlays()

    def clear_selection(self) -> None:
        if self.wall_roi is not None:
            self.host._viewer.overlay_view.removeItem(self.wall_roi)
        self.wall_roi = None
        self.selection_source = None
        self.selection_frame = None
        self.selection_armed = False
        self.drag_origin = None

    def start_selection(self) -> None:
        self.state()  # never draw on a playing, decoding or read-only frame
        self.clear_selection()
        self.clear_overlays()
        if self.review is not None:
            self.review.invalidate()
            self.summary()
        self.fields["roi"].clear()
        self.fields["guides"].clear()
        self.selection_frame = self.frame_context()
        self.selection_armed = True
        self.status.setText(tr("imt.select_hint"))

    def frame_context(self) -> tuple[object, ...]:
        state = self.state()
        assert state.instance is not None
        return (
            state.instance.sop_instance_uid,
            state.instance.path,
            state.current_frame_index,
            self.host._viewer.get_viewer_context().generation,
            state.manual_calibration,
            state.effective_calibration,
            state.instance.calibrations,
        )

    def eventFilter(self, watched: Any, event: Any) -> bool:
        if watched is not self.scene or not self.selection_armed:
            return False
        self.check_context()
        if not self.selection_armed:
            return False
        kind = event.type()
        if kind == QEvent.Type.GraphicsSceneMousePress:
            if event.button() == Qt.MouseButton.RightButton:
                self.clear_selection()
                return True
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            view = self.host._viewer.overlay_view
            if not view.sceneBoundingRect().contains(event.scenePos()):
                return False
            self.drag_origin = view.mapSceneToView(event.scenePos())
            return True
        if kind in (QEvent.Type.GraphicsSceneMouseMove, QEvent.Type.GraphicsSceneMouseRelease):
            origin = self.drag_origin
            if origin is None:
                return False
            point = self.host._viewer.overlay_view.mapSceneToView(event.scenePos())
            self.run(lambda: self.update_rectangle(origin, point))
            if kind == QEvent.Type.GraphicsSceneMouseRelease:
                self.selection_armed = False
                self.drag_origin = None
                self.run(self.rectangle_finished)
            return True
        return False

    def update_rectangle(self, first: QPointF, last: QPointF) -> None:
        """Scene/view transforms handle zoom and pan; store only source pixels."""
        height, width = self.pixels().shape[:2]
        x0 = max(0, min(width, floor(min(first.x(), last.x()))))
        y0 = max(0, min(height, floor(min(first.y(), last.y()))))
        x1 = max(0, min(width, ceil(max(first.x(), last.x()))))
        y1 = max(0, min(height, ceil(max(first.y(), last.y()))))
        if self.wall_roi is None:
            self.wall_roi = pg.RectROI((x0, y0), (x1 - x0, y1 - y0), pen=pg.mkPen("c", width=2))
            self.wall_roi.setZValue(90)
            self.host._viewer.overlay_view.addItem(self.wall_roi)
        else:
            self.wall_roi.setPos((x0, y0))
            self.wall_roi.setSize((x1 - x0, y1 - y0))
        self.fields["roi"].setText(f"{x0},{y0},{x1},{y1}")

    def rectangle_finished(self) -> None:
        if self.wall_roi is None:
            return
        # Invalidate before setting coordinates, but do not let the context
        # guard remove the rectangle during an intentional ROI edit.
        self.selection_source = None
        pos, size = self.wall_roi.pos(), self.wall_roi.size()
        self.fields["roi"].setText(
            f"{floor(pos.x())},{floor(pos.y())},{ceil(pos.x() + size.x())},{ceil(pos.y() + size.y())}"
        )
        self.selection_source = self.source()
        if not self.wall_roi.property("imt_connected"):
            self.wall_roi.sigRegionChangeStarted.connect(self.rectangle_edit_started)
            self.wall_roi.sigRegionChangeFinished.connect(self.rectangle_changed)
            self.wall_roi.setProperty("imt_connected", True)
        self.propose()

    def rectangle_edit_started(self) -> None:
        self.selection_source = None
        if self.review is not None:
            self.review.invalidate()
            self.clear_overlays()
            self.summary()

    def rectangle_changed(self) -> None:
        self.run(self.rectangle_finished)

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
        # A failed new search must not leave the previous result actionable.
        if self.review is not None:
            self.review.invalidate()
            self.clear_overlays()
            self.summary()
        source = self.source()
        values = [float(v) for v in self.fields["policy"].text().split(",")]
        if len(values) != 4:
            raise ImtRefusal("four_policy_values_required")
        policy = ImtPolicy(values[0], values[1], values[2], values[3])
        text = self.fields["guides"].text().strip()
        guides = [float(v) for v in text.split(",")] if text else []
        if guides and len(guides) != 4:
            raise ImtRefusal("four_guides_required")
        draft = propose_imt(
            self.pixels(),
            source,
            policy,
            lumen_y=(guides[0], guides[1]) if guides else None,
            adventitia_y=(guides[2], guides[3]) if guides else None,
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
        tokens = get_theme_tokens()
        for key, value in (("minimum", d.min_mm), ("mean", d.mean_mm), ("maximum", d.max_mm)):
            label = self.metrics[key]
            label.setText(tr(f"imt.{key}") + f": {value:.3f} " + tr("imt.mm"))
            role = "state.ok" if value <= 0.9 else "state.warn" if value < 1.5 else "state.err"
            color = tokens[role if self.review.live else "text.2"]
            label.setStyleSheet(f"color: {color}; font-weight: bold")
        self.status.setText(
            tr(
                "imt.summary",
                decision=decision,
                minimum=f"{d.min_mm:.3f}",
                mean=f"{d.mean_mm:.3f}",
                maximum=f"{d.max_mm:.3f}",
                sd=f"{d.sd_mm:.3f}",
                coverage=f"{d.coverage:.1%}",
                length=f"{d.sampled_length_mm:.2f}",
                revision=d.revision,
            )
        )

    @Slot(object)
    def context_changed(self, _value: object) -> None:
        self.check_context()

    def check_context(self) -> None:
        if self.selection_frame is not None:
            try:
                same_frame = self.frame_context() == self.selection_frame
            except (ImtRefusal, ValueError, TypeError):
                same_frame = False
            if not same_frame:
                self.clear_selection()
        if self.selection_source is not None:
            try:
                same = self.source() == self.selection_source
            except (ImtRefusal, ValueError, TypeError):
                same = False
            if not same:
                self.clear_selection()
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
    editor.run(editor.start_selection)
