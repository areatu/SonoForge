"""«3 Point Contour» overview screen — three views side-by-side with the bull's-eye.

Plan §5.3 п.2: three panels (frame + contour + strip / ECG) + bull's-eye + summary
table + per-view status list, all in one window. Every number is read from the
``StrainStudy`` — there is no recomputation, no hidden averaging, no fabricated
segments. When a view was never analysed its panel says so instead of drawing a
zero contour, exactly the way the vendor screen leaves the panel empty until the
clinician runs that view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.ui.bullseye_widget import BullseyeWidget
from echo_personal_tool.ui.strain_helpers import _smooth_contour

if TYPE_CHECKING:
    from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis, StrainStudy


#: Vendor-style status marks — the same three glyphs used by the meta bar and
#: by :class:`SummaryTable`, so the mark on a card, in the ribbon, in the
#: table and in the report always mean the same thing (plan §6.6).
_STATUS_MARK: dict[str, str] = {"valid": "●", "review": "⚠", "invalid": "■"}
_STATUS_COLOR: dict[str, str] = {
    "valid": "#4caf50",
    "review": "#ffb300",
    "invalid": "#ef5350",
}
#: Smallest number of endo points needed to draw a contour through (less than
#: that would just be noise — skip rather than fabricate).
_MIN_CONTOUR_POINTS = 3


def _frame_to_qimage(frame: np.ndarray) -> QImage:
    """Convert a grayscale ultrasound frame to a QImage (Format_Grayscale8)."""
    f = np.asarray(frame, dtype=np.uint8, order="C")
    if f.ndim != 2:
        raise ValueError(f"expected 2-D grayscale frame, got shape {f.shape}")
    h, w = f.shape
    return QImage(f.data, w, h, w, QImage.Format.Format_Grayscale8).copy()


def _points_to_polygon(points: np.ndarray) -> QPolygonF:
    return QPolygonF([QPointF(float(x), float(y)) for x, y in np.asarray(points)])


def _render_thumbnail_pixmap(snap: ViewSnapshot) -> QPixmap | None:
    """Render an ED-frame thumbnail with ED/ES contours + kernels.

    The result is a QPixmap at the native frame resolution with overlays
    painted in vendor-style colours (red ED, dashed green ES, white kernel
    squares). The card then scales it with ``KeepAspectRatio`` so the
    sector always fills the panel width — no pillarboxing artefacts.
    """
    if snap.ed_frame is None or snap.ed_frame.ndim < 2:
        return None
    img = _frame_to_qimage(snap.ed_frame)
    pix = QPixmap.fromImage(img.convertToFormat(QImage.Format.Format_RGB32))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    try:
        if snap.ed_contour is not None and len(snap.ed_contour) >= _MIN_CONTOUR_POINTS:
            pts = _smooth_contour(np.asarray(snap.ed_contour, dtype=float), n_output=96)
            painter.setPen(QPen(QColor("#ff1744"), 2.5))
            painter.drawPolyline(_points_to_polygon(pts))
        if snap.es_contour is not None and len(snap.es_contour) >= _MIN_CONTOUR_POINTS:
            pts = _smooth_contour(np.asarray(snap.es_contour, dtype=float), n_output=96)
            pen = QPen(QColor("#00e676"), 1.8)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPolyline(_points_to_polygon(pts))
        if snap.endo_positions_ed is not None and len(snap.endo_positions_ed) > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 220))
            for x, y in np.asarray(snap.endo_positions_ed):
                painter.drawRect(QRectF(float(x) - 1.5, float(y) - 1.5, 3.0, 3.0))
    finally:
        painter.end()
    return pix


@dataclass
class ViewSnapshot:
    """Visual snapshot of a single analysed view.

    The ``StrainAnalysis`` holds every number; the snapshot holds the pixels
    and contours needed to redraw that view's panel without rerunning the
    tracker. Frames are kept by reference (no copy) — the caller owns the
    buffer, and we only read from it.
    """

    view: str
    ed_frame: np.ndarray | None = None
    ed_contour: np.ndarray | None = None
    es_contour: np.ndarray | None = None
    endo_positions_ed: np.ndarray | None = None
    # ECG (already downsampled to per-frame for display, or None).
    ecg_trace: np.ndarray | None = None
    ecg_frame_time_ms: float = 33.3
    ed_index: int = 0
    es_index: int = 0
    frame_count: int = 0
    heart_rate_bpm: float = 0.0
    kernels: list = field(default_factory=list)


class _ViewCard(QFrame):
    """One thumbnail: ED frame + ED/ES contours + endo kernels + status chip."""

    def __init__(self, view: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view = view
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("QFrame { background: #0a0f14; border: 1px solid #263238; border-radius: 4px; }")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        # Header row: view label | GLS value + status mark
        header = QHBoxLayout()
        self._title = QLabel(view)
        self._title.setStyleSheet("font-weight: bold; color: #eceff1; font-size: 12px;")
        header.addWidget(self._title)
        header.addStretch()
        self._value = QLabel("--")
        self._value.setStyleSheet("font-weight: bold; color: #ffd54f; font-size: 13px;")
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._value)
        self._status = QLabel("")
        self._status.setStyleSheet("font-weight: bold; font-size: 14px;")
        header.addWidget(self._status)
        layout.addLayout(header)

        # Frame thumbnail (rendered to a QPixmap on each update, with
        # contours/kernels painted over the ED image). Using a QLabel with
        # scaledContents + KeepAspectRatio gives us the vendor-style
        # behaviour automatically: the sector fills the card width with a
        # small black band only where the image aspect doesn't match,
        # instead of pyqtgraph's aspectLocked mode which was forcing a
        # square viewBox and pillarboxing the sector into the upper half
        # of the card (the "Samsung phone look").
        self._thumb = QLabel()
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet("background: black;")
        self._thumb.setMinimumHeight(200)
        self._thumb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._thumb, stretch=4)
        self._thumb_pixmap: QPixmap | None = None

        # Mini ECG strip under the frame.
        self._ecg_plot = pg.PlotWidget()
        self._ecg_plot.setBackground("#0a0f14")
        self._ecg_plot.hideAxis("left")
        self._ecg_plot.hideAxis("bottom")
        self._ecg_plot.setMaximumHeight(36)
        self._ecg_plot.setMinimumHeight(28)
        layout.addWidget(self._ecg_plot, stretch=0)
        self._ecg_item: pg.PlotDataItem | None = None
        self._ecg_ed_line: pg.InfiniteLine | None = None
        self._ecg_es_line: pg.InfiniteLine | None = None

        # Footer: HR / frame info / reasons
        footer = QHBoxLayout()
        self._hr = QLabel("")
        self._hr.setStyleSheet("color: #80cbc4; font-size: 10px;")
        footer.addWidget(self._hr)
        footer.addStretch()
        self._frames_label = QLabel("")
        self._frames_label.setStyleSheet("color: #78909c; font-size: 10px;")
        footer.addWidget(self._frames_label)
        layout.addLayout(footer)

        # Reasons line (only when QC != valid).
        self._reasons = QLabel("")
        self._reasons.setStyleSheet("color: #ff8a65; font-size: 9px;")
        self._reasons.setWordWrap(True)
        layout.addWidget(self._reasons)

        # Placeholder shown when no analysis is available for this view.
        self._placeholder = QLabel(tr("strain.no_data"))
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #607d8b; font-size: 11px;")
        layout.addWidget(self._placeholder, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: D401, N802 - Qt override
        super().resizeEvent(event)
        if self._thumb_pixmap is not None and not self._thumb_pixmap.isNull():
            self._thumb.setPixmap(
                self._thumb_pixmap.scaled(
                    self._thumb.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def clear(self) -> None:
        """Reset the card to its empty state (no data)."""
        self._thumb_pixmap = None
        self._thumb.clear()
        for item in (self._ecg_item, self._ecg_ed_line, self._ecg_es_line):
            if item is not None:
                self._ecg_plot.removeItem(item)
        self._ecg_item = self._ecg_ed_line = self._ecg_es_line = None
        self._value.setText("--")
        self._status.setText("")
        self._status.setToolTip("")
        self._hr.setText("")
        self._frames_label.setText("")
        self._reasons.setText("")
        self._reasons.hide()
        self._placeholder.show()

    def set_analysis(self, analysis: StrainAnalysis, snapshot: ViewSnapshot | None) -> None:
        """Fill the card with numbers from ``analysis`` and visuals from ``snapshot``."""
        self.clear()
        self._placeholder.hide()

        # GLS value + QC mark (the same mark the table and the report use).
        status = str(getattr(analysis, "qc_status", "invalid") or "invalid")
        mark = _STATUS_MARK.get(status, "■")
        color = _STATUS_COLOR.get(status, "#ef5350")
        gls = analysis.gls
        if gls is not None and np.isfinite(gls):
            self._value.setText(f"{gls:.1f}%")
        else:
            self._value.setText("--")
        self._status.setText(mark)
        self._status.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px;")
        self._status.setToolTip(tr(f"strain.qc_status_{status}"))

        # HR / frames footer.
        hr = float(getattr(analysis, "heart_rate_bpm", 0.0) or 0.0)
        if hr > 0:
            self._hr.setText(f"HR {hr:.0f}")
        n_frames = snapshot.frame_count if snapshot and snapshot.frame_count else 0
        if n_frames > 0:
            self._frames_label.setText(
                f"ED {analysis.ed_index} / ES {analysis.es_index} / AVC {analysis.avc_index} · {n_frames} fr"
            )
        else:
            self._frames_label.setText(f"ED {analysis.ed_index} · ES {analysis.es_index}")

        # QC reasons (one-liner when the view needs review).
        reasons = tuple(getattr(analysis, "qc_reasons", ()) or ())
        if status != "valid" and reasons:
            short = ", ".join(tr(key) for key in reasons[:2])
            self._reasons.setText(short)
            self._reasons.show()
        else:
            self._reasons.hide()

        # Visual layer: frame + contours + kernels when a snapshot is present.
        if snapshot is not None:
            self._render_snapshot(snapshot)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_snapshot(self, snap: ViewSnapshot) -> None:
        pixmap = _render_thumbnail_pixmap(snap)
        if pixmap is not None:
            self._thumb_pixmap = pixmap
            self._thumb.setPixmap(
                pixmap.scaled(
                    self._thumb.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        # Mini ECG strip (hidden entirely when no ECG — plan §6.5: never
        # draw a synthetic ECG to pretend the data is there).
        if snap.ecg_trace is not None and len(snap.ecg_trace) >= 2:
            ft = max(float(snap.ecg_frame_time_ms), 0.001)
            n = len(snap.ecg_trace)
            t = np.arange(n) * ft
            self._ecg_item = pg.PlotDataItem(t, snap.ecg_trace, pen=pg.mkPen("#4caf50", width=1))
            self._ecg_plot.addItem(self._ecg_item)
            if 0 <= snap.ed_index < n:
                self._ecg_ed_line = pg.InfiniteLine(
                    pos=snap.ed_index * ft,
                    angle=90,
                    pen=pg.mkPen("#00e676", width=1, style=Qt.PenStyle.DashLine),
                )
                self._ecg_plot.addItem(self._ecg_ed_line)
            if 0 <= snap.es_index < n:
                self._ecg_es_line = pg.InfiniteLine(
                    pos=snap.es_index * ft,
                    angle=90,
                    pen=pg.mkPen("#ffd54f", width=1, style=Qt.PenStyle.DashLine),
                )
                self._ecg_plot.addItem(self._ecg_es_line)
            self._ecg_plot.setXRange(0, t[-1], padding=0.0)
            self._ecg_plot.show()
        else:
            self._ecg_plot.hide()


class OverviewScreen(QWidget):
    """«3 Point Contour» overview: three views in a row with the study bull's-eye.

    The widget is a pure projection of :class:`StrainStudy` + cached visual
    snapshots. It never recomputes strain or averages: numbers come straight
    from the analyses in the study, and the 18-segment merge uses
    :meth:`StrainStudy.bullseye_segments` — the same method the protocol report
    uses, so the UI and the printed report can never disagree about which
    segments are shown.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("steOverviewScreen")
        self.setStyleSheet("QWidget#steOverviewScreen { background: #0d1318; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Top ribbon: GLS_AV large, per-view GLS small, QC counts.
        ribbon = QHBoxLayout()
        self._avg_label = QLabel("--")
        f = QFont()
        f.setPointSize(22)
        f.setBold(True)
        self._avg_label.setFont(f)
        self._avg_label.setStyleSheet("color: #ffd54f;")
        ribbon.addWidget(self._avg_label)

        self._avg_title = QLabel(tr("strain.gls_av"))
        self._avg_title.setStyleSheet("color: #90a4ae; font-size: 11px; margin-left: 4px;")
        ribbon.addWidget(self._avg_title)
        ribbon.addSpacing(20)

        self._view_chips: dict[str, QLabel] = {}
        for v in ("A4C", "A2C", "A3C"):
            chip = QLabel(f"{v} --")
            chip.setStyleSheet(
                "color: #cfd8dc; background: #16212b; padding: 4px 10px; "
                "border-radius: 3px; font-size: 12px; font-weight: bold;"
            )
            ribbon.addWidget(chip)
            self._view_chips[v] = chip

        ribbon.addStretch()

        self._qc_summary = QLabel("")
        self._qc_summary.setStyleSheet("color: #b0bec5; font-size: 11px;")
        ribbon.addWidget(self._qc_summary)
        root.addLayout(ribbon)

        # ── Middle: 3 view cards in a grid with the bull's-eye in the fourth cell.
        grid = QGridLayout()
        grid.setSpacing(6)
        self._cards: dict[str, _ViewCard] = {}
        for col, view in enumerate(("A4C", "A2C", "A3C")):
            card = _ViewCard(view)
            self._cards[view] = card
            grid.addWidget(card, 0, col)

        # Bull's-eye cell (rightmost, spans vertically).
        self._bullseye = BullseyeWidget()
        self._bullseye.setMinimumWidth(260)
        self._bullseye.setMinimumHeight(260)
        grid.addWidget(self._bullseye, 0, 3, 2, 1)

        # Per-view status list under the middle card.
        self._status_list = QLabel("")
        self._status_list.setStyleSheet(
            "color: #cfd8dc; font-size: 11px; background: #16212b; padding: 6px; border-radius: 3px;"
        )
        self._status_list.setWordWrap(True)
        self._status_list.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._status_list, 1, 0, 1, 3)

        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 3)
        grid.setColumnStretch(3, 2)
        root.addLayout(grid, stretch=1)

        # Start empty.
        self._study: StrainStudy | None = None
        self._snapshots: dict[str, ViewSnapshot] = {}
        for card in self._cards.values():
            card.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def bullseye(self) -> BullseyeWidget:
        """The embedded bull's-eye, so the control panel palette/ttp toggles can drive it."""
        return self._bullseye

    def set_snapshot(self, snapshot: ViewSnapshot) -> None:
        """Register the visual snapshot of one view (called from StrainWindow.show_result)."""
        self._snapshots[snapshot.view] = snapshot

    def clear_snapshot(self, view: str) -> None:
        """Drop a previously-cached snapshot (e.g. when the user re-runs a view)."""
        self._snapshots.pop(view, None)

    def set_study(self, study: StrainStudy) -> None:
        """Render the study: per-view cards, the 18-segment bull's-eye and GLS_AV."""
        self._study = study

        valid = study.views_valid()
        measured = study.views_measured()
        gls_av = study.gls_average()
        if gls_av is not None and np.isfinite(gls_av):
            self._avg_label.setText(f"{gls_av:.1f}%")
        else:
            self._avg_label.setText("--")

        # Per-view chips across the top.
        for view in ("A4C", "A2C", "A3C"):
            chip = self._view_chips[view]
            analysis = study.analyses.get(view)
            mark = ""
            if analysis is not None:
                status = analysis.qc_status
                mark = f" {_STATUS_MARK.get(status, '■')}"
                val = analysis.gls
                if val is not None and np.isfinite(val):
                    chip.setText(f"{view} {val:.1f}%{mark}")
                else:
                    chip.setText(f"{view} --{mark}")
                color = _STATUS_COLOR.get(status, "#ef5350")
            else:
                chip.setText(f"{view} --")
                color = "#546e7a"
            chip.setStyleSheet(
                f"color: #eceff1; background: #16212b; padding: 4px 10px; "
                f"border-radius: 3px; font-size: 12px; font-weight: bold; "
                f"border-left: 4px solid {color};"
            )

        # QC summary line: how many views contributed / which were rejected.
        parts = []
        parts.append(f"{len(measured)}/3 {tr('strain.overview_views_measured')}")
        if len(valid) != len(measured):
            review = [v for v in measured if study.analyses[v].qc_status == "review"]
            invalid = [v for v in measured if study.analyses[v].qc_status == "invalid"]
            if review:
                parts.append(f"⚠ {', '.join(review)}")
            if invalid:
                parts.append(f"■ {', '.join(invalid)}")
        missing = study.missing_segments()
        if missing:
            parts.append(f"{len(missing)} {tr('strain.overview_segments_missing')}")
        self._qc_summary.setText("   |   ".join(parts))

        # Fill per-view cards.
        for view in ("A4C", "A2C", "A3C"):
            card = self._cards[view]
            analysis = study.analyses.get(view)
            if analysis is None:
                card.clear()
            else:
                card.set_analysis(analysis, self._snapshots.get(view))

        # Bull's-eye: the study's 18-segment merge, exactly like the report.
        segs = study.bullseye_segments()
        # Aggregate quality/TTP from the same merge so segments never disagree
        # between the bull's-eye and the cards.
        quality: dict[int, float] = {}
        ttp: dict[int, float] = {}
        sources = study.segment_sources()
        for seg_id in segs:
            src = sources.get(seg_id)
            if not src:
                continue
            a = study.analyses.get(src)
            if a is None:
                continue
            q = a.segment_quality.get(seg_id)
            if q is not None:
                quality[int(seg_id)] = float(q)
            t = a.segment_ttp_ms.get(seg_id)
            if t is not None:
                ttp[int(seg_id)] = float(t)
        self._bullseye.update_data(segs, quality if quality else None, ttp if ttp else None)

        # Status list: human-readable per-view summary.
        lines = []
        for view in ("A4C", "A2C", "A3C"):
            analysis = study.analyses.get(view)
            if analysis is None:
                lines.append(f"<span style='color:#607d8b'>{view}</span> — {tr('strain.no_data')}")
                continue
            mark = _STATUS_MARK.get(analysis.qc_status, "■")
            color = _STATUS_COLOR.get(analysis.qc_status, "#ef5350")
            label_status = tr(f"strain.qc_status_{analysis.qc_status}")
            gls_txt = "--" if analysis.gls is None or not np.isfinite(analysis.gls) else f"{analysis.gls:.1f}%"
            avc_key = f"strain.avc_{analysis.avc_source}"
            avc_src = tr(avc_key)
            if avc_src == avc_key:
                avc_src = str(analysis.avc_source)
            lines.append(
                f"<span style='color:{color}'>{mark}</span> <b>{view}</b> "
                f"GLS {gls_txt} — {label_status} · "
                f"AVC: {avc_src} · ED/ES {analysis.ed_index}/{analysis.es_index} · "
                f"QC {analysis.qc_coverage * 100:.0f}%"
            )
        self._status_list.setText("<br>".join(lines))
