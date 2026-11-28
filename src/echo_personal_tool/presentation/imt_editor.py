"""Non-modal research IMT editor: two source-pixel overlays on the main viewer.

Only explicit acceptance writes structured data and makes it available to the report.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from math import ceil, floor
from typing import Any, cast

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, QRect, QSignalBlocker, Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QLineEdit, QPushButton, QScrollArea, QWidget

from echo_personal_tool.application.composition import services_of
from echo_personal_tool.application.imt import propose_imt
from echo_personal_tool.application.imt_review import ImtReview
from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.calibration import CalibrationConfidence, CalibrationContext, select_calibration
from echo_personal_tool.domain.models.imt import ImtPolicy, ImtRefusal, ImtSource
from echo_personal_tool.domain.models.imt_region import Polygon
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.services.imt_validation import imt_key
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.imt_panel import build_imt_panel


class ImtEditor(QWidget):
    """Main-image wall selection, editable boundaries and explicit acceptance."""

    # Populated by the view builder; declared here for the typed controller API.
    side: QComboBox
    more: QCheckBox
    fields: dict[str, QLineEdit]
    metrics: dict[str, QLabel]
    status: QLabel
    calibration_status: QLabel
    use_dicom: QPushButton
    edit_boundaries: QCheckBox
    accept_button: QPushButton
    details: QScrollArea
    viewport: QWidget
    angle: QDoubleSpinBox

    def __init__(self, window: Any) -> None:
        viewport = window._viewer.overlay_view.scene().views()[0].viewport()
        super().__init__(viewport)
        self.viewport = viewport
        self.setObjectName("imtReviewOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setMaximumWidth(520)
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"#imtReviewOverlay {{ background: {tokens['surface.2']}; "
            f"border: 1px solid {tokens['line.1']}; border-radius: 6px; }}"
        )
        self.editing = False
        self.setWindowTitle(tr("imt.open"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.host = window
        self.review: ImtReview | None = None
        self.overlays: list[Any] = []
        self.roi_polygon: Polygon = ()
        self.wall_roi: pg.RectROI | None = None
        self.selection_armed = False
        self.drag_origin: QPointF | None = None
        self.selection_source: ImtSource | None = None
        self.selection_frame: tuple[object, ...] | None = None
        self.scene = self.host._viewer.overlay_view.scene()
        self.scene.installEventFilter(self)
        build_imt_panel(self)
        self.viewport.installEventFilter(self)
        self.refresh_calibration()
        # State changes must revoke the lease synchronously: polling alone can
        # miss frame/calibration A→B→A between timer ticks.
        self.host._controller.state_manager.state_changed.connect(self.context_changed)
        self.side.currentTextChanged.connect(self.context_changed)
        self.fields["roi"].textChanged.connect(self.context_changed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_context)
        self.timer.start(100)

    @property
    def panel_widget(self) -> QWidget:
        return self

    def closeEvent(self, event: QCloseEvent) -> None:
        self.cleanup()
        event.accept()

    def cleanup(self, _result: int = 0) -> None:
        self.timer.stop()
        self.scene.removeEventFilter(self)
        self.viewport.removeEventFilter(self)
        self.clear_selection()
        self.clear_overlays()

    def clear_selection(self) -> None:
        if self.wall_roi is not None:
            self.host._viewer.overlay_view.removeItem(self.wall_roi)
        self.wall_roi = None
        self.angle.setEnabled(False)
        self.selection_source = None
        self.selection_frame = None
        self.selection_armed = False
        self.drag_origin = None

    def reposition(self) -> None:
        """Anchor inside the viewer, not over the selected far-wall segment."""
        self.setFixedWidth(min(520, max(1, self.viewport.width() - 16)))
        self.setMaximumHeight(max(1, self.viewport.height() - 16))
        self.adjustSize()
        right = max(8, self.viewport.width() - self.width() - 8)
        bottom = max(8, self.viewport.height() - self.height() - 8)
        corners = [(8, bottom), (right, bottom), (8, 8), (right, 8)]
        if self.review is not None:
            x0, y0, x1, y1 = self.review.draft.source.roi
            view = self.host._viewer.overlay_view
            graphics = self.scene.views()[0]
            first = graphics.mapFromScene(view.mapViewToScene(QPointF(x0, y0)))
            last = graphics.mapFromScene(view.mapViewToScene(QPointF(x1, y1)))
            selected = QRect(first, last).normalized().adjusted(-8, -8, 8, 8)

            def overlap(corner: tuple[int, int]) -> int:
                intersection = QRect(*corner, self.width(), self.height()).intersected(selected)
                return intersection.width() * intersection.height()

            corners.sort(key=overlap)
        self.move(*corners[0])
        self.raise_()

    def reject(self) -> None:
        """Discard the pending review, never delete an earlier accepted record."""
        self.review = None
        self.close()

    def accept_result(self) -> None:
        """One explicit action: validate freshness, confirm, persist, then dismiss."""
        self.confirm()
        self.save()
        self.close()

    def start_selection(self) -> None:
        self.state()  # never draw on a playing, decoding or read-only frame
        self.clear_selection()
        self.clear_overlays()
        if self.review is not None:
            self.review.invalidate()
            self.summary()
        self.roi_polygon = ()
        with QSignalBlocker(self.angle):
            self.angle.setValue(0)
        self.fields["roi"].clear()
        self.fields["guides"].clear()
        self.accept_button.setEnabled(False)
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
        if watched is self.viewport and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            QTimer.singleShot(0, self.reposition)
            return False
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
            self.wall_roi.addRotateHandle((0.5, 0), (0.5, 0.5))
            self.wall_roi.setToolTip(tr("imt.rotate_hint"))
            self.angle.setEnabled(True)
            self.wall_roi.setZValue(90)
            self.host._viewer.overlay_view.addItem(self.wall_roi)
        else:
            self.wall_roi.setPos((x0, y0))
            self.wall_roi.setSize((x1 - x0, y1 - y0))
        self.fields["roi"].setText(f"{x0},{y0},{x1},{y1}")

    def rectangle_finished(self) -> None:
        if self.wall_roi is None:
            return
        # Invalidate even a programmatic rotation before resolving its new scale.
        self.rectangle_edit_started()
        # Do not let the guard remove the rectangle during an intentional edit.
        self.selection_source = None
        size = self.wall_roi.size()
        corners = [
            self.wall_roi.mapToParent(QPointF(x, y))
            for x, y in ((0, 0), (size.x(), 0), (size.x(), size.y()), (0, size.y()))
        ]
        angle = (self.wall_roi.angle() + 180) % 360 - 180
        self.roi_polygon = tuple((float(p.x()), float(p.y())) for p in corners) if abs(angle) > 1e-6 else ()
        with QSignalBlocker(self.angle):
            self.angle.setValue(angle)
        self.fields["roi"].setText(
            f"{floor(min(p.x() for p in corners))},{floor(min(p.y() for p in corners))},"
            f"{ceil(max(p.x() for p in corners))},{ceil(max(p.y() for p in corners))}"
        )
        if not self.wall_roi.property("imt_connected"):
            self.wall_roi.sigRegionChangeStarted.connect(self.rectangle_edit_started)
            self.wall_roi.sigRegionChangeFinished.connect(self.rectangle_changed)
            self.wall_roi.setProperty("imt_connected", True)
        self.selection_source = self.source()
        self.propose()

    def rotate_selection(self, angle: float) -> None:
        if self.wall_roi is None:
            return
        self.rectangle_edit_started()
        self.wall_roi.setAngle(angle, center=(0.5, 0.5))

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
            self.accept_button.setEnabled(False)
            self.status.setText(tr(refusal_message(str(exc))))
            self.status.setToolTip(str(exc))  # diagnostics, not the operator instruction
            self.refresh_calibration()
            self.reposition()

    def state(self) -> ViewerState:
        tabs = getattr(self.host, "_tabs", None)
        if getattr(getattr(tabs, "active", None), "report_finished", False):
            raise ImtRefusal("finished_report")
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
            raise ImtRefusal("calibration_scope_mismatch")
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
            roi_polygon=self.roi_polygon,
        )

    def selected_calibration(self) -> CalibrationContext | None:
        state = self.state()
        try:
            values = tuple(int(v.strip()) for v in self.fields["roi"].text().split(","))
            if len(values) == 4:
                return state.calibration_for_geometry(bbox=values).context
        except ValueError:
            pass
        return state.effective_calibration

    def refresh_calibration(self) -> None:
        try:
            state = self.state()
            context = self.selected_calibration()
        except ImtRefusal:
            self.calibration_status.setText(tr("imt.scale_required"))
            self.use_dicom.hide()
            return
        self.use_dicom.setVisible(state.manual_calibration is not None or state.manual_pixel_spacing is not None)
        available = self.dicom_calibration() is not None
        self.use_dicom.setEnabled(available)
        self.use_dicom.setToolTip(tr("imt.use_dicom_tip" if available else "imt.dicom_scale_unavailable"))
        if context is None:
            text = tr("imt.scale_required")
        elif not verified_scale(context):
            text = tr("imt.scale_assumed_short")
        else:
            row, col = context.spacing
            text = tr("imt.scale_ready", source=context.source, row=f"{row:.4g}", col=f"{col:.4g}")
        self.calibration_status.setText(text)
        self.calibration_status.setToolTip(
            tr("imt.scale_unverified") if context and not verified_scale(context) else text
        )

    def dicom_calibration(self) -> CalibrationContext | None:
        state = self.state()
        assert state.instance is not None
        try:
            values = tuple(int(v.strip()) for v in self.fields["roi"].text().split(","))
        except ValueError:
            return None
        if len(values) != 4:
            return None
        contexts = state.instance.calibrations or ((state.instance.calibration,) if state.instance.calibration else ())
        selection = select_calibration(contexts, frame_index=state.current_frame_index, bbox=values)
        context = selection.context
        return context if context is not None and verified_scale(context) else None

    def restore_dicom_scale(self) -> None:
        """Explicitly remove a manual override only if DICOM covers this ROI."""
        if self.dicom_calibration() is None:
            raise ImtRefusal("dicom_scale_unavailable")
        # Clearing an override invalidates earlier measurements through the
        # normal controller path. Never silently change or upgrade its trust.
        roi = self.fields["roi"].text()
        self.host._controller.clear_manual_calibration()
        self.fields["roi"].setText(roi)
        self.propose()

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
        self.clear_selection()
        self.review = ImtReview(candidates[-1])
        self.roi_polygon = self.review.draft.source.roi_polygon
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
        if self.editing:
            raise ImtRefusal("boundary_edit_in_progress")
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
        self.editing = False

    def draw(self) -> None:
        assert self.review is not None
        self.clear_overlays()
        color = get_theme_tokens()[imt_color_role(self.review.draft.mean_mm) if self.review.live else "text.2"]
        for boundary in (self.review.draft.lumen_intima, self.review.draft.media_adventitia):
            overlay = pg.PolyLineROI(boundary, closed=False, movable=False, pen=pg.mkPen(color, width=2))
            overlay.setZValue(100)
            overlay.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
            overlay.sigRegionChangeStarted.connect(self.edit_started)
            overlay.sigRegionChangeFinished.connect(lambda _roi: self.run(self.edited))
            self.host._viewer.overlay_view.addItem(overlay)
            self.overlays.append(overlay)
        self.set_boundary_editing(self.edit_boundaries.isChecked())
        self.summary()

    def set_boundary_editing(self, enabled: bool) -> None:
        for overlay in self.overlays:
            overlay.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if enabled else Qt.MouseButton.NoButton)
            # Keep the computed geometry intact, but do not obscure it with hundreds of nodes.
            handles = overlay.getHandles()
            step = max(1, len(handles) // 12)
            for index, handle in enumerate(handles):
                handle.setVisible(enabled and (index % step == 0 or index == len(handles) - 1))

    def edit_started(self) -> None:
        self.editing = True
        if self.review is not None:
            # An in-progress drag must never retain operator acceptance.
            self.review.draft = replace(self.review.draft, confirmed=False)
            self.summary()

    def edited(self) -> None:
        self.editing = False
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
            role = imt_color_role(value)
            color = tokens[role if self.review.live else "text.2"]
            label.setStyleSheet(f"color: {color}; font-weight: bold")
        self.accept_button.setEnabled(self.review.live and not self.editing)
        self.status.setText(tr("imt.review_hint") if self.review.live else tr("imt.stale_hint"))
        color = tokens[imt_color_role(d.mean_mm) if self.review.live else "text.2"]
        for overlay in self.overlays:
            overlay.setPen(pg.mkPen(color, width=2))
        self.refresh_calibration()
        self.reposition()
        self.status.setToolTip(
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
        self.refresh_calibration()
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
        if self.review.live or self.overlays:
            self.review.invalidate()
            self.clear_overlays()
            self.summary()


def verified_scale(context: CalibrationContext) -> bool:
    return (
        context.confidence in (CalibrationConfidence.MEASURED, CalibrationConfidence.DERIVED)
        and context.assumption is None
        and not context.assumed_isotropic
    )


def imt_color_role(value: float) -> str:
    return "state.ok" if value <= 0.9 else "state.warn" if value < 1.5 else "state.err"


def refusal_message(code: str) -> str:
    """Stable technical codes are details; the operator gets an actionable message."""
    if code in (
        "invalid_rotated_roi",
        "roi_angle_limit",
        "rotated_roi_outside_frame",
        "rotated_roi_auto_guides_required",
    ):
        return "imt.rotated_roi_refused"
    if code == "unverified_calibration":
        return "imt.scale_unverified"
    if code in ("calibration_required", "calibration_scope_mismatch", "numerically_unstable_scale"):
        return "imt.scale_required"
    if code == "dicom_scale_unavailable":
        return "imt.dicom_scale_unavailable"
    if code in (
        "paused_frame_required",
        "frame_not_resident",
        "bmode_required",
        "grayscale_frame_and_valid_roi_required",
    ):
        return "imt.frame_required"
    if code == "finished_report":
        return "imt.finished_report"
    if code == "readonly_pane":
        return "imt.readonly_pane"
    if code in ("stale_draft", "review_required", "draft_required", "boundary_edit_in_progress"):
        return "imt.stale_hint"
    if code in ("two_wall_edges_not_found", "insufficient_quality_coverage", "flat_roi", "no_continuous_boundary"):
        return "imt.search_failed"
    return "imt.invalid_input"


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
    editor.reposition()
    editor.run(editor.start_selection)
