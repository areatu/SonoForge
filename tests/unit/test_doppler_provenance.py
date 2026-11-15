"""Lineage of derived Doppler aggregates and strain (issue 555, step 8.2).

A report row such as ``AV Vmax`` is the mean of several primary measurements,
and a GLS row is the tracking result of one endocardial contour.  The card
«откуда значение» must name the clip, frame and measurement identity behind
the aggregate; when the markers or the contour lineage were never recorded the
card must say so instead of inventing a source.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.application.study_measurement_session import with_doppler_source
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.measurements import (
    ContourLineage,
    DopplerFlowResult,
    DopplerResults,
    MeasurementSnapshot,
    StrainReport,
)
from echo_personal_tool.domain.models.result_provenance import Freshness
from echo_personal_tool.domain.models.speckle import StrainResult
from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis, StrainStudy, strain_report_from_study
from echo_personal_tool.domain.models.value_origin import (
    METHOD_DOPPLER_AGGREGATE,
    METHOD_STRAIN,
    REASON_NOT_RECORDED,
    ClipSource,
)
from echo_personal_tool.domain.services.doppler_provenance import doppler_flow_origin
from echo_personal_tool.domain.services.nomenclature import flow_label, strain_label
from echo_personal_tool.domain.services.report_builder import build_report_groups
from echo_personal_tool.infrastructure.i18n import set_language, tr
from echo_personal_tool.infrastructure.measurement_codec import (
    FORMAT,
    SEMANTICS_VERSION,
    VERSION,
    dumps,
    loads,
)

UID = "1.2.840.113619.2.55.3.9999.1"
UID2 = "1.2.840.113619.2.55.3.9999.2"


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


def _rows(snapshot: MeasurementSnapshot):
    return [value for group in build_report_groups(snapshot) for value in group.values]


def _row(snapshot: MeasurementSnapshot, label: str):
    return next(value for value in _rows(snapshot) if value.label == label)


def _doppler(dto: DopplerMeasurementDTO):
    return compute(dto)


# ── Doppler aggregates ─────────────────────────────────────────────────


def test_a_vmax_aggregate_cites_every_measurement_it_averaged() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(
            DopplerPeakMarker(
                label="AV Vmax",
                time_ms=10.0,
                velocity_cm_s=310.0,
                measurement_id="p-1",
                sop_instance_uid=UID,
                frame_index=4,
            ),
            DopplerPeakMarker(
                label="AV Vmax",
                time_ms=20.0,
                velocity_cm_s=290.0,
                measurement_id="p-2",
                sop_instance_uid=UID2,
                frame_index=7,
            ),
        ),
        intervals=(),
        traces=(),
    )
    row = _row(MeasurementSnapshot(doppler=_doppler(dto)), flow_label("AV", "Vmax"))
    origin = row.origin
    assert origin is not None
    assert origin.method_id == METHOD_DOPPLER_AGGREGATE
    assert origin.measurement_id == "p-1"
    assert origin.freshness == Freshness.FRESH.value
    assert {(clip.sop_instance_uid, clip.frame_index) for clip in origin.clips} == {(UID, 4), (UID2, 7)}
    assert len(origin.inputs) == 2
    assert all(item.source == "measured" for item in origin.inputs)
    assert all(item.value.endswith(("cm/s", "m/s")) for item in origin.inputs)


def test_pgmax_points_at_the_vmax_it_was_computed_from() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(
            DopplerPeakMarker(
                label="AV Vmax",
                time_ms=10.0,
                velocity_cm_s=300.0,
                measurement_id="p-1",
                sop_instance_uid=UID,
                frame_index=3,
            ),
        ),
        intervals=(),
        traces=(),
    )
    row = _row(MeasurementSnapshot(doppler=_doppler(dto)), flow_label("AV", "PGmax"))
    origin = row.origin
    assert origin is not None
    assert origin.method_id == METHOD_DOPPLER_AGGREGATE
    assert origin.inputs[0].id == "Vmax"
    assert origin.clips[0].sop_instance_uid == UID


def test_a_vti_trace_carries_its_clip_and_measurement_identity() -> None:
    trace = DopplerTrace(
        label="AV VTI",
        points=((0.0, 0.0), (100.0, 100.0), (200.0, 0.0)),
        measurement_id="t-1",
        sop_instance_uid=UID,
        frame_index=9,
    )
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=(trace,))
    row = _row(MeasurementSnapshot(doppler=_doppler(dto)), flow_label("AV", "VTI"))
    origin = row.origin
    assert origin is not None
    assert origin.method_id == METHOD_DOPPLER_AGGREGATE
    assert origin.measurement_id == "t-1"
    assert origin.clips[0].frame_index == 9


def test_vmean_lists_the_vti_and_et_it_was_derived_from() -> None:
    trace = DopplerTrace(
        label="AV VTI",
        points=((0.0, 0.0), (100.0, 100.0), (200.0, 0.0)),
        measurement_id="t-1",
        sop_instance_uid=UID,
        frame_index=9,
    )
    interval = DopplerIntervalMarker(
        label="AV ET",
        start_time_ms=500.0,
        end_time_ms=800.0,
        measurement_id="i-1",
        sop_instance_uid=UID,
        frame_index=9,
    )
    dto = DopplerMeasurementDTO(peaks=(), intervals=(interval,), traces=(trace,))
    row = _row(MeasurementSnapshot(doppler=_doppler(dto)), flow_label("AV", "Vmean"))
    origin = row.origin
    assert origin is not None
    identifiers = {item.id for item in origin.inputs}
    assert identifiers == {"VTI", "ET"}
    assert {clip.frame_index for clip in origin.clips} == {9}


def test_a_ratio_names_the_values_it_divides() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(
            DopplerPeakMarker(
                label="E",
                time_ms=10.0,
                velocity_cm_s=80.0,
                measurement_id="e-1",
                sop_instance_uid=UID,
                frame_index=1,
            ),
            DopplerPeakMarker(
                label="A",
                time_ms=20.0,
                velocity_cm_s=100.0,
                measurement_id="a-1",
                sop_instance_uid=UID,
                frame_index=1,
            ),
        ),
        intervals=(),
        traces=(),
    )
    row = _row(MeasurementSnapshot(doppler=_doppler(dto)), tr("result.mv_ea_ratio"))
    origin = row.origin
    assert origin is not None
    assert origin.method_id == METHOD_DOPPLER_AGGREGATE
    assert [item.id for item in origin.inputs] == ["E", "A"]
    assert origin.measurement_id == "e-1"


def test_an_aggregate_without_markers_is_not_recorded() -> None:
    """Old documents carry the numbers but not the measurements behind them."""
    doppler = DopplerResults(flow_results=(DopplerFlowResult(site="TR", vmax_cm_s=280.0),))
    row = _row(MeasurementSnapshot(doppler=doppler), flow_label("TR", "Vmax"))
    origin = row.origin
    assert origin is not None
    assert origin.method_id == METHOD_DOPPLER_AGGREGATE
    assert origin.recorded is False
    assert origin.reason == REASON_NOT_RECORDED
    assert origin.freshness == Freshness.UNVERIFIED.value

    direct = doppler_flow_origin(doppler, doppler.flow_results[0], "Vmax")
    assert direct.method_id == METHOD_DOPPLER_AGGREGATE
    assert direct.recorded is False


def test_the_session_stamps_the_clip_and_frame_once() -> None:
    marker = DopplerPeakMarker(label="E", time_ms=1.0, velocity_cm_s=70.0, measurement_id="e-1")
    dto = with_doppler_source(
        DopplerMeasurementDTO(peaks=(marker,), intervals=(), traces=()),
        UID,
        5,
    )
    assert dto.peaks[0].sop_instance_uid == UID
    assert dto.peaks[0].frame_index == 5

    previously_stamped = DopplerPeakMarker(
        label="A",
        time_ms=2.0,
        velocity_cm_s=60.0,
        measurement_id="a-1",
        sop_instance_uid=UID2,
        frame_index=2,
    )
    kept = with_doppler_source(
        DopplerMeasurementDTO(peaks=(previously_stamped,), intervals=(), traces=()),
        UID,
        5,
    )
    assert kept.peaks[0].sop_instance_uid == UID2
    assert kept.peaks[0].frame_index == 2


# ── strain ─────────────────────────────────────────────────────────────


def _strain_report() -> StrainReport:
    return StrainReport(
        gls_by_view=(("A4C", -19.0), ("A2C", -18.0)),
        qc_by_view=(("A4C", "valid"), ("A2C", "valid")),
        gls_average=-18.5,
        views_valid=("A4C", "A2C"),
        segmentation="AHA-18",
        lineage_by_view=(
            ("A4C", ContourLineage("c-1", 2, UID, 12)),
            ("A2C", ContourLineage("c-2", 0, UID2, 4)),
        ),
    )


def test_a_per_view_gls_cites_its_contour_clip_and_frame() -> None:
    row = _row(MeasurementSnapshot(strain=_strain_report()), strain_label("A4C"))
    origin = row.origin
    assert origin is not None
    assert origin.method_id == METHOD_STRAIN
    assert origin.measurement_id == "c-1"
    assert origin.clips == (ClipSource(UID, 12),)


def test_the_gls_average_lists_the_views_that_entered_it() -> None:
    row = _row(
        MeasurementSnapshot(strain=_strain_report()),
        tr("domain.report.strain_gls_av", n="2"),
    )
    origin = row.origin
    assert origin is not None
    assert origin.method_id == METHOD_STRAIN
    assert {clip.sop_instance_uid for clip in origin.clips} == {UID, UID2}
    assert {item.id for item in origin.inputs} == {"GLS A4C", "GLS A2C"}


def test_strain_without_a_recorded_contour_stays_unverified() -> None:
    report = strain_report_from_study(
        StrainStudy().with_view(StrainAnalysis.from_result(StrainResult(longitudinal=None, radial=None, gls=-19.0)))
    )
    row = _row(MeasurementSnapshot(strain=report), strain_label("A4C"))
    origin = row.origin
    assert origin is not None
    assert origin.method_id == METHOD_STRAIN
    assert origin.recorded is False
    assert origin.freshness == Freshness.UNVERIFIED.value


def test_a_strain_analysis_keeps_the_contour_lineage_it_was_launched_from() -> None:
    result = StrainResult(longitudinal=None, radial=None, gls=-20.0)
    source = ContourLineage("c-9", 3, UID, 11)
    analysis = StrainAnalysis.from_result(result, source=source)
    assert analysis.source_contour == source

    empty = StrainAnalysis.from_result(result)
    assert empty.source_contour is None


def test_the_measurement_document_round_trips_the_source_lineage() -> None:
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementData

    dto = DopplerMeasurementDTO(
        peaks=(
            DopplerPeakMarker(
                label="E",
                time_ms=1.0,
                velocity_cm_s=70.0,
                measurement_id="e-1",
                sop_instance_uid=UID,
                frame_index=2,
            ),
        ),
        intervals=(),
        traces=(),
    )
    record = {
        "format": FORMAT,
        "schema_version": VERSION,
        "measurement_semantics_version": SEMANTICS_VERSION,
        "study_uid": "1.2.3",
        "revision": 1,
        "saved_at": "2026-11-12T00:00:00+00:00",
        "sources": {UID: {"fingerprint": "a" * 64, "frames": 5, "spacing": [0.5, 0.6]}},
        "data": StudyMeasurementData(
            doppler_by_instance=((UID, dto),),
            strain=_strain_report(),
        ),
    }
    loaded = loads(dumps(record))["data"]
    assert loaded.strain is not None
    assert loaded.strain.lineage_by_view == (
        ("A4C", ContourLineage("c-1", 2, UID, 12)),
        ("A2C", ContourLineage("c-2", 0, UID2, 4)),
    )
    peak = loaded.doppler_by_instance[0][1].peaks[0]
    assert peak.sop_instance_uid == UID
    assert peak.frame_index == 2


def test_the_strain_export_keeps_the_contour_lineage() -> None:
    result = StrainResult(longitudinal=None, radial=None, gls=-20.0)
    analysis = StrainAnalysis.from_result(result, source=ContourLineage("c-9", 3, UID, 11))
    payload = analysis.to_dict()
    assert payload["source_contour"] == {
        "measurement_id": "c-9",
        "revision": 3,
        "sop_instance_uid": UID,
        "frame_index": 11,
    }

    assert StrainAnalysis.from_result(result).to_dict()["source_contour"] is None
