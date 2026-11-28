"""Interactive Biplane Auto-EF review dialog with contour editing and live recalculation."""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.auto_ef_coordinator import (
    AutoEfCoordinator,
    apply_auto_ef_to_controller,
)
from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.application.ef_validation import load_auto_ef_validation_summary
from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.calculations.lvef_simpson import compute_simpson_lines
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.auto_ef_pipeline import (
    AutoEfPipelineResult,
    AutoEfViewSelection,
    recalculate_auto_ef,
)
from echo_personal_tool.domain.services.contour_geometry import apex_point
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

_SLOT_KEYS: tuple[tuple[str, str], ...] = (
    ("A4C", "ed"),
    ("A4C", "es"),
    ("A2C", "ed"),
    ("A2C", "es"),
)

logger = logging.getLogger(__name__)


def _fmt_validation_rate(value: object) -> str:
    """A sensitivity/specificity fraction as a percent, or «—» when undefined."""
    if not isinstance(value, (int, float)):
        return "—"
    return f"{float(value) * 100:.1f}%"


def _frame_to_pixmap(frame: np.ndarray | None) -> QPixmap | None:
    if frame is None or frame.size == 0:
        return None
    arr = np.asarray(frame)
    if arr.ndim == 3 and arr.shape[2] == 3:
        arr_u8 = np.ascontiguousarray(arr.astype(np.uint8))
        h, w, _ = arr_u8.shape
        qimg = QImage(arr_u8.data, w, h, w * 3, QImage.Format.Format_RGB888)
        return QPixmap.fromImage(qimg.copy())
    f32 = arr.astype(np.float32)
    lo, hi = float(f32.min()), float(f32.max())
    norm = ((f32 - lo) / (hi - lo) * 255.0).astype(np.uint8) if hi > lo else np.zeros_like(f32, dtype=np.uint8)
    contig = np.ascontiguousarray(norm)
    h, w = contig.shape[:2]
    qimg = QImage(contig.data, w, h, w, QImage.Format.Format_Grayscale8)
    return QPixmap.fromImage(qimg.copy())


class EditableContourCanvas(QWidget):
    """Frame viewer with draggable open-arc contour nodes and Simpson disks."""

    contour_edited = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = get_theme_tokens()
        self._pixmap: QPixmap | None = None
        self._frame_shape: tuple[int, int] = (1, 1)
        self._contour: Contour | None = None
        self._pixel_spacing: tuple[float, float] = (1.0, 1.0)
        self._drag_idx: int | None = None
        self.setMinimumSize(360, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def set_slot(
        self,
        frame: np.ndarray | None,
        contour: Contour | None,
        pixel_spacing: tuple[float, float] | None,
    ) -> None:
        self._pixmap = _frame_to_pixmap(frame)
        if frame is not None and frame.ndim >= 2:
            self._frame_shape = (int(frame.shape[0]), int(frame.shape[1]))
        elif self._pixmap is not None and not self._pixmap.isNull():
            self._frame_shape = (self._pixmap.height(), self._pixmap.width())
        self._contour = contour
        self._pixel_spacing = pixel_spacing if pixel_spacing is not None else (1.0, 1.0)
        self._drag_idx = None
        self.update()

    def _viewport_transform(self) -> tuple[float, float, float]:
        fh, fw = max(1, self._frame_shape[0]), max(1, self._frame_shape[1])
        scale = min(self.width() / fw, self.height() / fh)
        ox = (self.width() - fw * scale) / 2.0
        oy = (self.height() - fh * scale) / 2.0
        return scale, ox, oy

    def _img_to_widget(self, pt: tuple[float, float]) -> QPointF:
        scale, ox, oy = self._viewport_transform()
        return QPointF(ox + pt[0] * scale, oy + pt[1] * scale)

    def _widget_to_img(self, pos: QPointF) -> tuple[float, float]:
        scale, ox, oy = self._viewport_transform()
        fh, fw = self._frame_shape
        ix = float(np.clip((pos.x() - ox) / max(scale, 1e-6), 0.0, max(fw - 1, 1)))
        iy = float(np.clip((pos.y() - oy) / max(scale, 1e-6), 0.0, max(fh - 1, 1)))
        return ix, iy

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._contour is not None:
            pos = event.position()
            best_i, best_d = None, 14.0
            for idx, pt in enumerate(self._contour.points):
                wp = self._img_to_widget(pt)
                dist = math.hypot(pos.x() - wp.x(), pos.y() - wp.y())
                if dist <= best_d:
                    best_d = dist
                    best_i = idx
            if best_i is not None:
                self._drag_idx = best_i
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_idx is not None and self._contour is not None:
            new_pt = self._widget_to_img(event.position())
            self.move_node(self._drag_idx, new_pt)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_idx is not None:
            self._drag_idx = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def move_node(self, node_index: int, new_xy: tuple[float, float]) -> None:
        """Programmatic or mouse-driven node update with live recalculation signal."""
        if self._contour is None or not 0 <= node_index < len(self._contour.points):
            return
        pts = list(self._contour.points)
        pts[node_index] = (float(new_xy[0]), float(new_xy[1]))
        annulus = self._contour.mitral_annulus
        if annulus is not None:
            if node_index == 0:
                annulus = (pts[0], annulus[1])
            elif node_index == len(pts) - 1:
                annulus = (annulus[0], pts[-1])
        new_apex = apex_point(pts, annulus) if (annulus is not None and len(pts) >= 3) else self._contour.apex_landmark
        self._contour = replace(
            self._contour,
            points=pts,
            mitral_annulus=annulus,
            apex_landmark=new_apex,
            source="ai_edited",
            review_pending=False,
            num_nodes=len(pts),
        )
        self.update()
        self.contour_edited.emit(self._contour)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tokens = self._tokens
        painter.fillRect(self.rect(), QColor(tokens["surface.0"]))
        if self._pixmap is not None and not self._pixmap.isNull():
            scale, ox, oy = self._viewport_transform()
            tw = max(1, int(round(self._frame_shape[1] * scale)))
            th = max(1, int(round(self._frame_shape[0] * scale)))
            scaled = self._pixmap.scaled(
                tw,
                th,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(int(round(ox)), int(round(oy)), scaled)
        if self._contour is not None and len(self._contour.points) >= 3:
            self._draw_contour(painter)

    def _draw_contour(self, painter: QPainter) -> None:
        assert self._contour is not None
        tokens = self._tokens
        lines = compute_simpson_lines(replace(self._contour, review_pending=False), self._pixel_spacing)
        if lines is not None:
            disk_pen = QPen(QColor(tokens["state.info"]), 1.0, Qt.PenStyle.DashLine)
            painter.setPen(disk_pen)
            for p1, p2 in lines.disk_lines:
                painter.drawLine(self._img_to_widget(p1), self._img_to_widget(p2))
            axis_pen = QPen(QColor(tokens["state.warn"]), 1.4, Qt.PenStyle.DotLine)
            painter.setPen(axis_pen)
            painter.drawLine(self._img_to_widget(lines.central_line[0]), self._img_to_widget(lines.central_line[1]))

        arc_color = QColor(tokens["state.ok"] if not self._contour.review_pending else tokens["accent"])
        painter.setPen(QPen(arc_color, 2.0))
        pts = self._contour.points
        for i in range(len(pts) - 1):
            painter.drawLine(self._img_to_widget(pts[i]), self._img_to_widget(pts[i + 1]))

        if self._contour.mitral_annulus is not None:
            ma_pen = QPen(QColor(tokens["state.warn"]), 2.0)
            painter.setPen(ma_pen)
            s_pt, l_pt = self._contour.mitral_annulus
            painter.drawLine(self._img_to_widget(s_pt), self._img_to_widget(l_pt))

        painter.setBrush(QColor(tokens["surface.0"]))
        for idx, pt in enumerate(pts):
            is_end = idx in (0, len(pts) - 1)
            radius = 4.5 if is_end else 3.0
            painter.setPen(QPen(QColor(tokens["state.warn"] if is_end else tokens["accent.text"]), 1.5))
            painter.drawEllipse(self._img_to_widget(pt), radius, radius)


def _fmt_num(value: float | None, digits: int = 1) -> str:
    return f"{value:.{digits}f}" if value is not None else "—"


class AutoEfResultDialog(QDialog):
    """Interactive result card for reviewing, editing, and saving Biplane Auto-EF."""

    result_accepted = Signal(object)

    def __init__(
        self,
        result: AutoEfPipelineResult,
        *,
        bsa_m2: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("autoEfResultDialog")
        self.setWindowTitle(tr("auto_ef.title"))
        self.resize(760, 560)
        self._initial_result = result
        self._result = result
        self._bsa_m2 = bsa_m2
        self._active_slot: tuple[str, str] = self._first_available_slot(result)
        self._slot_buttons: dict[tuple[str, str], QPushButton] = {}
        self._build_ui()
        self._apply_validation_summary()
        self._refresh_all()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt naming
        """Refresh the external-validation line on every show (live recompute).

        The summary is recomputed from the recorded operator inputs (see
        ``application.ef_validation.recompute_validation_summary``), so a
        validation run that finished while the dialog object was already
        alive still shows current numbers; a missing manifest keeps the
        line hidden.
        """
        self._apply_validation_summary()
        super().showEvent(event)

    @property
    def current_result(self) -> AutoEfPipelineResult:
        return self._result

    @property
    def canvas(self) -> EditableContourCanvas:
        return self._canvas

    def _first_available_slot(self, res: AutoEfPipelineResult) -> tuple[str, str]:
        existing = {(c.view.upper(), c.phase.lower()) for c in res.contours}
        for slot in _SLOT_KEYS:
            if slot in existing:
                return slot
        return ("A4C", "ed")

    def _build_ui(self) -> None:
        tokens = get_theme_tokens()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        card = QFrame(self)
        card.setObjectName("autoEfSummaryCard")
        card.setStyleSheet(
            f"QFrame#autoEfSummaryCard {{ background: {tokens['surface.2']};"
            f" border: 1px solid {tokens['line.2']}; border-radius: 6px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(4)

        top_row = QHBoxLayout()
        self._ef_headline = QLabel(card)
        self._ef_headline.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {tokens['text.1']};")
        self._method_badge = QLabel(card)
        self._method_badge.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {tokens['accent.text']};")
        top_row.addWidget(self._ef_headline)
        top_row.addStretch(1)
        top_row.addWidget(self._method_badge)
        card_layout.addLayout(top_row)

        self._metrics_label = QLabel(card)
        self._indexed_label = QLabel(card)
        self._a4c_label = QLabel(card)
        self._a2c_label = QLabel(card)
        self._prov_label = QLabel(card)
        # External validation of the tool (#418): agreement metrics against the
        # reference standard, from the local manifest.  Shown next to every
        # automatic estimate so the research status of the number is visible
        # where the number is used, not only in the manual.
        self._validation_label = QLabel(card)
        self._validation_label.setWordWrap(True)
        for lbl in (
            self._metrics_label,
            self._indexed_label,
            self._a4c_label,
            self._a2c_label,
            self._prov_label,
            self._validation_label,
        ):
            lbl.setStyleSheet(f"color: {tokens['text.2']}; font-size: 12px;")
            card_layout.addWidget(lbl)
        root.addWidget(card)

        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(6)
        self._slot_group = QButtonGroup(self)
        self._slot_group.setExclusive(True)
        for view, phase in _SLOT_KEYS:
            btn = QPushButton(f"{view} {phase.upper()}", self)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, s=(view, phase): self.select_slot(s[0], s[1]))
            self._slot_group.addButton(btn)
            self._slot_buttons[(view, phase)] = btn
            tabs_row.addWidget(btn)
        tabs_row.addStretch(1)
        hint = QLabel(tr("auto_ef.hint_drag"), self)
        hint.setStyleSheet(f"color: {tokens['text.3']}; font-size: 11px;")
        tabs_row.addWidget(hint)
        root.addLayout(tabs_row)

        self._canvas = EditableContourCanvas(self)
        self._canvas.contour_edited.connect(self._on_contour_edited)
        root.addWidget(self._canvas, stretch=1)

        footer = QHBoxLayout()
        self._reset_btn = QPushButton(tr("auto_ef.reset_ai"), self)
        self._reset_btn.clicked.connect(self.reset_to_initial)
        self._cancel_btn = QPushButton(tr("auto_ef.cancel"), self)
        self._cancel_btn.clicked.connect(self.reject)
        self._accept_btn = QPushButton(tr("auto_ef.accept"), self)
        self._accept_btn.setDefault(True)
        self._accept_btn.clicked.connect(self._on_accept_clicked)
        footer.addWidget(self._reset_btn)
        footer.addStretch(1)
        footer.addWidget(self._cancel_btn)
        footer.addWidget(self._accept_btn)
        root.addLayout(footer)

    def _apply_validation_summary(self) -> None:
        """Show the external validation summary (issue 418) or hide the line.

        The manifest is operator-produced (see ``application.ef_validation``);
        a missing one hides the line, a corrupt one surfaces a stable
        diagnostic event and hides it — never blocks the review dialog.
        """
        try:
            summary = load_auto_ef_validation_summary()
        except (ValueError, OSError) as exc:
            log_boundary_failure(logger, "auto_ef.validation", exc, code="manifest_invalid")
            self._validation_label.hide()
            return
        if not summary:
            self._validation_label.hide()
            return
        report_metrics = summary["metrics"]
        self._validation_label.setText(
            tr(
                "auto_ef.validation_summary",
                source=str(summary["source"]),
                n=int(summary["n"]),
                mae=_fmt_num(float(report_metrics["mae"])),
                threshold=f"{float(summary['threshold_ef']):.0f}%",
                sens=_fmt_validation_rate(report_metrics.get("sensitivity")),
                spec=_fmt_validation_rate(report_metrics.get("specificity")),
            )
        )
        self._validation_label.show()

    def select_slot(self, view: str, phase: str) -> None:
        key = (view.upper(), phase.lower())
        if key not in self._slot_buttons:
            return
        self._active_slot = key
        self._slot_buttons[key].setChecked(True)
        self._refresh_canvas()

    def reset_to_initial(self) -> None:
        self._result = self._initial_result
        self._refresh_all()

    def _on_contour_edited(self, edited: object) -> None:
        if not isinstance(edited, Contour):
            return
        self._result = recalculate_auto_ef(
            self._result,
            (edited,),
            bsa_m2=self._bsa_m2,
            operator_confirmed=False,
        )
        self._refresh_summary()

    def _on_accept_clicked(self) -> None:
        self._result = recalculate_auto_ef(
            self._result,
            self._result.contours,
            bsa_m2=self._bsa_m2,
            operator_confirmed=True,
        )
        self.result_accepted.emit(self._result)
        self.accept()

    def _slot_frame_and_contour(self, view: str, phase: str) -> tuple[np.ndarray | None, Contour | None]:
        branch: AutoEfViewSelection | None = self._result.a4c if view == "A4C" else self._result.a2c
        frame = None
        if branch is not None:
            frame = branch.ed_frame if phase == "ed" else branch.es_frame
        contour = next(
            (c for c in self._result.contours if c.view.upper() == view and c.phase.lower() == phase),
            None,
        )
        return frame, contour

    def _refresh_canvas(self) -> None:
        view, phase = self._active_slot
        frame, contour = self._slot_frame_and_contour(view, phase)
        self._canvas.set_slot(frame, contour, self._result.pixel_spacing_mm)

    def _format_branch_line(self, view: str, branch: AutoEfViewSelection | None) -> str:
        if branch is None:
            return tr("auto_ef.view_missing", view=view)
        metrics = (
            self._result.lvef_result.a4c
            if (self._result.lvef_result is not None and view == "A4C")
            else (self._result.lvef_result.a2c if self._result.lvef_result is not None else None)
        )
        edv = _fmt_num(metrics.edv_ml if metrics is not None else None)
        esv = _fmt_num(metrics.esv_ml if metrics is not None else None)
        return tr(
            "auto_ef.view_summary",
            view=view,
            edv=edv,
            ed=branch.ed_frame_index + 1,
            esv=esv,
            es=branch.es_frame_index + 1,
            phase_src=branch.phase_source,
        )

    def _refresh_summary(self) -> None:
        ef = self._result.lvef_percent
        self._ef_headline.setText(tr("auto_ef.headline", ef=_fmt_num(ef)))
        if self._result.is_biplane:
            self._method_badge.setText(tr("auto_ef.method_biplane"))
        elif ef is not None:
            self._method_badge.setText(tr("auto_ef.method_monoplane"))
        else:
            self._method_badge.setText(tr("auto_ef.method_unavailable"))
        self._metrics_label.setText(
            tr(
                "auto_ef.metrics_line",
                edv=_fmt_num(self._result.edv_ml),
                esv=_fmt_num(self._result.esv_ml),
                sv=_fmt_num(self._result.sv_ml),
            )
        )
        if self._result.edvi_ml_m2 is not None or self._result.esvi_ml_m2 is not None:
            self._indexed_label.setText(
                tr(
                    "auto_ef.indexed_line",
                    edvi=_fmt_num(self._result.edvi_ml_m2),
                    esvi=_fmt_num(self._result.esvi_ml_m2),
                )
            )
            self._indexed_label.show()
        else:
            self._indexed_label.hide()
        self._a4c_label.setText(self._format_branch_line("A4C", self._result.a4c))
        self._a2c_label.setText(self._format_branch_line("A2C", self._result.a2c))
        prov = self._result.provenance
        self._prov_label.setText(
            tr(
                "auto_ef.provenance_line",
                freshness=prov.freshness,
                qc=prov.qc.status,
                rev=prov.revision,
            )
        )
        self._accept_btn.setEnabled(bool(self._result.contours))

    def _refresh_all(self) -> None:
        existing = {(c.view.upper(), c.phase.lower()) for c in self._result.contours}
        for key, btn in self._slot_buttons.items():
            btn.setEnabled(key in existing)
        if self._active_slot not in existing and existing:
            self._active_slot = self._first_available_slot(self._result)
        if self._active_slot in self._slot_buttons:
            self._slot_buttons[self._active_slot].setChecked(True)
        self._refresh_summary()
        self._refresh_canvas()


def launch_auto_ef(window: Any) -> None:
    """Trigger one-click Auto-EF from MainWindow and open the review dialog on completion."""
    if hasattr(window, "_comparison") and window._comparison.tool_blocked("auto_ef"):
        return
    controller = window._controller
    coordinator = window.findChild(AutoEfCoordinator)
    if coordinator is None:
        coordinator = AutoEfCoordinator(controller, parent=window)

        def _on_finished(result: object) -> None:
            if not isinstance(result, AutoEfPipelineResult) or not result.contours:
                window._show_status(tr("auto_ef.failed"))
                return
            snap = controller.state_manager.snapshot
            bsa = (
                snap.calculations.indexed.bsa_m2
                if (snap.calculations is not None and snap.calculations.indexed is not None)
                else None
            )
            dlg = AutoEfResultDialog(result, bsa_m2=bsa, parent=window)
            if dlg.exec() == int(QDialog.DialogCode.Accepted):
                saved = apply_auto_ef_to_controller(
                    controller,
                    dlg.current_result,
                    bsa_m2=bsa,
                    operator_confirmed=True,
                )
                method_txt = tr("auto_ef.method_biplane") if saved.is_biplane else tr("auto_ef.method_monoplane")
                window._show_status(tr("auto_ef.saved", ef=_fmt_num(saved.lvef_percent), method=method_txt))

        def _on_failed(code: str) -> None:
            if code == "no_study":
                window._show_status(tr("auto_ef.no_study"))
            elif code == "segmenter_unavailable":
                window._show_status(tr("app.segmentation_unavailable"))
            else:
                window._show_status(tr("auto_ef.failed"))

        coordinator.finished.connect(_on_finished)
        coordinator.failed.connect(_on_failed)

    if coordinator.start():
        window._show_status(tr("auto_ef.running"))
