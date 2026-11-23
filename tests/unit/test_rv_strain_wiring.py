"""Worker/UI wiring of the RV free-wall strain (plan А.7, issue #645).

These need PySide6 (QRunnable worker, Qt widgets), so they stay out of the
pure-core lane; the curve/metrics domain is Qt-free and covered by
``test_rv_strain.py``.
"""

from __future__ import annotations

import types

import numpy as np
import pytest

pytestmark = pytest.mark.gui

from tests.unit.test_rv_strain import _synthetic_rv_cine, _wall_points  # noqa: E402


def _rv_wall_contour(frame_index: int, phase: str = "ed", view: str = "A4C"):
    from echo_personal_tool.domain.models.contour import RV_FREE_WALL_CHAMBER, Contour

    return Contour(
        phase=phase,
        view=view,
        chamber=RV_FREE_WALL_CHAMBER,
        points=[(float(p[0]), float(p[1])) for p in _wall_points()],
        frame_index=frame_index,
    )


class TestWorkerRvStage:
    """The worker's optional RV stage tracks the wall and stores the GLS."""

    def _worker(self, **kwargs: object):
        from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker
        from echo_personal_tool.domain.models.speckle import MyocardialZone

        theta = np.linspace(0.0, np.pi, 12)
        zone = MyocardialZone(
            endo_points=np.column_stack([100 + 40 * np.cos(theta), 150 + 50 * np.sin(theta)]),
            epi_points=np.column_stack([100 + 52 * np.cos(theta), 150 + 62 * np.sin(theta)]),
            thickness_mm=8.0,
            pixel_spacing=(0.5, 0.5),
        )
        return SpeckleTrackingWorker(
            frames=None,
            zone=zone,
            pixel_spacing=(0.5, 0.5),
            **kwargs,  # type: ignore[arg-type]
        )

    def _state(self, frames):
        from echo_personal_tool.domain.models.speckle import SpeckleConfig

        return types.SimpleNamespace(
            preprocessed=frames,
            phase_start=0,
            track_ed_index=0,
            local_es=10,
            kernel_radius=6,
            config=SpeckleConfig.preset_standard(),
        )

    def test_rv_stage_tracks_and_computes_gls(self) -> None:
        frames, wall, expected = _synthetic_rv_cine()
        worker = self._worker(rv_contour=wall, rv_contour_frame=0)
        assert worker._rv_contour is not None
        assert worker._rv_contour_frame == 0
        state = self._state(frames)
        worker._run_rv_strain(state)
        assert state.rv_strain_metrics is not None
        assert state.rv_strain_curve is not None
        assert state.rv_strain_curve[0] == pytest.approx(0.0, abs=1e-9)
        assert state.rv_strain_metrics.gls_pct == pytest.approx(expected, abs=4.0)
        assert state.rv_tracking_quality is not None and state.rv_tracking_quality > 0.5

    def test_rv_stage_anchors_the_traces_frame(self) -> None:
        """An ES-drawn trace anchors tracking at its frame; the zero stays at ED."""
        frames, wall, _expected = _synthetic_rv_cine()
        worker = self._worker(rv_contour=wall, rv_contour_frame=12)
        state = self._state(frames)
        worker._run_rv_strain(state)
        assert state.rv_strain_metrics is not None
        assert state.rv_strain_curve[0] == pytest.approx(0.0, abs=1e-9)

    def test_no_trace_keeps_the_stage_off(self) -> None:
        worker = self._worker()
        assert worker._rv_contour is None
        state = types.SimpleNamespace(preprocessed=None, phase_start=0, track_ed_index=0)
        worker._run_rv_strain(state)
        assert state.rv_strain_metrics is None
        assert state.rv_strain_curve is None

    def test_contours_selection_picks_the_free_wall_trace(self) -> None:
        from echo_personal_tool.domain.models.contour import Contour

        trace = _rv_wall_contour(3)
        fac = Contour(
            phase="ed",
            view="A4C",
            chamber="RV",
            points=[(float(p[0]), float(p[1])) for p in _wall_points()],
            frame_index=6,
        )
        frames, _wall, _expected = _synthetic_rv_cine()
        worker = self._worker(rv_contours=(fac, trace))
        assert worker._rv_contour is not None
        assert worker._rv_contour_frame == 3
        state = self._state(frames)
        worker._run_rv_strain(state)
        assert state.rv_strain_metrics is not None


class TestStrainChain:
    """StrainResult → StrainAnalysis → StrainReport keeps the RV number."""

    def _result(self):
        from echo_personal_tool.domain.models.speckle import RvStrainMetrics, StrainResult

        curve = np.linspace(0.0, -20.0, 12)
        return StrainResult(
            longitudinal=np.linspace(0.0, -18.0, 12),
            radial=np.linspace(0.0, 20.0, 12),
            gls=-18.0,
            ed_index=0,
            es_index=5,
            rv_strain_curve=curve,
            rv_strain=RvStrainMetrics(gls_pct=-20.0, gls_index=6),
            rv_tracking_quality=0.88,
        )

    def test_from_result_copies_rv_fields(self) -> None:
        from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis

        analysis = StrainAnalysis.from_result(self._result(), view="A4C")
        assert analysis.rv_gls_pct == pytest.approx(-20.0)
        assert analysis.rv_tracking_quality == pytest.approx(0.88)

    def test_from_result_without_rv_stays_none(self) -> None:
        from echo_personal_tool.domain.models.speckle import StrainResult
        from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis

        bare = StrainResult(
            longitudinal=np.linspace(0.0, -18.0, 12),
            radial=np.linspace(0.0, 20.0, 12),
            gls=-18.0,
            ed_index=0,
            es_index=5,
        )
        analysis = StrainAnalysis.from_result(bare, view="A4C")
        assert analysis.rv_gls_pct is None
        assert analysis.rv_tracking_quality is None

    def test_report_aggregates_per_view_and_mean(self) -> None:
        from echo_personal_tool.domain.models.ste_analysis import (
            StrainAnalysis,
            StrainStudy,
            strain_report_from_study,
        )

        a4c = StrainAnalysis.from_result(self._result(), view="A4C")
        a2c = StrainAnalysis.from_result(self._result(), view="A2C")
        fields = {f.name: getattr(a2c, f.name) for f in a2c.__dataclass_fields__.values()}
        fields["rv_gls_pct"] = -24.0
        a2c = a2c.__class__(**fields)
        study = StrainStudy(analyses={"A4C": a4c, "A2C": a2c})
        report = strain_report_from_study(study)
        assert report is not None
        assert ("A4C", -20.0) in report.rv_strain_by_view
        assert ("A2C", -24.0) in report.rv_strain_by_view
        assert report.rv_gls_pct == pytest.approx(-22.0)

    def test_report_without_rv_has_no_section(self) -> None:
        from echo_personal_tool.domain.models.speckle import StrainResult
        from echo_personal_tool.domain.models.ste_analysis import (
            StrainAnalysis,
            StrainStudy,
            strain_report_from_study,
        )

        bare = StrainResult(
            longitudinal=np.linspace(0.0, -18.0, 12),
            radial=np.linspace(0.0, 20.0, 12),
            gls=-18.0,
            ed_index=0,
            es_index=5,
        )
        study = StrainStudy(analyses={"A4C": StrainAnalysis.from_result(bare, view="A4C")})
        report = strain_report_from_study(study)
        assert report is not None
        assert report.rv_strain_by_view == ()
        assert report.rv_gls_pct is None


class TestReportSection:
    """The RV strain row reaches the protocol in the right-ventricle group."""

    def test_row_in_the_right_ventricle_group(self) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot, StrainReport
        from echo_personal_tool.domain.services.report_builder import GROUP_RIGHT_VENTRICLE, build_report_groups

        report = StrainReport(
            gls_by_view=(("A4C", -18.0),),
            qc_by_view=(("A4C", "valid"),),
            gls_average=-18.0,
            views_valid=("A4C",),
            rv_strain_by_view=(("A4C", -20.0),),
            rv_gls_pct=-20.0,
        )
        groups = build_report_groups(MeasurementSnapshot(strain=report, spacing_calibrated=True), sex="M")
        rv = next(group for group in groups if group.key == GROUP_RIGHT_VENTRICLE)
        labels = {value.label for value in rv.values}
        # The Latin abbreviations lead the label in every language (Q-03).
        assert any("RV GLS" in label for label in labels)

    def test_no_rv_measurement_adds_no_rows(self) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot, StrainReport
        from echo_personal_tool.domain.services.report_builder import build_report_groups

        report = StrainReport(
            gls_by_view=(("A4C", -18.0),),
            qc_by_view=(("A4C", "valid"),),
            gls_average=-18.0,
            views_valid=("A4C",),
        )
        groups = build_report_groups(MeasurementSnapshot(strain=report, spacing_calibrated=True), sex="M")
        assert not any("RV GLS" in value.label for group in groups for value in group.values)


class TestSummaryAndCurve:
    """The strain window shows the RV row and overlays the wall curve."""

    def test_summary_row_fills_and_blanks(self, qtbot) -> None:
        from echo_personal_tool.ui.summary_table import SummaryTable

        table = SummaryTable()
        qtbot.addWidget(table)
        table.set_rv_values(-20.0)
        assert table._rows["rv_gls"][1].text() == "-20.0%"
        table.set_rv_values(None)
        assert table._rows["rv_gls"][1].text() == "--"

    def test_curve_panel_overlays_and_clears(self, qtbot) -> None:
        from echo_personal_tool.ui.strain_curves_view import SegmentCurvePanel

        panel = SegmentCurvePanel("A4C")
        qtbot.addWidget(panel)
        curve = np.linspace(0.0, -20.0, 12)
        panel.set_rv_curve(curve)
        assert panel._rv_item is not None
        panel.set_rv_curve(None)
        assert panel._rv_item is None
