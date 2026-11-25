"""Worker/UI wiring of the LA strain (plan А.6, issue #644).

These need PySide6 (QRunnable worker, Qt widgets), so they stay out of the
pure-core lane; the curve/metrics domain is Qt-free and covered by
``test_la_strain.py``.
"""

from __future__ import annotations

import types

import numpy as np
import pytest

pytestmark = pytest.mark.gui

from tests.unit.test_la_strain import _arc_points, _synthetic_la_cine  # noqa: E402


class TestWorkerLaStage:
    """The worker's optional LA stage tracks the arc and stores the metrics."""

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

    def test_la_stage_tracks_and_computes_metrics(self) -> None:
        frames, ed_arc = _synthetic_la_cine()
        worker = self._worker(la_contour=ed_arc, la_contour_frame=0)
        assert worker._la_contour is not None
        assert worker._la_contour_frame == 0
        state = types.SimpleNamespace(
            preprocessed=frames,
            phase_start=0,
            track_ed_index=0,
            kernel_radius=6,
            config=__import__(
                "echo_personal_tool.domain.models.speckle", fromlist=["SpeckleConfig"]
            ).SpeckleConfig.preset_standard(),
        )
        worker._run_la_strain(state)
        assert state.la_strain_metrics is not None
        assert state.la_strain_curve is not None
        assert state.la_strain_curve[0] == pytest.approx(0.0, abs=1e-9)
        assert state.la_strain_metrics.reservoir_pct == pytest.approx(6.4, abs=4.0)
        assert state.la_tracking_quality is not None and state.la_tracking_quality > 0.5

    def test_la_stage_anchors_the_contours_frame(self) -> None:
        """An ES-drawn contour anchors tracking at its frame; the zero stays at ED."""
        frames, ed_arc = _synthetic_la_cine()
        worker = self._worker(la_contour=ed_arc, la_contour_frame=12)
        state = types.SimpleNamespace(
            preprocessed=frames,
            phase_start=0,
            track_ed_index=0,
            kernel_radius=6,
            config=__import__(
                "echo_personal_tool.domain.models.speckle", fromlist=["SpeckleConfig"]
            ).SpeckleConfig.preset_standard(),
        )
        worker._run_la_strain(state)
        assert state.la_strain_metrics is not None
        assert state.la_strain_curve[0] == pytest.approx(0.0, abs=1e-9)

    def test_no_contour_keeps_the_stage_off(self) -> None:
        worker = self._worker()
        assert worker._la_contour is None
        state = types.SimpleNamespace(preprocessed=None, phase_start=0, track_ed_index=0)
        worker._run_la_strain(state)
        assert state.la_strain_metrics is None
        assert state.la_strain_curve is None

    def test_contours_selection_picks_the_clip_la_contour(self) -> None:
        from echo_personal_tool.domain.models.contour import Contour

        arc = _arc_points(50.0, 40.0)
        la = Contour(
            phase="ed",
            view="A4C",
            chamber="LA",
            points=[(float(p[0]), float(p[1])) for p in arc],
            frame_index=3,
        )
        frames, _ = _synthetic_la_cine()
        worker = self._worker(la_contours=(la,))
        assert worker._la_contour is not None
        assert worker._la_contour_frame == 3
        state = types.SimpleNamespace(
            preprocessed=frames,
            phase_start=0,
            track_ed_index=0,
            kernel_radius=6,
            config=__import__(
                "echo_personal_tool.domain.models.speckle", fromlist=["SpeckleConfig"]
            ).SpeckleConfig.preset_standard(),
        )
        worker._run_la_strain(state)
        assert state.la_strain_metrics is not None


class TestStrainChain:
    """StrainResult → StrainAnalysis → StrainReport keeps the LA numbers."""

    def _result(self):
        from echo_personal_tool.domain.models.speckle import LaStrainMetrics, StrainResult

        curve = np.linspace(0.0, 20.0, 12)
        return StrainResult(
            longitudinal=np.linspace(0.0, -18.0, 12),
            radial=np.linspace(0.0, 20.0, 12),
            gls=-18.0,
            ed_index=0,
            es_index=5,
            la_strain_curve=curve,
            la_strain=LaStrainMetrics(
                reservoir_pct=25.0,
                conduit_pct=15.0,
                booster_pct=None,
                reservoir_index=8,
                a_onset_index=None,
                a_onset_source="none",
            ),
            la_tracking_quality=0.82,
        )

    def test_from_result_copies_la_fields(self) -> None:
        from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis

        analysis = StrainAnalysis.from_result(self._result(), view="A4C")
        assert analysis.la_reservoir_pct == pytest.approx(25.0)
        assert analysis.la_conduit_pct == pytest.approx(15.0)
        assert analysis.la_booster_pct is None
        assert analysis.la_tracking_quality == pytest.approx(0.82)

    def test_from_result_without_la_stays_none(self) -> None:
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
        assert analysis.la_reservoir_pct is None
        assert analysis.la_tracking_quality is None

    def test_report_aggregates_per_view_and_means(self) -> None:
        from echo_personal_tool.domain.models.contour import Contour
        from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis, StrainStudy

        a4c = StrainAnalysis.from_result(self._result(), view="A4C")
        a2c = StrainAnalysis.from_result(self._result(), view="A2C")
        a2c = a2c.__class__(
            **{**{f.name: getattr(a2c, f.name) for f in a2c.__dataclass_fields__.values()}, "la_conduit_pct": None}
        )
        study = StrainStudy(analyses={"A4C": a4c, "A2C": a2c})
        report = __import__(
            "echo_personal_tool.domain.models.ste_analysis", fromlist=["strain_report_from_study"]
        ).strain_report_from_study(study)
        assert report is not None
        assert ("A4C", 25.0, 15.0, None) in report.la_strain_by_view
        # reservoir mean over both views, conduit mean over the view that has it
        assert report.la_reservoir_pct == pytest.approx(25.0)
        assert report.la_conduit_pct == pytest.approx(15.0)
        assert report.la_booster_pct is None
        assert isinstance(Contour, type)  # keep the import used

    def test_report_without_la_has_no_section(self) -> None:
        from echo_personal_tool.domain.models.speckle import StrainResult
        from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis, StrainStudy, strain_report_from_study

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
        assert report.la_strain_by_view == ()
        assert report.la_reservoir_pct is None


class TestReportSection:
    """The LA strain rows reach the protocol in the left-atrium group."""

    def test_rows_in_the_left_atrium_group(self) -> None:
        from echo_personal_tool.domain.models.measurements import StrainReport
        from echo_personal_tool.domain.services.report_builder import GROUP_LEFT_ATRIUM, build_report_groups

        report = StrainReport(
            gls_by_view=(("A4C", -18.0),),
            qc_by_view=(("A4C", "valid"),),
            gls_average=-18.0,
            views_valid=("A4C",),
            la_strain_by_view=(("A4C", 25.0, 15.0, 12.0),),
            la_reservoir_pct=25.0,
            la_conduit_pct=15.0,
            la_booster_pct=12.0,
        )
        snapshot = __import__(
            "echo_personal_tool.domain.models.measurements", fromlist=["MeasurementSnapshot"]
        ).MeasurementSnapshot(strain=report, spacing_calibrated=True)
        groups = build_report_groups(snapshot, sex="M")
        la = next(group for group in groups if group.key == GROUP_LEFT_ATRIUM)
        labels = {value.label for value in la.values}
        assert any("LASr" in label for label in labels)
        assert any("LAScd" in label for label in labels)
        assert any("LASct" in label for label in labels)

    def test_no_la_measurement_adds_no_rows(self) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot, StrainReport
        from echo_personal_tool.domain.services.report_builder import build_report_groups

        report = StrainReport(
            gls_by_view=(("A4C", -18.0),),
            qc_by_view=(("A4C", "valid"),),
            gls_average=-18.0,
            views_valid=("A4C",),
        )
        groups = build_report_groups(MeasurementSnapshot(strain=report, spacing_calibrated=True), sex="M")
        assert not any("LASr" in value.label for group in groups for value in group.values)


class TestSummaryAndCurve:
    """The strain window shows the LA rows and overlays the LA curve."""

    def test_summary_rows_fill_and_blank(self, qtbot) -> None:
        from echo_personal_tool.ui.summary_table import SummaryTable

        table = SummaryTable()
        qtbot.addWidget(table)
        table.set_la_values(25.0, 15.0, None)
        labels = {key: table._rows[key][1].text() for key in ("la_lasr", "la_lascd", "la_lasct")}
        assert labels["la_lasr"] == "25.0%"
        assert labels["la_lascd"] == "15.0%"
        assert labels["la_lasct"] == "--"
        table.set_la_values(None, None, None)
        assert all(table._rows[key][1].text() == "--" for key in ("la_lasr", "la_lascd", "la_lasct"))

    def test_curve_panel_overlays_and_clears(self, qtbot) -> None:
        from echo_personal_tool.ui.strain_curves_view import SegmentCurvePanel

        panel = SegmentCurvePanel("A4C")
        qtbot.addWidget(panel)
        curve = np.linspace(0.0, 20.0, 12)
        panel.set_la_curve(curve)
        assert panel._la_item is not None
        panel.set_la_curve(None)
        assert panel._la_item is None
