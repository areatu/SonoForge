"""A report prints the measurements of the study it belongs to.

One study can hold the clips and measurements of several examinations — the
physician starts an echocardiography, notices the thyroid and switches the
study type.  The measurements stay in the study, but the protocol of the
thyroid must not carry the left-ventricle sizes, and above all it must not
print the Teichholz numbers derived from them.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import (
    MeasurementSnapshot,
    PlanimeterResult,
    TeichholzResult,
)
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
from echo_personal_tool.domain.services.report_builder import PatientInfo, build_report_document
from echo_personal_tool.domain.services.report_scope import (
    allow_label,
    allowed_tool_ids,
    restrict_snapshot_to_profile,
    tools_for_label,
)
from echo_personal_tool.domain.study_profiles import (
    STUDY_PROFILE_ECHO,
    STUDY_PROFILE_KIDNEY,
    STUDY_PROFILE_THYROID,
    STUDY_PROFILE_VASCULAR,
    study_profile,
)
from echo_personal_tool.infrastructure.i18n import set_language


def _caliper(label: str, millimeters: float = 20.0) -> LinearMeasurement:
    return LinearMeasurement(label=label, pixel_length=millimeters * 2, millimeter_length=millimeters)


def _vessel(label: str) -> VesselMeasurement:
    return VesselMeasurement(
        psv_cm_s=100.0,
        edv_cm_s=30.0,
        ri=0.7,
        sd=3.3,
        mv_approx=2.5,
        sop_instance_uid="1.2.3",
        frame_index=0,
        label=label,
    )


def _study() -> MeasurementSnapshot:
    """One study that measured the heart, the thyroid, a kidney and a carotid."""
    return MeasurementSnapshot(
        linear_measurements=(
            _caliper("LVEDD", 47.7),
            _caliper("TH-R-TH", 38.8),
            _caliper("RK-T", 41.0),
            _caliper("L", 12.0),
        ),
        vessel_measurements=(_vessel("RA-R"), _vessel("CCA-R")),
        planimeter=(
            PlanimeterResult(label="S1", kind="area", value=12.0, unit="cm²"),
            PlanimeterResult(label="V1", kind="volume", value=90.0, unit="mL"),
        ),
        teichholz=TeichholzResult(edv_ml=106.0, esv_ml=54.0, lvef_percent=49.0, sv_ml=52.0),
    )


def _labels(snapshot: MeasurementSnapshot) -> set[str]:
    return {measurement.label for measurement in snapshot.linear_measurements}


# ── the scope of a profile ─────────────────────────────────────────


def test_the_labels_of_the_catalog_resolve_to_their_tools() -> None:
    assert "lv.linear_ed" in tools_for_label("LVEDD")
    assert tools_for_label("TH-R-TH") == {"thyroid.r_thick"}
    assert tools_for_label("RA-R") == {"vessel.renal_right"}
    # A free-form caliper belongs to no instrument.
    assert tools_for_label("L") == frozenset()


def test_a_free_caliper_survives_every_profile() -> None:
    """The physician's own caliper is an observation of the organ on screen."""
    for profile_id in (STUDY_PROFILE_ECHO, STUDY_PROFILE_KIDNEY, STUDY_PROFILE_THYROID):
        allowed = allowed_tool_ids(study_profile(profile_id))
        assert allow_label("L", allowed) is True


def test_the_echo_profile_keeps_echo_and_drops_the_organs() -> None:
    restricted = restrict_snapshot_to_profile(_study(), study_profile(STUDY_PROFILE_ECHO))
    assert _labels(restricted) == {"LVEDD", "L"}
    # The carotid belongs to the vascular study, not to the heart.
    assert restricted.vessel_measurements == ()
    assert restricted.teichholz is not None


def test_an_organ_profile_drops_the_heart_and_its_derived_numbers() -> None:
    restricted = restrict_snapshot_to_profile(_study(), study_profile(STUDY_PROFILE_THYROID))
    assert _labels(restricted) == {"TH-R-TH", "L"}
    assert restricted.vessel_measurements == ()
    assert restricted.teichholz is None


def test_the_renal_profile_keeps_its_artery_and_drops_the_carotid() -> None:
    restricted = restrict_snapshot_to_profile(_study(), study_profile(STUDY_PROFILE_KIDNEY))
    assert _labels(restricted) == {"RK-T", "L"}
    assert [vessel.label for vessel in restricted.vessel_measurements] == ["RA-R"]


def test_the_vascular_profile_keeps_its_own_arteries() -> None:
    restricted = restrict_snapshot_to_profile(_study(), study_profile(STUDY_PROFILE_VASCULAR))
    assert [vessel.label for vessel in restricted.vessel_measurements] == ["CCA-R"]
    assert "TH-R-TH" not in _labels(restricted)
    assert "RK-T" not in _labels(restricted)
    assert restricted.teichholz is None


def test_an_area_contour_stays_and_a_spline_volume_does_not() -> None:
    """«Площадь» is a general tool; «Объём» (spline) is echocardiography only."""
    restricted = restrict_snapshot_to_profile(_study(), study_profile(STUDY_PROFILE_THYROID))
    assert [result.kind for result in restricted.planimeter] == ["area"]


def test_the_study_itself_is_not_touched() -> None:
    study = _study()
    restrict_snapshot_to_profile(study, study_profile(STUDY_PROFILE_THYROID))
    assert len(study.linear_measurements) == 4
    assert study.teichholz is not None


# ── the document of a profile ──────────────────────────────────────


def test_a_thyroid_report_prints_the_thyroid_only() -> None:
    set_language("ru")
    document = build_report_document(
        _study(),
        PatientInfo(sex="M"),
        sex="M",
        profile_id="thyroid",
        study_profile_id=STUDY_PROFILE_THYROID,
    )
    rows = {value.label: value.value for group in document.groups for value in group.values}
    assert "ЩЖ П толщина" in rows
    assert "КДР ЛЖ" not in rows
    assert all("Тейхольц" not in label for label in rows)


def test_an_echo_report_prints_the_heart_only() -> None:
    set_language("ru")
    document = build_report_document(
        _study(),
        PatientInfo(sex="M"),
        sex="M",
        profile_id="echo",
        study_profile_id=STUDY_PROFILE_ECHO,
    )
    labels = {value.label for group in document.groups for value in group.values}
    assert not any("ЩЖ" in label for label in labels)
    assert not any("Почка" in label for label in labels)


def test_no_study_profile_keeps_the_whole_study() -> None:
    """Callers that know nothing about profiles keep the older document."""
    set_language("ru")
    document = build_report_document(_study(), PatientInfo(sex="M"), sex="M", profile_id="echo")
    labels = {value.label for group in document.groups for value in group.values}
    assert any("ЩЖ" in label for label in labels)
    assert any("Тейхольц" in label for label in labels)


@pytest.mark.parametrize("profile_id", [STUDY_PROFILE_KIDNEY, STUDY_PROFILE_VASCULAR])
def test_a_profile_never_sees_another_studys_rows(profile_id: str) -> None:
    set_language("ru")
    document = build_report_document(
        _study(),
        PatientInfo(sex="M"),
        sex="M",
        profile_id=study_profile(profile_id).report_profile_id,
        study_profile_id=profile_id,
    )
    labels = {value.label for group in document.groups for value in group.values}
    if profile_id == STUDY_PROFILE_KIDNEY:
        assert any("Почка" in label for label in labels)
        assert not any("ЩЖ" in label for label in labels)
        assert not any("КИМ" in label for label in labels)
    else:
        assert not any("ЩЖ" in label or "Почка" in label or "КДР" in label for label in labels)
