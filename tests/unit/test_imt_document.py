"""Synthetic structured storage/review tests; not clinical validation."""

import json
from dataclasses import replace

import numpy as np
import pytest

from echo_personal_tool.application.imt import propose_imt
from echo_personal_tool.application.imt_review import ImtReview
from echo_personal_tool.application.measurement_persistence import combine, scoped
from echo_personal_tool.application.study_measurement_session import StudyMeasurementData, StudyMeasurementSessionStore
from echo_personal_tool.domain.models.calibration import CalibrationContext
from echo_personal_tool.domain.models.imt import ImtPolicy, ImtRefusal, ImtSource
from echo_personal_tool.infrastructure.measurement_codec import (
    FORMAT,
    SEMANTICS_VERSION,
    VERSION,
    MeasurementStorageError,
    dumps,
    loads,
)


@pytest.fixture
def sample():
    image = np.full((64, 96), 10.0)
    image[20:23] = 140
    image[23:28] = 40
    image[28:] = 220
    source = ImtSource(
        "1.2.3",
        "sop",
        1,
        2,
        10,
        "R",
        "operator_selected",
        CalibrationContext((0.1, 0.2), source="PixelSpacing"),
        (0, 0, 96, 64),
    )
    return image, propose_imt(image, source, ImtPolicy(0.3, 1.5, 0.75, 0.05), lumen_y=20, adventitia_y=28)


def record(draft):
    return dict(
        format=FORMAT,
        schema_version=VERSION,
        measurement_semantics_version=SEMANTICS_VERSION,
        study_uid="1.2.3",
        revision=1,
        saved_at="2026-11-13T00:00:00+00:00",
        sources={"sop": dict(fingerprint="a" * 64, frames=10, spacing=[0.1, 0.2])},
        data=StudyMeasurementData(imt_measurements=(draft,)),
    )


def test_round_trip_schema_and_dirty(sample):
    image, draft = sample
    draft = draft.confirm(draft.source)
    changes = []
    store = StudyMeasurementSessionStore(lambda *args: changes.append(args))
    store.set_imt_measurement("1.2.3", draft)
    assert len(changes) == 1
    assert store.get("1.2.3").has_measurements
    payload = dumps(record(draft))
    loaded = loads(payload)["data"].imt_measurements[0]
    assert loaded == draft
    from importlib.resources import files

    import jsonschema

    jsonschema.validate(
        json.loads(payload),
        json.loads(
            files("echo_personal_tool.resources").joinpath(f"measurement-storage-v{VERSION}.schema.json").read_text()
        ),
    )
    review = ImtReview(loaded)
    with pytest.raises(ImtRefusal, match="review_required"):
        review.confirm(loaded.source)
    assert review.revalidate(loaded.source, image).revision == 1
    assert not review.draft.confirmed
    assert review.confirm(loaded.source).confirmed


@pytest.mark.parametrize(
    "field,value",
    [
        ("mean_mm", 99),
        ("sd_mm", 99),
        ("sampled_length_mm", 99),
        ("attempted_samples", 999),
        ("accepted_sample_indices", (0, 0)),
        ("revision", -1),
        ("method", "clinical"),
    ],
)
def test_corrupt_records_refused(sample, field, value):
    _, draft = sample
    with pytest.raises(MeasurementStorageError):
        dumps(record(replace(draft, **{field: value})))


def test_wrong_source_and_duplicate_refused(sample):
    _, draft = sample
    r = record(draft)
    r["sources"]["sop"]["frames"] = 11
    with pytest.raises(MeasurementStorageError):
        dumps(r)
    r = record(draft)
    r["study_uid"] = "1.2.4"
    with pytest.raises(MeasurementStorageError):
        dumps(r)
    r = record(draft)
    r["data"] = replace(r["data"], imt_measurements=(draft, draft))
    with pytest.raises(MeasurementStorageError):
        dumps(r)


def test_review_edit_and_context_invalidation(sample):
    image, draft = sample
    review = ImtReview(draft, live=True)
    review.confirm(draft.source)
    edited = review.edit(draft.source, image, draft.lumen_intima, draft.media_adventitia)
    assert edited.revision == 1 and not edited.confirmed
    changed = replace(draft.source, generation=2)
    with pytest.raises(ImtRefusal, match="stale_draft"):
        review.confirm(changed)
    review.invalidate()
    with pytest.raises(ImtRefusal):
        review.confirm(draft.source)
    assert review.revalidate(changed, image).source == changed


def test_scope_combine_preserves_missing_sources(sample):
    _, draft = sample
    full = StudyMeasurementData(imt_measurements=(draft,))
    assert not scoped(full, {"other"}).imt_measurements
    assert combine(full, StudyMeasurementData(), {"other"}).imt_measurements == (draft,)


def test_direct_storage_and_geometry_validation(sample):
    from echo_personal_tool.domain.services.imt_validation import validate_imt
    from echo_personal_tool.infrastructure.imt_storage import validate_imt_storage

    _, draft = sample
    validate_imt(draft)
    validate_imt_storage((draft,), record(draft)["sources"])
    with pytest.raises(ImtRefusal):
        validate_imt_storage((draft,), {})
    with pytest.raises(ImtRefusal):
        validate_imt(replace(draft, max_mm=100))


def test_document_disk_reload_keeps_evidence_but_not_live_lease(sample, tmp_path):
    from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository

    image, draft = sample
    data = StudyMeasurementData(imt_measurements=(draft.confirm(draft.source),))
    repository = MeasurementRepository(tmp_path)
    repository.acquire()
    try:
        repository.save("1.2.3", data, record(draft)["sources"], 0)
        reloaded = repository.load("1.2.3")["data"]
        assert reloaded == data
        assert reloaded.imt_measurements[0].confirmed
        review = ImtReview(reloaded.imt_measurements[0])
        with pytest.raises(ImtRefusal):
            review.confirm(draft.source)
        review.revalidate(replace(draft.source, generation=5), image)
        assert review.draft.source.generation == 5 and not review.draft.confirmed
    finally:
        repository.close()


def test_v6_document_has_empty_imt_and_unknown_nested_fields_refuse(sample):
    _, draft = sample
    old = record(draft)
    old["data"] = StudyMeasurementData()
    old["schema_version"] = 6
    loaded = loads(dumps(old))
    assert loaded["data"].imt_measurements == ()
    wire = json.loads(dumps(record(draft)))
    wire["data"]["imt_measurements"][0]["source"]["clinical_override"] = True
    with pytest.raises(MeasurementStorageError):
        loads(json.dumps(wire).encode())


@pytest.mark.parametrize(
    "change",
    [
        {"study_uid": "1.2.4"},
        {"instance_uid": "other"},
        {"frame_index": 3},
        {"frame_count": 11},
        {"side": "L"},
        {"phase": "other"},
        {"roi": (1, 0, 96, 64)},
    ],
)
def test_loaded_draft_cannot_be_relabelled_during_revalidation(sample, change):
    image, draft = sample
    loaded = loads(dumps(record(draft.confirm(draft.source))))["data"].imt_measurements[0]
    review = ImtReview(loaded)
    changed = replace(loaded.source, **change)
    with pytest.raises(ImtRefusal, match="stale_draft"):
        review.revalidate(changed, image)
    assert not review.live and not review.draft.confirmed
    assert review.draft.source == draft.source
    with pytest.raises(ImtRefusal, match="review_required"):
        review.confirm(draft.source)


def test_loaded_draft_revalidates_new_calibration_against_raw_image(sample):
    image, draft = sample
    loaded = loads(dumps(record(draft.confirm(draft.source))))["data"].imt_measurements[0]
    new_calibration = replace(loaded.source.calibration, spacing=(0.11, 0.2), revision=1)
    current = replace(loaded.source, generation=7, calibration=new_calibration)
    review = ImtReview(loaded)
    checked = review.revalidate(current, image)
    assert checked.source == current and checked.revision == loaded.revision + 1
    assert checked.mean_mm == pytest.approx(loaded.mean_mm * 1.1, rel=0.02)
    assert not checked.confirmed and review.live
    assert review.confirm(current).confirmed


@pytest.mark.parametrize("failure", ["flat", "nan", "colour", "cropped"])
def test_revalidation_bad_image_clears_live_and_confirmation(sample, failure):
    image, draft = sample
    review = ImtReview(draft.confirm(draft.source), live=True)
    bad = image.copy()
    if failure == "flat":
        bad[:] = 0
    elif failure == "nan":
        bad[22, 22] = np.nan
    elif failure == "colour":
        bad = np.stack((bad, bad, bad), axis=-1)
    else:
        bad = bad[:30]
    with pytest.raises(ImtRefusal):
        review.revalidate(draft.source, bad)
    assert not review.live and not review.draft.confirmed
    assert review.draft.revision == draft.revision
    with pytest.raises(ImtRefusal, match="review_required"):
        review.confirm(draft.source)


@pytest.mark.parametrize("failure", ["geometry", "image", "stale"])
def test_refused_edit_revokes_live_lease_without_publishing_new_values(sample, failure):
    image, draft = sample
    review = ImtReview(draft.confirm(draft.source), live=True)
    li, ma = draft.lumen_intima, draft.media_adventitia
    current = draft.source
    if failure == "geometry":
        li, ma = ma, li
    elif failure == "image":
        image = np.zeros_like(image)
    else:
        current = replace(current, frame_index=3)
    with pytest.raises(ImtRefusal):
        review.edit(current, image, li, ma)
    assert not review.live and not review.draft.confirmed
    assert review.draft.revision == draft.revision
    assert review.draft.lumen_intima == draft.lumen_intima and review.draft.mean_mm == draft.mean_mm
    with pytest.raises(ImtRefusal, match="review_required"):
        review.confirm(draft.source)


def test_stale_confirmation_revokes_lease_even_if_context_returns(sample):
    _, draft = sample
    review = ImtReview(draft.confirm(draft.source), live=True)
    with pytest.raises(ImtRefusal, match="stale_draft"):
        review.confirm(replace(draft.source, generation=2))
    assert not review.live and not review.draft.confirmed
    with pytest.raises(ImtRefusal, match="review_required"):
        review.confirm(draft.source)


def test_real_correction_recomputes_geometry_and_requires_new_confirmation(sample):
    image, draft = sample
    review = ImtReview(draft.confirm(draft.source), live=True)
    # Shift the second line by one pixel, but retain the physical/QC gates.
    changed = tuple((x, y + 0.5) for x, y in draft.media_adventitia)
    corrected = review.edit(draft.source, image, draft.lumen_intima, changed)
    assert corrected.media_adventitia == changed
    assert corrected.revision == draft.revision + 1 and not corrected.confirmed
    assert corrected.mean_mm > draft.mean_mm
    with pytest.raises(ImtRefusal, match="confirmation_required"):
        corrected.report_record(draft.source)
    assert review.confirm(draft.source).report_record(draft.source)["confirmed"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("mean_mm", -1),
        ("max_mm", 99),
        ("attempted_samples", 0),
        ("accepted_sample_indices", [0, 0]),
        ("confirmed", "true"),
        ("distances_mm", [float("nan")]),
    ],
)
def test_loaded_malformed_nested_evidence_refused(sample, field, value):
    _, draft = sample
    wire = json.loads(dumps(record(draft)))
    wire["data"]["imt_measurements"][0][field] = value
    with pytest.raises(MeasurementStorageError):
        loads(json.dumps(wire).encode())
