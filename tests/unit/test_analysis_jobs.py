"""Qt-free publication ownership and ABA regressions (#552)."""

from dataclasses import replace

import pytest

from echo_personal_tool.application.analysis_jobs import AnalysisBasis, AnalysisJobs


def _basis():
    return AnalysisBasis("study", 1, "sop", "/cine.dcm", ((0.5, 0.5), 1), 33.3, ())


def test_only_latest_request_can_finish_once():
    owner = AnalysisJobs()
    old = owner.begin(_basis())
    latest = owner.begin(_basis())
    assert latest.request_id > old.request_id
    assert not owner.finish(old, _basis())
    assert owner.finish(latest, _basis())
    assert not owner.finish(latest, _basis())


@pytest.mark.parametrize(
    "change",
    [
        {"document_id": "other"},
        {"study_generation": 2},
        {"instance_uid": "other"},
        {"source_path": "/other.dcm"},
        {"calibration": ((0.5, 0.5), 2)},
        {"frame_time_ms": 40.0},
        {"contours": (("contour", 2),)},
    ],
)
def test_changed_basis_rejects_publication(change):
    owner = AnalysisJobs()
    ticket = owner.begin(_basis())
    assert not owner.finish(ticket, replace(_basis(), **change))
    assert not owner.finish(ticket, _basis())


def test_observed_change_then_undo_does_not_revive_request():
    owner = AnalysisJobs()
    ticket = owner.begin(_basis())
    owner.observe(replace(_basis(), calibration=((1.0, 1.0), 2)))
    owner.observe(_basis())
    assert not owner.finish(ticket, _basis())


def test_invalidation_and_identical_reload_does_not_revive_request():
    owner = AnalysisJobs()
    old = owner.begin(_basis())
    owner.invalidate()
    new = owner.begin(_basis())
    assert not owner.finish(old, _basis())
    assert owner.finish(new, _basis())


def test_unchanged_observation_preserves_job():
    owner = AnalysisJobs()
    ticket = owner.begin(_basis())
    owner.observe(_basis())
    assert owner.finish(ticket, _basis())


def test_idle_observation_does_not_resolve_or_copy_the_document():
    owner = AnalysisJobs()

    def forbidden():
        raise AssertionError("idle playback must not resolve the document")

    owner.observe_state(None, None, forbidden, 1)  # type: ignore[arg-type]


def test_basis_copies_mutable_contour_points():
    from echo_personal_tool.application.analysis_jobs import analysis_basis
    from echo_personal_tool.domain.models.contour import Contour
    from echo_personal_tool.domain.models.viewer_state import ViewerState

    contour = Contour(phase="ED", points=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
    state = ViewerState(None, 0, 3, 33.3, False, contours=(contour,))
    basis = analysis_basis(state, None, document_id="doc", generation=1)
    contour.points[0] = (4.0, 4.0)
    later = analysis_basis(state, None, document_id="doc", generation=1)
    assert basis.contours != later.contours
