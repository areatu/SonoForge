"""GLS in the active study protocol and structured report (plan §5.3 п.6).

The tests keep the domain record as the single source for strain report values,
check that the controller publishes it, and compare the displayed study values
with the rows assembled by the production ``ReportDocument`` builder. The PDF
integration check uses the same structured document that the report dialog
previews and exports; no test exercises the removed legacy text formatter.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.speckle import StrainResult
from echo_personal_tool.domain.models.ste_analysis import (
    StrainAnalysis,
    StrainStudy,
    strain_report_from_study,
)


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
    """The active structured report carries the study's per-view values."""

    pytestmark = pytest.mark.gui

    def test_per_view_gls_and_average_match(self, qapp) -> None:
        from echo_personal_tool.domain.services.nomenclature import strain_label
        from echo_personal_tool.domain.services.report_builder import GROUP_LEFT_VENTRICLE, build_report_document
        from echo_personal_tool.infrastructure.i18n import tr
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

        document = build_report_document(MeasurementSnapshot(strain=report))
        groups = {group.key: group for group in document.groups}
        rows = {value.label: value for value in groups[GROUP_LEFT_VENTRICLE].values}
        for key, view in (("gls_a4c", "A4C"), ("gls_a2c", "A2C"), ("gls_dao", "A3C")):
            ui_number = table._rows[key][1].text().split("%")[0].strip()
            assert rows[strain_label(view)].value == ui_number

        av_number = table._rows["gls_av"][1].text().rstrip("%")
        average_label = tr("domain.report.strain_gls_av", n=str(len(report.views_valid)))
        assert rows[average_label].value == av_number
        assert any("●" in note for note in groups[GROUP_LEFT_VENTRICLE].notes)

    def test_active_report_keeps_qc_method_and_provenance_notes(self, qapp) -> None:
        from echo_personal_tool.domain.services.report_builder import GROUP_LEFT_VENTRICLE, build_report_document
        from echo_personal_tool.infrastructure.i18n import tr, tr_plural

        report = strain_report_from_study(
            _study(_result("A4C", -19.0), _result("A2C", -8.0, "invalid", avc_source="simpson_area")),
            contour_source="draft",
        )
        assert report is not None
        report = replace(report, segments_missing=2)
        document = build_report_document(MeasurementSnapshot(strain=report))
        group = next(item for item in document.groups if item.key == GROUP_LEFT_VENTRICLE)
        notes = group.notes

        assert any("●" in note and tr("strain.qc_status_valid") in note for note in notes)
        assert any("■" in note and tr("strain.qc_status_invalid") in note for note in notes)
        method = tr("domain.report.strain_method", segmentation=report.segmentation)
        assert tr("domain.report.method", method=method).strip() in notes
        assert any("A4C:" in note and "A2C:" in note for note in notes)
        assert tr("domain.report.strain_contour_draft").strip() in notes
        assert tr_plural("domain.report.strain_segments_missing", 2).strip() in notes

        rejected = strain_report_from_study(_study(_result("A4C", -9.0, "invalid")))
        rejected_document = build_report_document(MeasurementSnapshot(strain=rejected))
        rejected_group = next(item for item in rejected_document.groups if item.key == GROUP_LEFT_VENTRICLE)
        assert tr("domain.report.strain_no_average").strip() in rejected_group.notes


class TestPdfExport:
    """The actual structured report PDF contains the values shown in the UI."""

    pytestmark = pytest.mark.gui

    def test_section_survives_the_pdf(self, tmp_path, qapp) -> None:
        pymupdf = pytest.importorskip("pymupdf")
        from echo_personal_tool.domain.services.report_builder import GROUP_LEFT_VENTRICLE, build_report_document
        from echo_personal_tool.infrastructure.i18n import tr
        from echo_personal_tool.infrastructure.measurement_report_pdf import export_report_document_pdf

        study = _study(_result("A4C", -19.0), _result("A2C", -21.0, "review"))
        report = strain_report_from_study(study)
        document = build_report_document(MeasurementSnapshot(strain=report))
        expected = {
            value.value for group in document.groups if group.key == GROUP_LEFT_VENTRICLE for value in group.values
        }
        output = export_report_document_pdf(document, tmp_path / "report.pdf")

        with pymupdf.open(output) as pdf:
            page_text = "\n".join(page.get_text() for page in pdf)
        assert expected <= set(page_text.split())
        assert "⚠" in page_text
        assert tr("strain.qc_status_review") in page_text


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

    def test_set_study_rejects_a_stand_in_object(self, qapp) -> None:
        """A duck-typed stand-in must be refused at the door, not deep inside.

        The window asks the application for the study, and a test double (or a
        stubbed controller) answers every call with another double. Accepting
        it here would postpone the failure until ``GLS_AV`` is formatted —
        ``unsupported format string passed to MagicMock.__format__`` — far away
        from the object that actually caused it. This is exactly how the first
        version of the wiring broke the ubuntu CI job.
        """
        from unittest.mock import MagicMock

        from echo_personal_tool.ui.strain_window import StrainWindow

        window = StrainWindow()
        try:
            window.show_result(_result("A4C", -19.0))
            window.set_study(MagicMock())
            assert window._study.view_gls("A4C") == pytest.approx(-19.0)
            # And the table still renders: no mock reaches the format string.
            window.show_result(_result("A2C", -21.0))
            assert window._study.gls_average() == pytest.approx(-20.0)
        finally:
            window.close()
