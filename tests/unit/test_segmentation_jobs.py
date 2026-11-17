"""Qt-free single-use segmentation publication and ABA tests (#552)."""

from dataclasses import replace

import pytest

from echo_personal_tool.application.segmentation_jobs import SegmentationBasis, SegmentationJobs


def _basis():
    return SegmentationBasis("study", 1, "sop", "/cine.dcm", ((0.5, 0.5), 1), 33.3, (), 0, 0, False, ())


def test_superseded_terminal_cannot_consume_the_new_ticket():
    jobs = SegmentationJobs()
    old = jobs.begin(_basis())
    new = jobs.begin(_basis())
    assert jobs.finish(old, _basis()) is None
    assert jobs.finish(new, _basis()) is True
    assert jobs.finish(new, _basis()) is None


@pytest.mark.parametrize(
    "change",
    [
        {"document_id": "other"},
        {"study_generation": 2},
        {"instance_uid": "other"},
        {"source_path": "/other"},
        {"calibration": ((0.7, 0.7), 2)},
        {"frame_time_ms": 40.0},
        {"contours": (("changed",),)},
        {"frame_index": 1},
        {"loaded_frame_index": 1},
        {"is_playing": True},
        {"contour_flags": ((True,),)},
    ],
)
def test_change_at_delivery_consumes_but_does_not_publish(change):
    jobs = SegmentationJobs()
    ticket = jobs.begin(_basis())
    assert jobs.finish(ticket, replace(_basis(), **change)) is False
    assert jobs.finish(ticket, _basis()) is None


def test_explicit_invalidation_cannot_be_undone_by_equal_inputs():
    jobs = SegmentationJobs()
    ticket = jobs.begin(_basis())
    jobs.invalidate()
    assert jobs.finish(ticket, _basis()) is False


def test_idle_observation_never_reads_document():
    jobs = SegmentationJobs()

    def forbidden():
        raise AssertionError("idle playback must not resolve a document")

    jobs.observe_state(None, None, forbidden, 1, None)  # type: ignore[arg-type]


def test_observed_frame_and_contour_aba_never_revives_ticket():
    from echo_personal_tool.application.segmentation_jobs import segmentation_basis
    from echo_personal_tool.domain.models.contour import Contour
    from echo_personal_tool.domain.models.metadata import InstanceMetadata
    from echo_personal_tool.domain.models.viewer_state import ViewerState

    instance = InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2",
        modality="US",
        number_of_frames=2,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="synthetic",
    )
    contour = Contour("ED", points=[(1.0, 2.0)], frame_index=0)
    state = ViewerState(instance, 0, 2, 33.3, False, contours=(contour,))
    basis = segmentation_basis(state, instance, document_id="doc", generation=1, loaded_frame_index=0)
    jobs = SegmentationJobs()
    unchanged = jobs.begin(basis)
    assert jobs.finish(unchanged, basis) is True
    ticket = jobs.begin(basis)
    jobs.observe_state(replace(state, current_frame_index=1), instance, lambda: "doc", 1, 0)
    jobs.observe_state(state, instance, lambda: "doc", 1, 0)
    assert jobs.finish(ticket, basis) is False

    ticket = jobs.begin(basis)
    contour.points[0] = (3.0, 4.0)
    jobs.observe_state(state, instance, lambda: "doc", 1, 0)
    contour.points[0] = (1.0, 2.0)
    assert jobs.finish(ticket, basis) is False
