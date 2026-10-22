"""Decision D-23: repeated measurements of one Doppler parameter.

The protocol measures a parameter (TR Vmax, VTI, ET, …) on several consecutive
beats and reports the mean of the last three.  These tests pin the shared rules:
the mean window, the storage bound, the measurement identity that keeps the
merge idempotent, and the aggregation across frames of one clip.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from echo_personal_tool.application.study_measurement_session import (
    StudyMeasurementData,
    StudyMeasurementSessionStore,
    merge_doppler_dtos,
    merge_doppler_peaks,
)
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.models.doppler import (
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.services.doppler_repeats import (
    MAX_REPEATS_PER_PARAMETER,
    REPORT_WINDOW,
    keep_newest_per_label,
    mean_of_last,
    merge_newest_wins,
    new_measurement_id,
    report_sample_count,
)

UID = "1.2.3"
SOP = "1.2.3.4"


def _peak(label: str, velocity: float, *, index: int = 0) -> DopplerPeakMarker:
    return DopplerPeakMarker(label=label, time_ms=10.0 * index, velocity_cm_s=velocity, measurement_id=f"m{index}")


# ── mean_of_last ────────────────────────────────────────────────────


def test_report_window_is_three() -> None:
    assert REPORT_WINDOW == 3


def test_mean_of_last_uses_most_recent_values() -> None:
    assert mean_of_last([]) is None
    assert mean_of_last([120.0]) == 120.0
    assert mean_of_last([120.0, 140.0]) == 130.0
    assert mean_of_last([120.0, 140.0, 160.0]) == pytest.approx(140.0)
    # A fourth measurement pushes the oldest out of the window.
    assert mean_of_last([100.0, 120.0, 140.0, 160.0]) == pytest.approx(140.0)
    assert mean_of_last([100.0, 120.0, 140.0, 160.0, 180.0]) == pytest.approx(160.0)


def test_mean_of_last_accepts_other_windows() -> None:
    assert mean_of_last([100.0, 200.0, 300.0], window=1) == 300.0


@pytest.mark.parametrize("stored, expected_in_report", [(0, 0), (1, 1), (2, 2), (3, 3), (4, 3), (10, 3)])
def test_report_sample_count_matches_last_three_window(stored: int, expected_in_report: int) -> None:
    assert report_sample_count(stored) == expected_in_report


# ── storage bound ───────────────────────────────────────────────────


def test_keep_newest_per_label_drops_oldest_repeats() -> None:
    markers = tuple(_peak("TR Vmax", 100.0 + index, index=index) for index in range(MAX_REPEATS_PER_PARAMETER + 2))

    kept = keep_newest_per_label(markers, label_of=lambda marker: marker.label)

    assert len(kept) == MAX_REPEATS_PER_PARAMETER
    assert kept == markers[2:]
    assert kept[-1].measurement_id == markers[-1].measurement_id


def test_keep_newest_per_label_counts_labels_separately() -> None:
    markers = (
        _peak("TR Vmax", 280.0, index=0),
        _peak("AV Vmax", 400.0, index=1),
        _peak("TR Vmax", 300.0, index=2),
    )

    kept = keep_newest_per_label(markers, label_of=lambda marker: marker.label, limit=1)

    assert [marker.velocity_cm_s for marker in kept] == [400.0, 300.0]


# ── identity-aware merge ────────────────────────────────────────────


def test_merge_replaces_an_edited_measurement_in_place() -> None:
    original = _peak("TR Vmax", 280.0, index=0)
    edited = replace(original, velocity_cm_s=310.0)

    merged = merge_newest_wins(
        (original,),
        (edited,),
        identity_of=lambda marker: (marker.label, marker.measurement_id),
        label_of=lambda marker: marker.label,
    )

    assert merged == (edited,)


def test_merge_appends_a_new_measurement_of_the_same_label() -> None:
    first = _peak("TR Vmax", 280.0, index=0)
    second = _peak("TR Vmax", 330.0, index=1)

    merged = merge_newest_wins(
        (first,),
        (second,),
        identity_of=lambda marker: (marker.label, marker.measurement_id),
        label_of=lambda marker: marker.label,
    )

    assert merged == (first, second)


def test_merge_keeps_legacy_replace_by_label_behavior() -> None:
    legacy = DopplerPeakMarker(label="TR Vmax", time_ms=10.0, velocity_cm_s=280.0)
    newer = DopplerPeakMarker(label="TR Vmax", time_ms=20.0, velocity_cm_s=330.0)

    merged = merge_doppler_peaks((legacy,), (newer,))

    assert merged == (newer,)


def test_repeated_measurements_survive_repeated_merges() -> None:
    """The frame record is merged again on every frame change; repeats stay put."""
    markers = tuple(_peak("TR Vmax", 280.0 + 10.0 * index, index=index) for index in range(3))
    dto = DopplerMeasurementDTO(peaks=markers, intervals=(), traces=())

    merged = merge_doppler_dtos(dto, dto)

    assert merged.peaks == markers


def test_new_measurement_id_is_unique_and_opaque() -> None:
    first, second = new_measurement_id(), new_measurement_id()
    assert first and second and first != second
    assert len(first) <= 256
    assert first.isascii()


# ── aggregation across frames of one clip ───────────────────────────


def test_all_doppler_dto_keeps_repeats_from_different_frames() -> None:
    """The atrial-fibrillation workflow: one TR Vmax per frame of the clip."""
    store = StudyMeasurementSessionStore()
    baseline = StudyMeasurementData()
    store.restore(UID, baseline)
    for frame, velocity in enumerate((280.0, 300.0, 320.0, 340.0)):
        dto = DopplerMeasurementDTO(peaks=(_peak("TR Vmax", velocity, index=frame),), intervals=(), traces=())
        store.set_doppler_for_instance_frame(UID, SOP, frame, dto)

    aggregate = store.get(UID).all_doppler_dto

    assert len(aggregate.peaks) == 4
    assert [marker.velocity_cm_s for marker in aggregate.peaks] == [280.0, 300.0, 320.0, 340.0]
    result = compute(aggregate)
    assert result.flow("TR").vmax_repeats == 4
    assert result.flow("TR").vmax_cm_s == pytest.approx((300.0 + 320.0 + 340.0) / 3.0)


def test_aggregate_keeps_repeats_after_frame_resave() -> None:
    """A second save of the same frame must not duplicate or drop measurements."""
    store = StudyMeasurementSessionStore()
    store.restore(UID, StudyMeasurementData())
    dto = DopplerMeasurementDTO(
        peaks=(_peak("TR Vmax", 280.0, index=0), _peak("TR Vmax", 330.0, index=1)),
        intervals=(),
        traces=(),
    )
    store.set_doppler_for_instance_frame(UID, SOP, 0, dto)
    store.merge_doppler_for_instance_frame(UID, SOP, 0, dto)

    aggregate = store.get(UID).all_doppler_dto

    assert [marker.velocity_cm_s for marker in aggregate.peaks] == [280.0, 330.0]


def test_vti_repeats_average_last_three_traces() -> None:
    def triangle(offset: float, peak: float) -> DopplerTrace:
        return DopplerTrace(
            label="AV VTI",
            points=((offset, 0.0), (offset + 100.0, peak), (offset + 200.0, 0.0)),
            measurement_id=f"t{offset}",
        )

    traces = (triangle(0.0, 100.0), triangle(300.0, 200.0), triangle(600.0, 300.0), triangle(900.0, 400.0))
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=traces)

    result = compute(dto)

    # Triangular envelope: 0.5 · 200 ms · v cm/s / 1000 = v/10 cm.
    expected = (200.0 / 10.0 + 300.0 / 10.0 + 400.0 / 10.0) / 3.0
    assert result.flow("AV").vti_cm == pytest.approx(expected)
    assert result.flow("AV").vti_repeats == 3
