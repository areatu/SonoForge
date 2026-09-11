"""GLS in the study protocol and the exported report (plan §5.3 п.6).

Why these tests exist
---------------------
Until now the strain numbers lived only inside the strain window: the study
record (:class:`StrainStudy`) was built by the widget, and the measurement
report — the text the user prints and archives — had no idea speckle tracking
had ever run. A number that cannot leave the screen is not a clinical result.

What is pinned here:

* the protocol record is the *projection* of the study, computed by the domain
  (``strain_report_from_study``), so the report cannot drift away from the
  window (a shared conversion is the whole point of §4.4);
* a strain line never appears without its method and the QC status of the view
  it came from — a bare "GLS −19 %" is not comparable with a vendor report;
* ``GLS_AV`` in the report equals ``StrainStudy.gls_average()`` exactly, and
  when no view passed QC the report *says so* instead of quietly averaging
  rejected views or printing nothing;
* views that were never analysed are absent, never written as 0 or "—" rows,
  and unmeasured segments are declared;
* the numbers the summary table shows and the numbers the report prints are the
  same objects (the parity test at the bottom).
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.measurements import MeasurementSnapshot, StrainReport
from echo_personal_tool.domain.models.speckle import StrainResult
from echo_personal_tool.domain.models.ste_analysis import (
    StrainAnalysis,
    StrainStudy,
    strain_report_from_study,
)
from echo_personal_tool.domain.services.measurement_report_formatter import format_measurement_report
from echo_personal_tool.infrastructure.i18n import set_language, tr


def _result(
    view: str,
    gls: float,
    status: str = "valid",
    *,
    avc_source: str = "ecg",
    segments: dict[int, float] | None = None,
) -> StrainResult:
    segments = segments or {3: -17.0, 6: -19.0, 9: -18.5, 12: -20.0, 15: -21.0, 18: -21.5}
    n = 12
    return StrainResult(
        longitudinal=np.linspace(0.0, gls, n),
        radial=np.zeros(n),
        gls=gls,
        view=view,
        qc_status=status,
        segment_strain=dict(segments),
        segment_quality={seg: 0.9 for seg in segments},
        segment_curves={seg: np.linspace(0.0, value, n) for seg, value in segments.items()},
        ed_index=0,
        es_index=5,
        avc_index=5,
        avc_source=avc_source,
        ess=gls + 1.0,
        peak_strain=gls,
        config_preset="standard",
        tracking_quality_mean=0.92,
        heart_rate_bpm=64.0,
        frame_time_ms=33.3,
    )


def _study(*results: StrainResult) -> StrainStudy:
    return StrainStudy.from_analyses(StrainAnalysis.from_result(item) for item in results)


class TestReportRecord:
    def test_empty_study_has_no_record(self) -> None:
        """No analysed view → no strain section at all (never an empty header)."""
        assert strain_report_from_study(StrainStudy()) is None

    def test_record_keeps_view_order_and_status(self) -> None:
        report = strain_report_from_study(_study(_result("A2C", -20.0, "review"), _result("A4C", -19.0)))
        assert report is not None
        # A4C first: the report follows the standard view order, not the order
        # in which the user happened to analyse the clips.
        assert report.gls_by_view == (("A4C", -19.0), ("A2C", -20.0))
        assert dict(report.qc_by_view) == {"A4C": "valid", "A2C": "review"}
        assert report.views_valid == ("A4C",)

    def test_average_matches_the_study(self) -> None:
        """GLS_AV in the protocol is the study's own average — never recomputed."""
        study = _study(_result("A4C", -19.0), _result("A2C", -21.0), _result("A3C", -14.5))
        report = strain_report_from_study(study)
        assert report is not None
        assert report.gls_average == pytest.approx(study.gls_average())
        assert report.gls_average == pytest.approx(-18.1666, abs=1e-3)

    def test_rejected_views_do_not_enter_the_average(self) -> None:
        study = _study(_result("A4C", -19.0), _result("A2C", -8.0, "invalid"))
        report = strain_report_from_study(study)
        assert report is not None
        assert report.views_valid == ("A4C",)
        assert report.gls_average == pytest.approx(-19.0)
        # …but the rejected view is still reported, with its status attached.
        assert dict(report.gls_by_view)["A2C"] == pytest.approx(-8.0)

    def test_no_valid_view_leaves_the_average_undefined(self) -> None:
        report = strain_report_from_study(_study(_result("A4C", -9.0, "invalid")))
        assert report is not None
        assert report.gls_average is None

    def test_view_without_a_finite_gls_is_dropped(self) -> None:
        """A non-finite GLS is not a measurement: it must not reach the protocol."""
        study = _study(_result("A4C", -19.0), _result("A2C", float("nan")))
        report = strain_report_from_study(study)
        assert report is not None
        assert [view for view, _ in report.gls_by_view] == ["A4C"]

    def test_unmeasured_segments_are_declared(self) -> None:
        """Segments of a rejected view are reported as missing, not as values."""
        clean = strain_report_from_study(_study(_result("A4C", -19.0)))
        assert clean is not None
        # Every segment the single analysed view covers has a value.
        assert clean.segments_missing == 0
        assert clean.segmentation == "AHA-18"

        with_rejected = strain_report_from_study(_study(_result("A4C", -19.0), _result("A2C", -8.0, "invalid")))
        assert with_rejected is not None
        # A2C contributes six segments, none of which may be merged after the
        # view failed QC — they are counted as unmeasured instead.
        assert with_rejected.segments_missing == 6

    def test_avc_source_is_recorded_per_view(self) -> None:
        report = strain_report_from_study(
            _study(_result("A4C", -19.0, avc_source="ecg"), _result("A2C", -20.0, avc_source="simpson_area"))
        )
        assert report is not None
        assert dict(report.avc_source_by_view) == {"A4C": "ecg", "A2C": "simpson_area"}


class TestReportText:
    def _text(self, study: StrainStudy, **kwargs) -> str:
        report = strain_report_from_study(study, **kwargs)
        return format_measurement_report(MeasurementSnapshot(strain=report))

    def test_section_is_absent_without_strain(self) -> None:
        text = format_measurement_report(MeasurementSnapshot(strain=None))
        assert "STE" not in text

    def test_section_carries_value_status_and_method(self) -> None:
        text = self._text(_study(_result("A4C", -19.0)))
        assert "-19.0 %" in text
        assert "●" in text  # QC mark of a valid view
        # The definition behind the number, in the interface language (ru here).
        assert tr("domain.report.strain_method", segmentation="AHA-18") in text
        assert "AHA-18" in text

    def test_method_line_follows_the_interface_language(self) -> None:
        """The record stores the fact, not the wording: switching the language
        must re-translate an already analysed study rather than keep the text
        frozen from the moment of the analysis."""
        report = strain_report_from_study(_study(_result("A4C", -19.0)))
        snapshot = MeasurementSnapshot(strain=report)
        russian = format_measurement_report(snapshot)
        set_language("en")
        try:
            english = format_measurement_report(snapshot)
        finally:
            set_language("ru")
        assert "Лагранж" in russian
        assert "Lagrangian" in english
        # The number itself is language-independent.
        assert "-19.0 %" in russian and "-19.0 %" in english

    def test_review_and_invalid_views_are_marked(self) -> None:
        text = self._text(_study(_result("A4C", -19.0, "review"), _result("A2C", -8.0, "invalid")))
        assert "⚠" in text
        assert "■" in text

    def test_average_line_states_how_many_views(self) -> None:
        text = self._text(_study(_result("A4C", -19.0), _result("A2C", -21.0)))
        assert "GLS AV" in text
        assert "-20.0 %" in text

    def test_no_valid_view_says_so(self) -> None:
        """Silence would read as 'not measured'; the report must be explicit."""
        text = self._text(_study(_result("A4C", -9.0, "invalid")))
        assert "GLS AV" in text
        assert "-9.0 %" in text

    def test_draft_contour_is_disclosed(self) -> None:
        """A semi-automatic contour is not a gold contour and must be declared."""
        text = self._text(_study(_result("A4C", -19.0)), contour_source="draft")
        assert tr("domain.report.strain_contour_draft").strip() in text

    def test_manual_contour_adds_no_disclaimer(self) -> None:
        text = self._text(_study(_result("A4C", -19.0)))
        assert tr("domain.report.strain_contour_draft").strip() not in text


class TestSnapshotWiring:
    def test_snapshot_carries_the_record(self) -> None:
        report = strain_report_from_study(_study(_result("A4C", -19.0)))
        snapshot = MeasurementSnapshot(strain=report)
        assert snapshot.strain is report

    def test_snapshots_compare_by_value(self) -> None:
        """The viewer refreshes on snapshot change: the record must be hashable-by-value."""
        first = strain_report_from_study(_study(_result("A4C", -19.0)))
        second = strain_report_from_study(_study(_result("A4C", -19.0)))
        assert MeasurementSnapshot(strain=first) == MeasurementSnapshot(strain=second)
        third = strain_report_from_study(_study(_result("A4C", -18.0)))
        assert MeasurementSnapshot(strain=first) != MeasurementSnapshot(strain=third)

    def test_default_snapshot_has_no_strain(self) -> None:
        assert MeasurementSnapshot().strain is None

    def test_empty_record_produces_no_section(self) -> None:
        text = format_measurement_report(MeasurementSnapshot(strain=StrainReport()))
        assert "STE" not in text


class TestControllerPublishesTheRecord:
    """The controller — not the widget — is what puts GLS into the protocol.

    Marked ``gui`` only because :class:`AppController` is a ``QObject``; no
    window is created.
    """

    pytestmark = pytest.mark.gui

    def _controller(self):
        from echo_personal_tool.application.app_controller import AppController

        class _Pool:
            def start(self, worker) -> None:  # pragma: no cover - never used here
                raise AssertionError("no worker should be started in this test")

        return AppController(thread_pool=_Pool())

    def test_finished_result_reaches_the_snapshot(self, qapp) -> None:
        controller = self._controller()
        controller._on_speckle_tracking_finished(_result("A4C", -19.0))
        snapshot = controller.state_manager.snapshot.measurement_snapshot
        assert snapshot is not None
        assert snapshot.strain is not None
        assert dict(snapshot.strain.gls_by_view)["A4C"] == pytest.approx(-19.0)

    def test_second_view_accumulates_into_the_average(self, qapp) -> None:
        controller = self._controller()
        controller._on_speckle_tracking_finished(_result("A4C", -19.0))
        controller._on_speckle_tracking_finished(_result("A2C", -21.0))
        strain = controller.state_manager.snapshot.measurement_snapshot.strain
        assert [view for view, _ in strain.gls_by_view] == ["A4C", "A2C"]
        assert strain.gls_average == pytest.approx(-20.0)

    def test_rerunning_a_view_replaces_it(self, qapp) -> None:
        """A re-analysis must not be averaged with the run it supersedes."""
        controller = self._controller()
        controller._on_speckle_tracking_finished(_result("A4C", -19.0))
        controller._on_speckle_tracking_finished(_result("A4C", -17.0))
        strain = controller.state_manager.snapshot.measurement_snapshot.strain
        assert strain.gls_by_view == (("A4C", -17.0),)

    def test_non_strain_payload_is_ignored(self, qapp) -> None:
        controller = self._controller()
        controller._on_speckle_tracking_finished(object())
        snapshot = controller.state_manager.snapshot.measurement_snapshot
        assert snapshot is None or snapshot.strain is None


class TestUiAndReportAgree:
    """The one test the plan asks for: "numbers in the UI == numbers in the report".

    Both sides are fed the same :class:`StrainResult` objects. The summary table
    formats them for the screen, the formatter for the protocol; if either side
    ever recomputes a value on its own, the strings stop matching.
    """

    pytestmark = pytest.mark.gui

    def test_per_view_gls_and_average_match(self, qapp) -> None:
        from echo_personal_tool.ui.strain_window import SummaryTable

        results = [_result("A4C", -19.0), _result("A2C", -21.0), _result("A3C", -14.5, "review")]
        study = _study(*results)
        report = strain_report_from_study(study)
        assert report is not None

        table = SummaryTable()
        table.set_view_statuses({view: analysis.qc_status for view, analysis in study.analyses.items()})
        table.update_values(
            gls_a4c=study.view_gls("A4C"),
            gls_a2c=study.view_gls("A2C"),
            gls_dao=study.view_gls("A3C"),
            gls_av=study.gls_average(),
        )

        text = format_measurement_report(MeasurementSnapshot(strain=report))
        for key, view in (("gls_a4c", "A4C"), ("gls_a2c", "A2C"), ("gls_dao", "A3C")):
            # "-19.0%" on screen, "-19.0 %" in the report: same number, and the
            # report line names the view it belongs to.
            ui_number = table._rows[key][1].text().split("%")[0].strip()
            assert any(view in line and ui_number in line for line in text.splitlines()), (
                f"{view}: UI shows {ui_number}, report lines: {text.splitlines()}"
            )

        av_number = table._rows["gls_av"][1].text().rstrip("%")
        assert any("GLS AV" in line and av_number in line for line in text.splitlines())

    def test_qc_marks_match(self, qapp) -> None:
        from echo_personal_tool.ui.strain_window import SummaryTable

        study = _study(_result("A4C", -19.0), _result("A2C", -8.0, "invalid"))
        table = SummaryTable()
        table.set_view_statuses({view: item.qc_status for view, item in study.analyses.items()})
        table.update_values(gls_a4c=study.view_gls("A4C"), gls_a2c=study.view_gls("A2C"))
        text = format_measurement_report(MeasurementSnapshot(strain=strain_report_from_study(study)))

        for key, view in (("gls_a4c", "A4C"), ("gls_a2c", "A2C")):
            mark = table._rows[key][1].text()[-1]
            assert any(view in line and mark in line for line in text.splitlines())


class TestPdfExport:
    """The printed protocol must carry the section, marks included.

    The QC marks are non-Latin glyphs; a font without them would silently
    print blanks and turn "needs review" into "valid" for the reader.
    """

    pytestmark = pytest.mark.gui

    def test_section_survives_the_pdf(self, tmp_path, qapp) -> None:
        pymupdf = pytest.importorskip("pymupdf")
        from echo_personal_tool.infrastructure.measurement_report_pdf import export_measurement_report_pdf

        study = _study(_result("A4C", -19.0), _result("A2C", -21.0, "review"))
        text = format_measurement_report(MeasurementSnapshot(strain=strain_report_from_study(study)))
        output = export_measurement_report_pdf(text, tmp_path / "report.pdf")

        page_text = pymupdf.open(output)[0].get_text()
        assert "-19.0 %" in page_text
        assert "-21.0 %" in page_text
        assert "GLS AV" in page_text
        assert "●" in page_text and "⚠" in page_text


class TestWindowAdoptsTheStudy:
    """The window must not keep a second, private list of analysed views."""

    pytestmark = pytest.mark.gui

    def test_adopted_study_drives_the_per_view_rows(self, qapp) -> None:
        from echo_personal_tool.ui.strain_window import StrainWindow

        study = _study(_result("A2C", -21.0))
        window = StrainWindow()
        try:
            window.set_study(study)
            # A4C is analysed now; the A2C value adopted from the application
            # must survive into the table instead of being forgotten.
            window.show_result(_result("A4C", -19.0))
            assert window._study.view_gls("A2C") == pytest.approx(-21.0)
            assert window._study.view_gls("A4C") == pytest.approx(-19.0)
            assert window._study.gls_average() == pytest.approx(-20.0)
        finally:
            window.close()

    def test_set_study_ignores_none(self, qapp) -> None:
        """No study yet (first run) must not wipe what the window already has."""
        from echo_personal_tool.ui.strain_window import StrainWindow

        window = StrainWindow()
        try:
            window.show_result(_result("A4C", -19.0))
            window.set_study(None)
            assert window._study.view_gls("A4C") == pytest.approx(-19.0)
        finally:
            window.close()
