"""Explicit accepted/excluded Doppler repeats and their statistics (issue 559)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib.resources import files

import jsonschema
import pytest

from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.measurements import DopplerFlowResult, DopplerResults, MeasurementSnapshot
from echo_personal_tool.domain.services.doppler_repeats import repeat_statistics
from echo_personal_tool.domain.services.report_builder import build_report_groups
from echo_personal_tool.infrastructure.measurement_codec import (
    FORMAT,
    SEMANTICS_VERSION,
    VERSION,
    dumps,
    loads,
)

_UTC = timezone.utc


def _peak(value: float, *, accepted: bool = True, label: str = "TR Vmax") -> DopplerPeakMarker:
    return DopplerPeakMarker(
        label=label,
        time_ms=0.0,
        velocity_cm_s=value,
        measurement_id=f"m{value}",
        accepted=accepted,
    )


def _dto(*peaks: DopplerPeakMarker) -> DopplerMeasurementDTO:
    return DopplerMeasurementDTO(peaks=peaks, intervals=(), traces=())


def test_repeat_statistics_split_accepted_and_selected_window() -> None:
    stats = repeat_statistics([300.0, 900.0, 310.0, 320.0], [True, False, True, True])

    assert stats.accepted == (300.0, 310.0, 320.0)
    assert stats.excluded == (900.0,)
    assert stats.selected == (300.0, 310.0, 320.0)
    assert stats.n == 3
    assert stats.mean == pytest.approx(310.0)
    assert stats.sd == pytest.approx(10.0)
    assert stats.cv_percent == pytest.approx(10.0 / 310.0 * 100.0)


def test_single_selected_value_has_no_sd_or_cv() -> None:
    stats = repeat_statistics([310.0, 900.0], [True, False])
    assert stats.n == 1
    assert stats.mean == pytest.approx(310.0)
    assert stats.sd is None
    assert stats.cv_percent is None


def test_compute_uses_only_accepted_peaks_and_traces() -> None:
    dto = _dto(_peak(300.0), _peak(900.0, accepted=False), _peak(320.0))
    flow = compute(dto).flow("TR")

    assert flow is not None
    assert flow.vmax_cm_s == pytest.approx(310.0)
    assert flow.vmax_stats.accepted == (300.0, 320.0)
    assert flow.vmax_stats.excluded == (900.0,)
    assert flow.vmax_stats.n == 2
    assert flow.vmax_stats.sd is not None
    assert flow.vmax_repeats == 3, "storage still reports every stored measurement"

    traces = (
        DopplerTrace("AV VTI", ((0.0, 0.0), (100.0, 100.0), (200.0, 0.0)), measurement_id="a"),
        DopplerTrace("AV VTI", ((300.0, 0.0), (400.0, 300.0), (500.0, 0.0)), measurement_id="b", accepted=False),
    )
    flow = compute(DopplerMeasurementDTO(peaks=(), intervals=(), traces=traces)).flow("AV")
    assert flow is not None
    assert flow.vti_cm == pytest.approx(10.0)
    assert flow.vti_stats.accepted_count == 1
    assert flow.vti_stats.excluded_count == 1


def test_interval_exclusion_removes_bad_rr_from_heart_rate() -> None:
    accepted = DopplerIntervalMarker("RR", 0.0, 1000.0, measurement_id="a")
    excluded = DopplerIntervalMarker("RR", 2000.0, 2600.0, measurement_id="b", accepted=False)
    dto = DopplerMeasurementDTO(peaks=(), intervals=(accepted, excluded), traces=())

    assert compute(dto).heart_rate_bpm == pytest.approx(60.0)


def test_report_uses_the_same_selected_count_and_spread() -> None:
    stats = repeat_statistics([300.0, 310.0, 320.0], [True, True, True])
    snapshot = MeasurementSnapshot(
        spacing_calibrated=True,
        doppler=DopplerResults(
            flow_results=(DopplerFlowResult(site="TR", vmax_cm_s=310.0, vmax_repeats=3, vmax_stats=stats, mode="PW"),),
        ),
    )

    groups = build_report_groups(snapshot, sex="M")
    row = next(value for group in groups for value in group.values if value.label == "Vmax ТР")

    assert row.sample_count == 3
    assert row.display_value == "310 (n=3) · SD 10.00 · CV 3.2%"


def test_document_roundtrip_keeps_exclusion_and_omits_default_flag() -> None:
    data = StudyMeasurementData(
        doppler_by_instance=(("1.2.3.4", _dto(_peak(300.0), _peak(900.0, accepted=False))),),
    )
    record = {
        "format": FORMAT,
        "schema_version": VERSION,
        "measurement_semantics_version": SEMANTICS_VERSION,
        "study_uid": "1.2.3.4",
        "revision": 1,
        "saved_at": datetime.now(_UTC).isoformat(),
        "sources": {"1.2.3.4": {"fingerprint": "a" * 64, "frames": 5, "spacing": [0.5, 0.6]}},
        "data": data,
    }

    wire = dumps(record).decode("utf-8")
    assert '"accepted":false' in wire
    assert loads(wire)["data"].doppler_by_instance[0][1].peaks[1].accepted is False
    schema = json.loads(
        files("echo_personal_tool.resources")
        .joinpath(f"measurement-storage-v{VERSION}.schema.json")
        .read_text(encoding="utf-8")
    )
    jsonschema.validate(json.loads(wire), schema)

    all_accepted = dumps(
        {
            **record,
            "data": StudyMeasurementData(doppler_by_instance=(("1.2.3.4", _dto(_peak(300.0))),)),
        }
    ).decode("utf-8")
    assert "accepted" not in json.loads(all_accepted)["data"]["doppler_by_instance"][0][1]["peaks"][0]
    assert loads(all_accepted)["data"].doppler_by_instance[0][1].peaks[0].accepted is True
