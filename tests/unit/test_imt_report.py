"""Only explicit accepted IMT appears in the appropriate research report section."""

from dataclasses import replace

from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.report_builder import build_report_groups
from echo_personal_tool.domain.services.report_imt import imt_report_values
from echo_personal_tool.domain.services.report_scope import restrict_snapshot_to_profile
from echo_personal_tool.domain.study_profiles import STUDY_PROFILE_THYROID, STUDY_PROFILE_VASCULAR, study_profile
from tests.unit.test_imt_document import sample as sample


def test_draft_is_not_reported_and_accepted_result_keeps_scale_and_lineage(sample):
    _image, draft = sample
    assert imt_report_values((draft,)) == ()
    assert not build_report_groups(MeasurementSnapshot(imt_measurements=(draft,)))
    accepted = draft.confirm(draft.source)
    rows = [v for g in build_report_groups(MeasurementSnapshot(imt_measurements=(accepted,))) for v in g.values]
    direct = imt_report_values((accepted,))
    assert [(v.parameter_id, v.value, v.origin) for v in rows] == [(v.parameter_id, v.value, v.origin) for v in direct]
    assert len(rows) == 3
    assert {v.parameter_id for v in rows} == {"cca.imt_right", "cca.imt_right.minimum", "cca.imt_right.maximum"}
    assert all(v.unit == "mm" and not v.pathological and not v.norm for v in rows)
    assert all(v.origin.method_id == draft.method and v.origin.sources[0].sop_instance_uid == "sop" for v in rows)


def test_report_profile_filters_imt_without_deleting_stored_measurements(sample):
    _image, draft = sample
    accepted = draft.confirm(draft.source)
    snapshot = MeasurementSnapshot(imt_measurements=(accepted,))
    thyroid = restrict_snapshot_to_profile(snapshot, study_profile(STUDY_PROFILE_THYROID))
    vascular = restrict_snapshot_to_profile(snapshot, study_profile(STUDY_PROFILE_VASCULAR))
    assert not thyroid.imt_measurements
    assert vascular.imt_measurements == snapshot.imt_measurements == (accepted,)


def test_sides_and_repeated_frames_remain_separate_no_implicit_averaging(sample):
    _image, draft = sample
    second = replace(draft, source=replace(draft.source, side="L", frame_index=3))
    accepted = tuple(d.confirm(d.source) for d in (draft, second))
    rows = [v for g in build_report_groups(MeasurementSnapshot(imt_measurements=accepted)) for v in g.values]
    assert len(rows) == 6
    assert {v.origin.sources[0].frame_index for v in rows} == {2, 3}
    assert {v.parameter_id for v in rows if not v.parameter_id.endswith((".minimum", ".maximum"))} == {
        "cca.imt_right",
        "cca.imt_left",
    }
