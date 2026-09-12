"""Separate window for STE strain visualization — quad-view layout."""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr

if TYPE_CHECKING:
    from echo_personal_tool.domain.models.speckle import StrainResult

from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis, StrainStudy
from echo_personal_tool.presentation.segment_labels import (
    full_segment_label,
)
from echo_personal_tool.ui.bullseye_widget import BullseyeWidget  # noqa: F401 — re-exported
from echo_personal_tool.ui.cine_panel import CinePanel  # noqa: F401 — re-exported
from echo_personal_tool.ui.control_panel import ControlPanel  # noqa: F401 — re-exported
from echo_personal_tool.ui.ste import OverviewScreen, ViewSnapshot
from echo_personal_tool.ui.ste.gold_contour import contour_from_result, default_path_for, load_for
from echo_personal_tool.ui.strain_curves_view import StrainCurvesView

# --- Extracted submodules (step 1 of decomposition) ---
from echo_personal_tool.ui.strain_helpers import (  # noqa: F401 — re-exported for backward compat
    AHA_SEGMENT_NAMES_RU,
    DEFORMATION_PLUS_RAMP,
    MONOCHROME_RAMP,
    PALETTES,
    RAINBOW_RAMP,
    STRAIN_RAMP,
    _smooth_contour,
    segment_name,
)
from echo_personal_tool.ui.summary_table import SummaryTable  # noqa: F401 — re-exported

logger = logging.getLogger(__name__)


class StrainWindow(QMainWindow):
    """Separate window for STE strain visualization with quad-view layout."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Strain Analysis")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        try:
            from PySide6.QtCore import QSettings

            geo = QSettings("SonoForge", "StrainWindow").value("geometry")
            if geo is not None:
                self.restoreGeometry(geo)
        except Exception:  # noqa: BLE001
            pass

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Splitter: control panel | content
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Control panel
        self._control = ControlPanel()
        self._control.view_toggled.connect(self._on_view_toggled)
        self._control.display_mode_changed.connect(self._on_display_mode_changed)
        self._control.strain_metric_changed.connect(self._on_strain_metric_changed)
        self._control.qc_segment_toggled.connect(self._on_qc_segment_toggled)
        self._control.position_selected.connect(self._on_position_selected)
        self._control._btn_undo.clicked.connect(self._undo_kernel_move)
        self._control._btn_redo.clicked.connect(self._redo_kernel_move)
        self._control._btn_save.clicked.connect(self._save_json)
        self._control._btn_export_png.clicked.connect(self._export_png)
        self._control._btn_export_csv.clicked.connect(self._export_csv)
        self._control.save_gold_contour.connect(self._save_gold_contour)
        self._control.load_gold_contour.connect(self._load_gold_contour)
        # Plan §6.5: ``C`` cycles the bull's-eye palette. The combo box stays in
        # sync, so the keyboard and the panel never disagree about the palette.
        palette_shortcut = QShortcut(QKeySequence(Qt.Key.Key_C), self)
        palette_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        palette_shortcut.activated.connect(self._cycle_bullseye_palette)
        self._control._btn_close.clicked.connect(self.close)
        splitter.addWidget(self._control)

        # Content area: meta bar on top, stacked views + summary below
        content = QWidget()
        content_outer = QVBoxLayout(content)
        content_outer.setContentsMargins(0, 0, 0, 0)
        content_outer.setSpacing(3)

        self._meta_label = QLabel("")
        self._meta_label.setStyleSheet(
            "QLabel { color: #cfd8dc; font-size: 11px; font-weight: bold; "
            "background: #16212b; padding: 3px 8px; border-radius: 3px; }"
        )
        content_outer.addWidget(self._meta_label)

        content_inner = QWidget()
        content_layout = QHBoxLayout(content_inner)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        # Stacked widget for contour/curves modes
        self._stacked = QStackedWidget()

        # Contour mode (2x2 grid)
        contour_widget = QWidget()
        contour_layout = QGridLayout(contour_widget)
        contour_layout.setContentsMargins(0, 0, 0, 0)
        contour_layout.setSpacing(4)

        self._panel_a4c = CinePanel("A4C")
        self._panel_a2c = CinePanel("A2C")
        self._panel_dao = CinePanel("DAO (A3C)")
        self._panel_bullseye = BullseyeWidget()
        self._control.ttp_mode_toggled.connect(self._panel_bullseye.set_ttp_mode)
        self._control.palette_changed.connect(self._panel_bullseye.set_palette)

        contour_layout.addWidget(self._panel_a4c, 0, 0)
        contour_layout.addWidget(self._panel_a2c, 0, 1)
        contour_layout.addWidget(self._panel_dao, 1, 0)
        contour_layout.addWidget(self._panel_bullseye, 1, 1)

        self._stacked.addWidget(contour_widget)  # index 0

        # Curves mode
        self._curves_view = StrainCurvesView()
        self._stacked.addWidget(self._curves_view)  # index 1

        # «3 Point Contour» overview (plan §5.3 п.2): three per-view cards, the
        # 18-segment bull's-eye from ``StrainStudy``, and a per-view status list.
        # All data flows from the study — no recomputation.
        self._overview = OverviewScreen()
        self._control.ttp_mode_toggled.connect(self._overview.bullseye.set_ttp_mode)
        self._control.palette_changed.connect(self._overview.bullseye.set_palette)
        self._stacked.addWidget(self._overview)  # index 2

        content_layout.addWidget(self._stacked, stretch=3)

        # Summary table
        self._summary = SummaryTable()
        content_layout.addWidget(self._summary, stretch=1)

        content_outer.addWidget(content_inner, stretch=1)

        splitter.addWidget(content)
        splitter.setSizes([180, 1220])

        main_layout.addWidget(splitter)

        # State
        self._result: StrainResult | None = None
        self._position: str = "A4C"
        # DICOM provenance carried with the current clip (set via show_result):
        # needed to write a gold-contour JSON that the validation harness can
        # match back to the source clip.
        self._study_uid: str = ""
        self._sop_instance_uid: str = ""
        self._source_path: str = ""
        self._pixel_spacing_mm: tuple[float, float] = (1.0, 1.0)
        # Multi-view study: every analysed view is kept, so the report can show
        # per-view GLS, the three-view average (GLS_AV) and the 18-segment merge.
        self._study: StrainStudy = StrainStudy()
        self._qc_accepted_segments: set[int] = set(range(1, 18))  # All segments accepted by default

        # Undo/Redo stacks for kernel movements
        self._undo_stack: list[tuple[int, float, float, float, float]] = []  # (idx, old_x, old_y, new_x, new_y)
        self._redo_stack: list[tuple[int, float, float, float, float]] = []

        # Connect panel signals
        self._panel_a4c.kernel_moved.connect(lambda idx, x, y: self._on_kernel_moved("A4C", idx, x, y))

    def set_study(self, study: StrainStudy | None) -> None:
        """Adopt the study accumulated by the application (plan §5.3 п.6).

        The window used to be the only place that remembered the analysed
        views, so closing it silently dropped the per-view GLS and GLS_AV that
        the protocol still reported. The application now owns that
        accumulation; the window adopts it, which also guarantees the table and
        the report can never show different sets of views.

        Only a real :class:`StrainStudy` is adopted. Anything else (``None``
        before the first analysis, or a stand-in controller that answers every
        call) keeps the study the window already has: a duck-typed object would
        pass this far and only fail later, while formatting ``GLS_AV`` — far
        from the place that supplied it.
        """
        if isinstance(study, StrainStudy):
            self._study = study
            self._refresh_overview()

    def show_result(
        self,
        result: StrainResult,
        *,
        frames: np.ndarray | None = None,
        study_uid: str = "",
        sop_instance_uid: str = "",
        pixel_spacing_mm: tuple[float, float] | None = None,
    ) -> None:
        """Display strain results in the STE window.

        Args:
            result: computed StrainResult.
            frames: optional full cine (N, H, W[, C]) used as the ultrasound
                background of the A4C panel. Positions in the result are in the
                same pixel coordinate space, so overlays line up with the image.
            study_uid: DICOM Study Instance UID — used as the file-name stem
                when saving a gold contour (plan §11.2 п.1).
            sop_instance_uid: DICOM SOP Instance UID, stored verbatim in the
                gold-contour JSON for provenance.
            pixel_spacing_mm: physical pixel size (row, col) from the DICOM;
                defaults to the value carried on the worker result, then 1 mm.
        """
        self._result = result
        # Record DICOM provenance for gold-contour saves (newer value wins;
        # unknown fields stay at their default so older callers keep working).
        self._study_uid = str(study_uid or getattr(result, "study_instance_uid", "") or "")
        self._sop_instance_uid = str(sop_instance_uid or getattr(result, "sop_instance_uid", "") or "")
        self._source_path = str(getattr(result, "source_path", "") or "")
        if pixel_spacing_mm is not None and len(pixel_spacing_mm) == 2:
            self._pixel_spacing_mm = (float(pixel_spacing_mm[0]), float(pixel_spacing_mm[1]))
        else:
            try:
                ps = getattr(result, "pixel_spacing_mm", None)
                if ps is not None and len(ps) == 2:
                    self._pixel_spacing_mm = (float(ps[0]), float(ps[1]))
            except Exception:  # noqa: BLE001
                pass

        # Record this view in the study; the newest run of a view wins.
        analysis = StrainAnalysis.from_result(result)
        self._analysis = analysis
        self._study = self._study.with_view(analysis)

        # Visual snapshot for the overview screen (plan §5.3 п.2): store the ED
        # frame + ED/ES contours + endo kernels per view so the 3-view screen
        # can redraw without recomputing strain. The snapshot borrows frame
        # memory from the caller (no copy) — frame buffers live for the
        # lifetime of the viewer.
        self._overview.set_snapshot(self._capture_view_snapshot(result, frames))

        disp_idx: int | None = None
        n_all = len(result.longitudinal) if result.longitudinal is not None else 0
        if frames is not None and frames.ndim >= 3 and frames.shape[0] == n_all:
            ed = result.ed_index
            if 0 <= ed < frames.shape[0]:
                disp_idx = ed

        # ── Meta bar ────────────────────────────────────────────────────────
        parts: list[str] = [f"{tr('strain.view_label')} {self._analysis.view}", f"GLS {result.gls:.1f}%"]
        gls_av = self._study.gls_average()
        if gls_av is not None and len(self._study.views_valid()) > 1:
            parts.append(tr("strain.gls_av_meta", value=f"{gls_av:.1f}", n=str(len(self._study.views_valid()))))
        # Honest QC (issue #3): NCC fidelity and measurement validity are
        # different things. Never label a high NCC as "quality" without the
        # validity status next to it.
        status = getattr(result, "qc_status", "") or "invalid"
        if status == "valid":
            parts.append(f"● {tr('strain.qc_status_valid')}")
        elif status == "review":
            parts.append(f"⚠ {tr('strain.qc_status_review')}")
        else:
            parts.append(f"■ {tr('strain.qc_status_invalid')}")
        if result.tracking_quality_mean:
            parts.append(tr("strain.qc_fidelity", pct=f"{result.tracking_quality_mean * 100.0:.0f}"))
        avc_source = getattr(result, "avc_source", "") or ""
        if avc_source:
            parts.append(
                tr(
                    "strain.avc_source",
                    source=tr(f"strain.avc_{avc_source}"),
                    frame=str(getattr(result, "avc_index", 0)),
                )
            )
        drift = float(getattr(result, "drift_measured", float("nan")))
        if np.isfinite(drift) and abs(drift) > 2.0:
            parts.append(tr("strain.drift_warning", value=f"{drift:+.1f}"))
        if getattr(result, "is_post_systolic", False):
            parts.append(tr("strain.post_systolic"))
        # Segment names depend on which wall the display puts on the left; the
        # user's declaration travels with the numbers (Voigt 2015).
        if getattr(result, "segment_flip_applied", False):
            parts.append(tr("strain.segment_flip_meta"))
        # Round-trip verification of the tracking (clinical review Q6): the share
        # of node-frames the tracker could confirm by matching there and back, and
        # how far the round trip misses the drawn contour. This is the number that
        # turns "trust the tracking" into evidence.
        confirmed = 1.0 - float(getattr(result, "qc_rejected_fraction", 0.0) or 0.0)
        closure_mm = float(getattr(result, "qc_closure_median_mm", 0.0) or 0.0)
        if getattr(result, "qc_rejected_fraction", None) is not None:
            parts.append(
                tr(
                    "strain.tracking_verification",
                    confirmed=f"{confirmed * 100.0:.1f}",
                    closure=f"{closure_mm:.1f}",
                )
            )
        qc_reasons = getattr(result, "qc_reasons", ()) or ()
        if qc_reasons:
            reason_text = ", ".join(tr(key) for key in qc_reasons[:2])
            parts.append(f"{tr('strain.qc_reasons')}: {reason_text}")
        elif not result.qc_physiology_ok and result.qc_physiology_reasons:
            parts.append(f"⚠ {result.qc_physiology_reasons[0]}")
        total_k = result.kernels_total_count
        if total_k:
            parts.append(f"kernels {result.kernels_accepted_count}/{total_k}")
        source_map = {
            "manual": "manual",
            "manual_ed+auto": "manual ED + auto ES",
            "manual_es+auto": "manual ES + auto ED",
            "ecg": "ECG",
            "simpson": "Simpson",
            "image": "image",
            "image_fallback": "image",
        }
        source_label = source_map.get(result.ed_es_source, result.ed_es_source)
        parts.append(f"ED/ES {result.ed_index}/{result.es_index} ({source_label})")
        parts.append(f"Позиция: {self._position}")
        if result.drift_compensation_applied:
            parts.append("drift on")
        if result.heart_rate_bpm > 0:
            parts.append(f"HR {result.heart_rate_bpm:.0f} bpm")
        self._meta_label.setText("   |   ".join(parts))

        # Update quality gate info
        self._control.update_quality(
            result.kernels_accepted_count,
            result.kernels_total_count,
            result.kernels_rejected_count,
        )

        # Per-view GLS: only the analysed view can have a value — the segments
        # of the other views were never measured, and the old id-range split
        # (<=6 / 7..11 / >=12) mixed walls of different views (issues #C2/#C11).
        # Per-view GLS: filled from the recorded analyses, so a view analysed
        # earlier keeps its value (and the average of the views is meaningful).
        # A view that was never analysed stays empty — never a fabricated 0.
        view = self._analysis.view
        gls_a4c = self._study.view_gls("A4C")
        gls_a2c = self._study.view_gls("A2C")
        gls_dao = self._study.view_gls("A3C")

        # Update summary table — GLS (peak of the global curve) next to ESS
        # (value at AVC), time to peak, post-systolic index and the measured
        # baseline drift, so the systolic value can never be mistaken for the
        # peak one (plan §3.5).
        def _finite(value) -> float | None:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return number if np.isfinite(number) else None

        # Which measured views passed QC, vendor-style: the per-view rows carry
        # the status mark so GLS_AV is never read as "three views agreed".
        self._summary.set_view_statuses({view: item.qc_status for view, item in self._study.analyses.items()})
        self._summary.update_values(
            gls=result.gls,
            gls_a4c=gls_a4c,
            gls_a2c=gls_a2c,
            gls_dao=gls_dao,
            gls_av=self._study.gls_average(),
            ess=_finite(getattr(result, "ess", None)),
            ttp=_finite(getattr(result, "time_to_peak_ms", None)),
            psi=_finite(getattr(result, "post_systolic_index", None)),
            drift=_finite(getattr(result, "drift_measured", None)),
            hr=result.heart_rate_bpm if result.heart_rate_bpm > 0 else None,
        )

        # Update Bull's Eye plot
        if result.segment_strain:
            self._panel_bullseye.update_data(
                result.segment_strain,
                result.segment_quality,
                getattr(result, "segment_ttp_ms", None),
            )

            # Populate QC checkboxes for available segments
            self._populate_qc_checkboxes(result.segment_strain)

        # Get endo kernels and positions
        endo_indices = [i for i, k in enumerate(result.kernels) if k.layer == "endo"]
        endo_kernels = [result.kernels[i] for i in endo_indices]

        # Update A4C panel (main view)
        self._panel_a4c.set_title_info(f"GLS: {result.gls:.1f}%")

        # ED contour (red, smoothed)
        if result.ed_contour is not None and len(result.ed_contour) >= 3:
            self._panel_a4c.show_contour(result.ed_contour, color="#ff1744", smooth=True)

        # ES contour (green, dashed)
        if result.es_contour is not None and len(result.es_contour) >= 3:
            self._panel_a4c.show_es_contour(result.es_contour, color="#00e676", smooth=True)

        # Tracking kernels with quality coloring
        if result.tracked_ed_positions is not None:
            endo_positions = result.tracked_ed_positions[endo_indices]
            if result.es_ncc_scores is not None and result.es_valid_mask is not None:
                endo_ncc = result.es_ncc_scores[endo_indices]
                endo_valid = result.es_valid_mask[endo_indices]
                self._panel_a4c.show_kernels(endo_positions, endo_ncc, endo_valid)
            else:
                self._panel_a4c.show_kernels(endo_positions)

            # Segment labels (Russian names)
            self._panel_a4c.show_segment_labels(endo_kernels, endo_positions)

        # HR and frame info
        self._panel_a4c.set_hr(result.heart_rate_bpm)
        n_frames = len(result.longitudinal) if result.longitudinal is not None else 0
        # Real ultrasound background (frame where kernels/ED contour are anchored)
        self._panel_a4c.set_frames(frames, index=disp_idx if disp_idx is not None else 0)
        self._panel_a4c.set_frame((disp_idx if disp_idx is not None else result.es_index) + 1, n_frames)

        # Per-frame animated overlay (kernels + live endo contour follow the wall)
        layers = [k.layer for k in result.kernels]
        self._panel_a4c.set_tracked_overlay(
            result.tracked_positions_all,
            layers=layers,
            ed_index=result.ed_index,
            es_index=result.es_index,
        )

        # ECG trace: real DICOM ECG only. No real ECG → strip hidden entirely
        # (no synthetic placeholder — issue #2).
        has_ecg = result.ecg_trace_for_display is not None and len(result.ecg_trace_for_display) > 0
        if has_ecg:
            ecg = result.ecg_trace_for_display
            sample_rate: float | None = None
            if result.ecg_waveform is not None and result.ecg_waveform.primary_lead is not None:
                sample_rate = float(result.ecg_waveform.primary_lead.sampling_frequency)
            r_peak_times: np.ndarray | None = None
            if result.r_peak_result is not None and result.r_peak_result.r_peak_times_ms is not None:
                r_peak_times = result.r_peak_result.r_peak_times_ms
            self._panel_a4c.show_ecg_trace(
                ecg,
                frame_time_ms=result.frame_time_ms,
                current_frame=result.es_index,
                ecg_sample_rate=sample_rate,
                r_peak_times_ms=r_peak_times,
                ed_frame=result.ed_index,
                es_frame=result.es_index,
            )
            self._panel_a4c.set_ecg_visible(True)
        else:
            self._panel_a4c.set_ecg_visible(False)

        # A2C/DAO are not analysed in the single-view pass
        self._panel_a2c.set_title_info(tr("strain.no_data"))
        self._panel_dao.set_title_info(tr("strain.no_data"))

        # Update curves view (ECG strip hidden there too when absent)
        self._curves_view.set_strain_data(result)

        # Keep the overview in sync even when it's not the active page, so
        # switching to it later shows the latest study without a second click.
        self._refresh_overview()

        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def set_position(self, view: str) -> None:
        """Record which echo view (A4C/A2C/A3C) the contours came from."""
        view = view.upper()
        if view not in ("A4C", "A2C", "A3C"):
            return
        self._position = view
        self._control.set_position(view)
        self._curves_view.set_active_view(view)
        if self._result is not None:
            parts = self._meta_label.text().split("   |   ")
            parts = [p for p in parts if not p.startswith("Позиция:")]
            parts.append(f"Позиция: {self._position}")
            self._meta_label.setText("   |   ".join(parts))

    def show_curves(self) -> None:
        """Switch the stacked view to the strain-curves page."""
        self._stacked.setCurrentIndex(1)
        self._control._mode_curves.setChecked(True)
        if self._result is not None:
            self._curves_view.set_strain_data(self._result)

    def show_overview(self) -> None:
        """Switch the stacked view to the «3 Point Contour» overview page."""
        self._stacked.setCurrentIndex(2)
        self._control._mode_overview.setChecked(True)
        self._refresh_overview()

    def _on_position_selected(self, view: str) -> None:
        self._position = view
        self._curves_view.set_active_view(view)
        if self._result is not None and self._stacked.currentIndex() == 1:
            self._curves_view.set_strain_data(self._result)

    def _generate_synthetic_ecg(self, n_frames: int, hr_bpm: float) -> np.ndarray:
        """Generate synthetic ECG trace for visualization."""
        if n_frames < 2 or hr_bpm <= 0:
            return np.zeros(max(n_frames, 100))

        frame_time_s = 33.3 / 1000.0  # assuming ~30fps
        hr_hz = hr_bpm / 60.0
        period_frames = int(1.0 / (hr_hz * frame_time_s))

        ecg = np.zeros(n_frames)
        for i in range(n_frames):
            phase = (i % period_frames) / period_frames
            # Simple PQRST approximation
            if 0.0 <= phase < 0.1:  # P wave
                ecg[i] = 0.15 * np.sin(np.pi * phase / 0.1)
            elif 0.15 <= phase < 0.18:  # Q wave
                ecg[i] = -0.1
            elif 0.18 <= phase < 0.25:  # R wave
                ecg[i] = 1.0 * np.sin(np.pi * (phase - 0.18) / 0.07)
            elif 0.25 <= phase < 0.28:  # S wave
                ecg[i] = -0.2
            elif 0.35 <= phase < 0.5:  # T wave
                ecg[i] = 0.3 * np.sin(np.pi * (phase - 0.35) / 0.15)

        return ecg

    def _on_kernel_moved(self, view: str, kernel_idx: int, new_x: float, new_y: float) -> None:
        """Handle kernel movement from panel."""
        if self._result is None or self._result.tracked_ed_positions is None:
            return

        # Find the actual kernel index in the full array
        endo_indices = [i for i, k in enumerate(self._result.kernels) if k.layer == "endo"]
        if kernel_idx >= len(endo_indices):
            return

        actual_idx = endo_indices[kernel_idx]
        old_x = float(self._result.tracked_ed_positions[actual_idx, 0])
        old_y = float(self._result.tracked_ed_positions[actual_idx, 1])

        # Update position
        self._result.tracked_ed_positions[actual_idx, 0] = new_x
        self._result.tracked_ed_positions[actual_idx, 1] = new_y

        # Add to undo stack
        self._undo_stack.append((actual_idx, old_x, old_y, new_x, new_y))
        self._redo_stack.clear()  # Clear redo stack on new action

        # Update undo/redo button states
        self._control._btn_undo.setEnabled(len(self._undo_stack) > 0)
        self._control._btn_redo.setEnabled(False)

        logger.info("Kernel %d moved: (%.1f, %.1f) -> (%.1f, %.1f)", actual_idx, old_x, old_y, new_x, new_y)

    def _populate_qc_checkboxes(self, segment_strain: dict[int, float]) -> None:
        """Populate QC checkboxes only for segments with data."""
        # Remove placeholder
        if self._control._qc_placeholder is not None:
            self._control._qc_layout.removeWidget(self._control._qc_placeholder)
            self._control._qc_placeholder.deleteLater()
            self._control._qc_placeholder = None

        # Clear old checkboxes
        for cb in self._control._qc_checkboxes.values():
            self._control._qc_layout.removeWidget(cb)
            cb.deleteLater()
        self._control._qc_checkboxes.clear()

        # Create checkboxes for segments with data. Names come from the standard
        # AHA ids of the analysis; the level is spelled out ("Базальный
        # нижнеперегородочный"), unlike the short labels on the cine.
        for seg_id in sorted(segment_strain.keys()):
            seg_name = full_segment_label(seg_id)
            cb = QCheckBox(seg_name)
            cb.setChecked(True)
            cb.setStyleSheet("color: #e0e0e0; font-size: 10px;")
            cb.toggled.connect(lambda checked, sid=seg_id: self._control.qc_segment_toggled.emit(sid, checked))
            self._control._qc_layout.addWidget(cb)
            self._control._qc_checkboxes[seg_id] = cb

        # Add stretch at end
        self._control._qc_layout.addStretch()

    def _undo_kernel_move(self) -> None:
        """Undo the last kernel movement."""
        if not self._undo_stack or self._result is None:
            return

        idx, old_x, old_y, new_x, new_y = self._undo_stack.pop()

        # Restore position
        self._result.tracked_ed_positions[idx, 0] = old_x
        self._result.tracked_ed_positions[idx, 1] = old_y

        # Add to redo stack
        self._redo_stack.append((idx, old_x, old_y, new_x, new_y))

        # Update button states
        self._control._btn_undo.setEnabled(len(self._undo_stack) > 0)
        self._control._btn_redo.setEnabled(len(self._redo_stack) > 0)

        # Re-render
        self._update_panel_a4c()

    def _redo_kernel_move(self) -> None:
        """Redo the last undone kernel movement."""
        if not self._redo_stack or self._result is None:
            return

        idx, old_x, old_y, new_x, new_y = self._redo_stack.pop()

        # Apply position
        self._result.tracked_ed_positions[idx, 0] = new_x
        self._result.tracked_ed_positions[idx, 1] = new_y

        # Add to undo stack
        self._undo_stack.append((idx, old_x, old_y, new_x, new_y))

        # Update button states
        self._control._btn_undo.setEnabled(len(self._undo_stack) > 0)
        self._control._btn_redo.setEnabled(len(self._redo_stack) > 0)

        # Re-render
        self._update_panel_a4c()

    def _refresh_overview(self) -> None:
        """Re-render the «3 Point Contour» screen from ``self._study``.

        Called when the user switches to the overview tab and whenever a new
        view's result arrives. All numbers come from the study — there is no
        second GLS computation, no alternate average.
        """
        if self._study is None:
            return
        self._overview.set_study(self._study)

    def _capture_view_snapshot(
        self,
        result: StrainResult,
        frames: np.ndarray | None,
    ) -> ViewSnapshot:
        """Build a :class:`ViewSnapshot` from the worker result for this run.

        The snapshot holds references (not copies) to the ED frame and the
        contours/endo positions so the overview card can draw them without
        re-running the tracker. ``frames`` is kept by reference; the caller
        (viewer widget) owns the buffer.
        """
        view = str(getattr(result, "view", self._position) or self._position)
        ed_frame: np.ndarray | None = None
        ed_idx = int(getattr(result, "ed_index", 0) or 0)
        if frames is not None and frames.ndim >= 3 and 0 <= ed_idx < frames.shape[0]:
            ed_frame = frames[ed_idx]
        endo_indices = [i for i, k in enumerate(result.kernels) if k.layer == "endo"]
        endo_positions = None
        if result.tracked_ed_positions is not None and len(endo_indices) > 0:
            endo_positions = np.asarray(result.tracked_ed_positions)[endo_indices]
        ecg = result.ecg_trace_for_display
        frame_count = 0
        if frames is not None and frames.ndim >= 3:
            frame_count = int(frames.shape[0])
        elif result.longitudinal is not None:
            frame_count = len(result.longitudinal)
        return ViewSnapshot(
            view=view,
            ed_frame=ed_frame,
            ed_contour=None if result.ed_contour is None else np.asarray(result.ed_contour),
            es_contour=None if result.es_contour is None else np.asarray(result.es_contour),
            endo_positions_ed=endo_positions,
            ecg_trace=None if ecg is None else np.asarray(ecg),
            ecg_frame_time_ms=float(getattr(result, "frame_time_ms", 33.3) or 33.3),
            ed_index=ed_idx,
            es_index=int(getattr(result, "es_index", 0) or 0),
            frame_count=frame_count,
            heart_rate_bpm=float(getattr(result, "heart_rate_bpm", 0.0) or 0.0),
            kernels=[result.kernels[i] for i in endo_indices],
        )

    def _update_panel_a4c(self) -> None:
        """Re-render A4C panel with current data."""
        if self._result is None:
            return

        # Update kernels
        endo_indices = [i for i, k in enumerate(self._result.kernels) if k.layer == "endo"]
        endo_kernels = [self._result.kernels[i] for i in endo_indices]

        if self._result.tracked_ed_positions is not None:
            endo_positions = self._result.tracked_ed_positions[endo_indices]
            if self._result.es_ncc_scores is not None and self._result.es_valid_mask is not None:
                endo_ncc = self._result.es_ncc_scores[endo_indices]
                endo_valid = self._result.es_valid_mask[endo_indices]
                self._panel_a4c.show_kernels(endo_positions, endo_ncc, endo_valid)
            else:
                self._panel_a4c.show_kernels(endo_positions)

            # Update segment labels
            self._panel_a4c.show_segment_labels(endo_kernels, endo_positions)

    def _on_view_toggled(self, view: str, checked: bool) -> None:
        """Handle view checkbox toggle."""
        panel_map = {
            "A4C": self._panel_a4c,
            "A2C": self._panel_a2c,
            "DAO": self._panel_dao,
        }
        panel = panel_map.get(view)
        if panel is not None:
            panel.setVisible(checked)

    def _cycle_bullseye_palette(self) -> None:
        """Switch the bull's-eye palette (``C``) and keep the combo in sync."""
        key = self._panel_bullseye.cycle_palette()
        # Keep the overview bull's-eye on the same palette (same palette key
        # drives both targets — they must never disagree about the color map).
        self._overview.bullseye.set_palette(key)
        combo = getattr(self._control, "_cb_palette", None)
        if combo is not None:
            index = combo.findData(key)
            if index >= 0 and index != combo.currentIndex():
                blocker = QSignalBlocker(combo)
                combo.setCurrentIndex(index)
                del blocker

    def _on_display_mode_changed(self, mode: str) -> None:
        """Switch between contour, curves, overview and edit mode."""
        if mode == "contour":
            self._stacked.setCurrentIndex(0)
            self._panel_a4c.set_edit_mode(False)
        elif mode == "curves":
            self._stacked.setCurrentIndex(1)
            # Update curves view with current result
            if self._result is not None:
                self._curves_view.set_strain_data(self._result)
        elif mode == "overview":
            self._stacked.setCurrentIndex(2)
            self._panel_a4c.set_edit_mode(False)
            # Re-push the study so new per-view numbers / snapshots are drawn.
            self._refresh_overview()
        elif mode == "edit_mode":
            self._stacked.setCurrentIndex(0)
            self._panel_a4c.set_edit_mode(True)

    def _on_strain_metric_changed(self, metric: str) -> None:
        """Switch between deformation, strain rate, and peak strain display."""
        if self._result is None:
            return

        # Store current metric for re-rendering
        self._current_metric = metric

        # Update title info based on metric
        if metric == "deformation":
            title_info = f"GLS: {self._result.gls:.1f}%"
            unit = "%"
        elif metric == "strain_rate":
            title_info = "GLS Rate: --"
            unit = "1/s"
        elif metric == "peak":
            title_info = f"Peak GLS: {self._result.gls:.1f}%"
            unit = "%"
        else:
            return

        self._panel_a4c.set_title_info(title_info)

        # Update bull's eye if available
        if self._result.segment_strain:
            if metric == "strain_rate" and self._result.strain_rate is not None:
                # For SR mode, we would show strain rate per segment
                # For now, show strain as placeholder
                self._panel_bullseye.update_data(
                    self._result.segment_strain,
                    self._result.segment_quality,
                )
            else:
                self._panel_bullseye.update_data(
                    self._result.segment_strain,
                    self._result.segment_quality,
                )

    def _on_qc_segment_toggled(self, segment_id: int, accepted: bool) -> None:
        """Handle quality control checkbox toggle for a segment."""
        if accepted:
            self._qc_accepted_segments.add(segment_id)
        else:
            self._qc_accepted_segments.discard(segment_id)

        # Recalculate GLS excluding rejected segments
        if self._result is not None and self._result.segment_strain:
            accepted_strains = [
                strain for seg_id, strain in self._result.segment_strain.items() if seg_id in self._qc_accepted_segments
            ]
            if accepted_strains:
                gls_qc = float(np.min(accepted_strains))
            else:
                gls_qc = self._result.gls  # Fallback to original GLS

            # Update summary table with QC-adjusted GLS
            self._summary.update_values(gls=gls_qc)

            # Update bull's eye (mark rejected segments as gray)
            self._panel_bullseye.update_qc(
                self._result.segment_strain,
                self._result.segment_quality,
                self._qc_accepted_segments,
            )

    def _save_gold_contour(self) -> None:
        """Save the current ED endo contour as a gold-standard annotation (§11.2 п.1).

        Writes ``gold/lv_{study_uid}_{view}.json`` using the canonical schema
        consumed by the validation harness. The saved contour is exactly what
        is on screen (so manual kernel edits are captured); if the user has
        moved kernels, those edits are what gets saved, not the original
        auto-contour.
        """
        if self._result is None:
            return
        try:
            gold = contour_from_result(
                self._result,
                view=self._position,
                study_uid=self._study_uid,
                sop_instance_uid=self._sop_instance_uid,
                pixel_spacing_mm=self._pixel_spacing_mm,
            )
        except ValueError as exc:
            logger.warning("cannot save gold contour: %s", exc)
            return

        from PySide6.QtWidgets import QFileDialog

        default = str(default_path_for(self._study_uid or "unknown", self._position))
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("strain.save_gold_title"),
            default,
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            written = gold.save(pathlib.Path(path).parent, source_path=self._source_path)
            # Ensure the file name uses the final chosen path (save() writes
            # its own lv_* name inside the selected directory; rename if the
            # user picked a different file name).
            target = pathlib.Path(path)
            if written != target:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    target.unlink()
                written.replace(target)
                written = target
            logger.info("Saved gold ED contour → %s", written)
            self._meta_label.setText(
                self._meta_label.text() + f"   |   {tr('strain.gold_saved', path=str(written.name))}"
            )
        except OSError as exc:
            logger.error("Failed to save gold contour: %s", exc)

    def _load_gold_contour(self) -> None:
        """Load a gold-contour JSON and draw it over the current panel.

        This is a visual overlay (dashed yellow) for comparison against the
        current ED contour — it does not replace the tracked contour or
        recompute anything.
        """
        from PySide6.QtWidgets import QFileDialog

        default_dir = str(default_path_for(self._study_uid or "unknown", self._position).parent)
        path, _ = QFileDialog.getOpenFileName(self, tr("strain.load_gold_title"), default_dir, "JSON files (*.json)")
        if not path:
            return
        gold = load_for(pathlib.Path(path))
        if gold is None:
            return
        # Overlay as a dashed cyan contour on the currently visible panel.
        self._panel_a4c.show_es_contour(gold.points, color="#00e5ff", smooth=True)
        self._meta_label.setText(
            self._meta_label.text() + f"   |   {tr('strain.gold_loaded', view=gold.view, frame=str(gold.frame_index))}"
        )

    def _save_json(self) -> None:
        """Save deformation data to JSON file."""
        if self._result is None:
            return

        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, tr("strain.save_dialog_title"), "", "JSON files (*.json)")
        if not path:
            return

        import json

        # Export the analysis record with its definitions, frame anchors and QC,
        # not a bare list of numbers: a strain value without the definition and
        # the view it was measured in cannot be reproduced or compared with a
        # vendor report. Curves are included so the file is self-contained.
        analysis = getattr(self, "_analysis", None) or StrainAnalysis.from_result(self._result)
        analysis_dict = analysis.to_dict(with_curves=True)
        analysis_dict["qc_accepted_segments"] = sorted(int(seg) for seg in self._qc_accepted_segments)
        data = {
            "kind": "sonoforge.ste.analysis",
            "analysis": analysis_dict,
            "study": self._study.to_dict(),
        }
        # Keep the legacy flat keys for consumers written against the old file.
        legacy_keys = {
            "gls": self._result.gls,
            "heart_rate_bpm": self._result.heart_rate_bpm,
            "position": self._position,
            "ed_index": self._result.ed_index,
            "es_index": self._result.es_index,
            "avc_index": analysis.avc_index,
            "ess": analysis.ess,
            "time_to_peak_ms": analysis.time_to_peak_ms,
            "post_systolic_index": analysis.post_systolic_index,
            "drift_measured": analysis.drift,
            "qc_status": analysis.qc_status,
            "qc_reasons": list(analysis.qc_reasons),
            "kernels_accepted": self._result.kernels_accepted_count,
            "kernels_rejected": self._result.kernels_rejected_count,
            "kernels_total": self._result.kernels_total_count,
            "segment_strain": {str(k): v for k, v in (self._result.segment_strain or {}).items()},
            "segment_quality": {str(k): v for k, v in (self._result.segment_quality or {}).items()},
            "segment_ttp_ms": {str(k): v for k, v in (analysis.segment_ttp_ms or {}).items()},
            "segment_ess": {str(k): v for k, v in (analysis.segment_ess or {}).items()},
        }
        data.update(legacy_keys)

        # Add kernel positions if available
        if self._result.tracked_ed_positions is not None:
            data["kernel_positions_ed"] = self._result.tracked_ed_positions.tolist()
        if self._result.tracked_es_positions is not None:
            data["kernel_positions_es"] = self._result.tracked_es_positions.tolist()

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Saved deformation data to %s", path)

    def _export_png(self) -> None:
        """Export current view as PNG screenshot."""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, tr("strain.export_png_title"), "", "PNG files (*.png)")
        if not path:
            return

        # Capture the content area
        content = self._stacked.currentWidget()
        if content is None:
            return

        pixmap = content.grab()
        pixmap.save(path, "PNG")
        logger.info("Exported PNG to %s", path)

    def _export_csv(self) -> None:
        """Export the measured segments with their metrics to CSV.

        One row per standard AHA segment with the value, time to peak,
        end-systolic value, tracking quality, the view it came from and whether
        it passed QC — the table a report or a paper actually needs.
        """
        if self._result is None or self._result.segment_strain is None:
            return

        import csv

        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, tr("strain.export_csv_title"), "", "CSV files (*.csv)")
        if not path:
            return

        analysis = getattr(self, "_analysis", None) or StrainAnalysis.from_result(self._result)
        sources = self._study.segment_sources()

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Segment ID",
                    "Segment Name",
                    "Strain (%)",
                    "ESS (%)",
                    "Time to peak (ms)",
                    "Quality (NCC)",
                    "View",
                    "Accepted",
                ]
            )
            for seg_id in sorted(self._result.segment_strain.keys()):
                strain = self._result.segment_strain[seg_id]
                quality = (self._result.segment_quality or {}).get(seg_id, float("nan"))
                ess = analysis.segment_ess.get(seg_id)
                ttp = analysis.segment_ttp_ms.get(seg_id)
                accepted = seg_id in self._qc_accepted_segments
                writer.writerow(
                    [
                        seg_id,
                        segment_name(seg_id),
                        f"{strain:.2f}",
                        "" if ess is None else f"{ess:.2f}",
                        "" if ttp is None or not np.isfinite(ttp) else f"{ttp:.0f}",
                        "" if quality is None or not np.isfinite(quality) else f"{quality:.3f}",
                        sources.get(seg_id, self._analysis.view),
                        accepted,
                    ]
                )
            # Provenance block: definitions + anchors, so the file stands alone.
            writer.writerow([])
            writer.writerow(["# GLS definition", analysis.definition_gls])
            writer.writerow(["# ESS definition", analysis.definition_ess])
            writer.writerow(["# TTP definition", analysis.definition_ttp])
            writer.writerow(["# Layer", analysis.layer])
            writer.writerow(
                [
                    "# ROI sampling (kernel / node spacing, mm)",
                    f"{analysis.sampling_kernel_mm:.2f} / {analysis.sampling_node_spacing_mm:.2f}",
                ]
            )
            writer.writerow(["# Regularization", analysis.regularization])
            if analysis.segment_sides:
                writer.writerow(["# Segment sides", analysis.segment_sides])
            writer.writerow(
                [
                    "# LV translation compensation",
                    "on" if analysis.translation_compensation else "off",
                ]
            )
            writer.writerow(["# Frame rate (Hz)", f"{analysis.frame_rate_hz:.0f}"])
            writer.writerow(["# View", analysis.view])
            writer.writerow(["# ED frame", analysis.ed_index])
            writer.writerow(["# ES frame", analysis.es_index])
            writer.writerow(["# AVC frame", analysis.avc_index])
            writer.writerow(["# AVC source", analysis.avc_source])
            writer.writerow(["# QC status", analysis.qc_status])
            writer.writerow(["# QC reasons", "|".join(analysis.qc_reasons)])
            writer.writerow(["# Coverage", f"{analysis.qc_coverage:.3f}"])
            # Round-trip verification travels with the number it qualifies.
            rejected = getattr(analysis, "qc_rejected_fraction", None)
            unverified = getattr(analysis, "qc_unverified_fraction", None)
            closure_median = getattr(analysis, "qc_closure_median_mm", None)
            closure_p95 = getattr(analysis, "qc_closure_p95_mm", None)
            if rejected is not None:
                writer.writerow(["# Tracking verified (share of node-frames)", f"{1.0 - rejected:.3f}"])
                writer.writerow(["# Tracking rejected (share of node-frames)", f"{rejected:.3f}"])
            if unverified is not None:
                writer.writerow(["# Tracking without a verdict (share)", f"{unverified:.3f}"])
            if closure_median is not None and closure_p95 is not None:
                writer.writerow(["# Round-trip closure median/p95 (mm)", f"{closure_median:.2f}/{closure_p95:.2f}"])
            writer.writerow(["# GLS", "" if analysis.gls is None else f"{analysis.gls:.2f}"])
            writer.writerow(["# ESS", "" if analysis.ess is None else f"{analysis.ess:.2f}"])
            writer.writerow(["# Peak strain", "" if analysis.peak is None else f"{analysis.peak:.2f}"])
            writer.writerow(
                ["# GLS_AV", "" if self._study.gls_average() is None else f"{self._study.gls_average():.2f}"]
            )

        logger.info("Exported CSV to %s", path)

    def closeEvent(self, event) -> None:
        try:
            from PySide6.QtCore import QSettings

            settings = QSettings("SonoForge", "StrainWindow")
            settings.setValue("geometry", self.saveGeometry())
        except Exception:  # noqa: BLE001
            pass
        self.closed.emit()
        super().closeEvent(event)
