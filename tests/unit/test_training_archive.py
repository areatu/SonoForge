"""Real confirmations, local atomic storage, explicit phase/origin and offline splits."""

import json
import sqlite3
from dataclasses import replace

import numpy as np
import pytest
from scripts.export_measurement_archive import export_archive, main

from echo_personal_tool.application.training_archive import MeasurementArchiveCapture
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.training_archive import ArchiveContext, ArchiveWriteError
from echo_personal_tool.domain.services.training_archive import atlas_phase, make_archive_sample, phase_semantics
from echo_personal_tool.domain.services.training_archive_export import reviewed_atlas_record, split_archive_records
from echo_personal_tool.infrastructure.training_archive import SqliteMeasurementArchive


@pytest.fixture
def setup_archive(tmp_path):
    archive = SqliteMeasurementArchive(tmp_path / "local" / "measurement-training.sqlite3")
    skipped = []
    capture = MeasurementArchiveCapture(archive, lambda: skipped.append(True))
    context = ArchiveContext(
        "patient-sensitive", "study-sensitive", "series-sensitive", "sop-sensitive", "0.4.2", (0.4, 0.3)
    )
    image = np.arange(128 * 160, dtype=np.uint16).reshape(128, 160)
    contour = Contour(
        "ED",
        points=[(20.0, 90.0), (45.0, 15.0), (70.0, 30.0), (90.0, 90.0)],
        mitral_annulus=((20.0, 90.0), (90.0, 90.0)),
        apex_landmark=(45.0, 15.0),
        frame_index=2,
        sop_instance_uid=context.instance_key,
    )
    capture.transition(context.instance_key, 2)
    return archive, capture, context, image, contour, skipped


@pytest.mark.parametrize(
    "chamber,phase,semantics",
    [
        ("LV", "ED", "ventricular_end_diastole"),
        ("LV", "ES", "ventricular_end_systole"),
        ("RV", "ED", "ventricular_end_diastole"),
        ("RV", "ES", "ventricular_end_systole"),
        ("LA", "ES", "atrial_maximum"),
        ("LA", "ED", "atrial_minimum"),
        ("RA", "ES", "atrial_maximum"),
        ("RA", "ED", "atrial_minimum"),
        ("RA", "GEN", "unspecified"),
    ],
)
@pytest.mark.parametrize(
    "source,edited,origin", [("manual", False, "MANUAL"), ("ai", False, "AUTO_ACCEPTED"), ("ai", True, "AUTO_EDITED")]
)
def test_context_is_stable_and_explicit(setup_archive, chamber, phase, semantics, source, edited, origin):
    archive, capture, context, image, contour, skipped = setup_archive
    contour = replace(
        contour, chamber=chamber, phase=phase, source=source, auto_edited=edited, measurement_label="Ненужная подпись"
    )
    capture.observe([contour], image, 2, context)
    capture.confirm(context.instance_key, 2)
    [record] = archive.records()
    assert (record["chamber"], record["phase_semantics"], record["origin"]) == (chamber, semantics, origin)
    assert record["tool_id"] == f"chamber_open_arc:{chamber}"
    assert record["points"] == [list(p) for p in contour.points]
    assert record["partial_annotation"] and not skipped
    text = json.dumps(record)
    assert "sensitive" not in text and "Ненужная" not in text
    if phase in {"ED", "ES"}:
        assert atlas_phase(semantics) == phase
    else:
        with pytest.raises(ValueError, match="unspecified"):
            atlas_phase(semantics)


def test_apply_navigation_edits_delete_and_undo_have_one_versioned_identity(setup_archive):
    archive, capture, context, image, contour, _ = setup_archive
    capture.observe([contour], image, 2, context)
    assert archive.records() == []  # no intermediate training example
    capture.confirm(context.instance_key, 2)
    first = archive.records()[0]
    capture.observe([contour], image, 2, context)
    capture.confirm(context.instance_key, 2)
    assert archive.records()[0]["revision"] == 1
    modified = replace(contour, points=[(21.0, 90.0), *contour.points[1:]])
    capture.observe([modified], image, 2, context)
    capture.transition(context.instance_key, 3)
    [updated] = archive.records()
    assert updated["revision"] == 2 and updated["sample_id"] == first["sample_id"]
    assert updated["points"][0] == [21.0, 90.0]
    capture.observe([], image, 3, context)
    assert archive.records() == []
    assert archive.records(include_excluded=True)[0]["excluded"]
    capture.transition(context.instance_key, 2)
    capture.observe([modified], image, 2, context)
    capture.confirm(context.instance_key, 2)
    assert len(archive.records()) == 1 and archive.records()[0]["revision"] == 4


def test_navigation_uses_copied_measurement_frame_not_next_frame_or_overlay(setup_archive):
    archive, capture, context, image, contour, _ = setup_archive
    expected = image.copy()
    capture.observe([contour], image, 2, context)
    image[:] = 0  # display buffer may be reused/overlaid after leaving
    capture.transition(context.instance_key, 3)
    [record] = archive.records()
    np.testing.assert_array_equal(archive.frame(record["frame_hash"]), expected)
    assert record["frame_index"] == 2 and record["source_to_saved"] == np.eye(3).tolist()
    assert record["pixel_spacing_mm"] == [0.4, 0.3]
    np.testing.assert_array_equal(np.asarray(record["points"]), contour.points)


@pytest.mark.parametrize(
    "change",
    [
        {"review_pending": True},
        {"points": []},
        {"points": [(1.0, 1.0)] * 3},
        {"chamber": "AREA"},
        {"frame_index": None},
        {"points": [(999.0, 1.0)] * 3},
    ],
)
def test_unfinished_cancelled_pending_and_nonspecific_are_not_samples(setup_archive, change):
    archive, capture, context, image, contour, _ = setup_archive
    capture.observe([replace(contour, **change)], image, 2, context)
    capture.observe([], image, 2, context)  # Esc/remove before commit
    capture.transition(context.instance_key, 3)
    assert archive.records() == []


def test_pending_auto_is_never_accepted_by_navigation(setup_archive):
    archive, capture, context, image, contour, _ = setup_archive
    proposal = replace(contour, source="ai", review_pending=True)
    capture.observe([proposal], image, 2, context)
    capture.transition(context.instance_key, 3)
    assert archive.records() == []
    capture.transition(context.instance_key, 2)
    capture.observe([replace(proposal, review_pending=False)], image, 2, context)
    capture.confirm(context.instance_key, 2)
    assert archive.records()[0]["origin"] == "AUTO_ACCEPTED"


def test_clip_switch_and_wrong_frame_never_implicitly_accept(setup_archive):
    archive, capture, context, image, contour, _ = setup_archive
    capture.observe([contour], image, 2, context)
    capture.transition("different-clip", 3)
    assert archive.records() == []
    capture.observe([contour], image, 3, context)
    capture.confirm(context.instance_key, 2)
    assert archive.records() == []


def test_local_write_failure_does_not_mutate_clinical_measurement_and_can_retry(setup_archive, monkeypatch):
    archive, capture, context, image, contour, skipped = setup_archive
    capture.observe([contour], image, 2, context)
    original_save = archive.save

    def broken(sample):
        raise ArchiveWriteError("safe")

    monkeypatch.setattr(archive, "save", broken)
    capture.confirm(context.instance_key, 2)
    assert skipped == [True] and contour.points[0] == (20.0, 90.0) and archive.records() == []
    monkeypatch.setattr(archive, "save", original_save)
    capture.confirm(context.instance_key, 2)
    assert len(archive.records()) == 1


def test_sqlite_failed_transaction_has_no_orphan_frame(setup_archive):
    archive, capture, context, image, contour, _ = setup_archive
    capture.observe([contour], image, 2, context)
    with sqlite3.connect(archive.path) as db:
        db.execute("CREATE TRIGGER fail_sample BEFORE INSERT ON samples BEGIN SELECT RAISE(ABORT,'no'); END")
    capture.confirm(context.instance_key, 2)
    with sqlite3.connect(archive.path) as db:
        assert db.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 0
    assert archive.records() == []


def test_pathological_trace_kept_verbatim_and_automatic_assist_not_manual(setup_archive):
    archive, capture, context, image, contour, _ = setup_archive
    pathological = replace(
        contour, points=[(2.0, 126.0), (150.0, 2.0), (3.0, 3.0), (158.0, 127.0)], auto_generated=True
    )
    capture.observe([pathological], image, 2, context)
    capture.confirm(context.instance_key, 2)
    [record] = archive.records()
    assert record["points"] == [list(p) for p in pathological.points]
    assert record["origin"] == "AUTO_ACCEPTED" and "diagnosis" not in record


def test_source_grid_rejects_viewport_coordinates(setup_archive):
    _, _, context, image, contour, _ = setup_archive
    with pytest.raises(ValueError, match="source frame grid"):
        make_archive_sample(replace(contour, points=[(x * 8, y * 8) for x, y in contour.points]), image, context, "id")
    assert phase_semantics("LA", "GEN") == "unspecified"


def test_read_only_export_no_revision_or_salt_changes_and_no_automatic_gold(setup_archive, tmp_path):
    archive, capture, context, image, contour, _ = setup_archive
    capture.observe([contour], image, 2, context)
    capture.confirm(context.instance_key, 2)
    before = archive.path.read_bytes()
    output = tmp_path / "export"
    summary = export_archive(archive.path, output, {}, "seed")
    manifest = json.loads((output / "manifest.json").read_text())
    assert summary["exported"] == 1 and manifest["records"][0]["strong_label"] is False
    assert not list(output.glob("atlas-*.json")) and before == archive.path.read_bytes()
    np.testing.assert_array_equal(np.load(next(output.glob("*.npy"))), image)
    with pytest.raises(ValueError, match="new external"):
        export_archive(archive.path, output, {}, "seed")
    assert (
        main(["--archive", str(tmp_path / "missing"), "--output", str(tmp_path / "other"), "--acknowledge-local-phi"])
        == 2
    )


def test_split_unions_patients_studies_and_duplicate_pixels_before_deduplication():
    records = []
    for i, (patient, study, frame) in enumerate(
        [
            ("p1", "s1", "f1"),
            ("p1", "s2", "f2"),
            ("p2", "s2", "f3"),
            ("p3", "s3", "f3"),
            ("p3", "s4", "f4"),
            ("p4", "s5", "f5"),
        ]
    ):
        records.append(
            {
                "sample_id": str(i),
                "patient_key": patient,
                "study_key": study,
                "frame_hash": frame,
                "chamber": "LV",
                "phase_semantics": "ventricular_end_diastole",
                "points": [[1, 2]],
            }
        )
    split = split_archive_records(records)
    assert len(split) == 5  # identical frame annotation deduplicated
    assert len({r["split_group"] for r in split if r["sample_id"] != "5"}) == 1
    assert split_archive_records(list(reversed(records))) == split
    assert {r["split"] for r in split} <= {"train", "val", "test"}


def test_atlas_adapter_blocks_holdouts_stale_reviews_priors_and_ra(setup_archive):
    archive, capture, context, image, contour, _ = setup_archive
    capture.observe([contour], image, 2, context)
    capture.confirm(context.instance_key, 2)
    record = {**archive.records()[0], "split": "train"}
    reviewed = {record["sample_id"]: record["revision"]}
    assert reviewed_atlas_record(record, reviewed)["contours"] == {"LV": record["points"]}
    for change, reason in [
        ({"split": "val"}, "held_out"),
        ({"revision": 99}, "review_required"),
        ({"geometry_kind": "landmark_prior"}, "sparse_prior"),
        ({"chamber": "RA"}, "RA_archive"),
        ({"mitral_annulus": None}, "reviewed_open_arc"),
    ]:
        with pytest.raises(ValueError, match=reason):
            reviewed_atlas_record({**record, **change}, reviewed)


def test_reviewed_corpus_trains_from_saved_pixels_after_original_media_is_gone(setup_archive, tmp_path):
    from scripts.echo_template_data import TemplateDataset, assign_group_splits, load_measurement_corpus

    from echo_personal_tool.domain.services.echo_template_contract import default_atlases

    archive, capture, context, image, contour, _ = setup_archive
    capture.observe([contour], image, 2, context)
    capture.confirm(context.instance_key, 2)
    [record] = archive.records()
    reviewed = {record["sample_id"]: record["revision"]}
    output = tmp_path / "reviewed-corpus"
    export_archive(archive.path, output, reviewed, "seed")
    samples = load_measurement_corpus(output / "manifest.json")
    assert len(samples) == 1 and samples[0].frame_index == 0  # saved single source frame
    assign_group_splits(samples)
    batch = TemplateDataset(samples, default_atlases(), input_size=64)[0]
    assert batch["image"].shape == (3, 64, 64)
    assert 0 < batch["node_mask"].sum() < len(batch["node_mask"])  # only observed LV
    assert samples[0].split == json.loads((output / "manifest.json").read_text())["records"][0]["split"]
    # Unknown/unreviewed samples are not quietly made into a gold target.
    export_archive(archive.path, tmp_path / "unreviewed-corpus", {}, "seed")
    assert load_measurement_corpus(tmp_path / "unreviewed-corpus" / "manifest.json") == []


def test_atlas_export_contains_only_reviewed_train_records(setup_archive, tmp_path):
    from scripts.fit_cardiac_atlas_pca import observation_from_record

    from echo_personal_tool.domain.services.cardiac_atlas import build_cardiac_atlas
    from echo_personal_tool.domain.services.cardiac_atlas_pca import fit_atlas_pca

    archive, capture, context, image, contour, _ = setup_archive
    contours = []
    for phase in ("ED", "ES"):
        contours.append(replace(contour, phase=phase))
        capture.observe(contours, image, 2, context)
        capture.confirm(context.instance_key, 2)
    records = archive.records()
    reviewed = {r["sample_id"]: r["revision"] for r in records}
    # Choose a deterministic train split for this synthetic fixture only.
    seed = next(str(i) for i in range(100) if split_archive_records(records, seed=str(i))[0]["split"] == "train")
    output = tmp_path / "atlas-corpus"
    export_archive(archive.path, output, reviewed, seed)
    samples = json.loads((output / "atlas-A4C-train.json").read_text())["atlas_samples"]
    assert len(samples) == 2 and {s["phase"] for s in samples} == {"ED", "ES"}
    model = build_cardiac_atlas("A4C")
    observations = [observation_from_record(model, s) for s in samples]
    fitted = fit_atlas_pca(model, observations, max_modes=1)
    assert fitted.view == "A4C" and np.isfinite(fitted.mean_ed).all()
    assert np.isnan(observations[0].points).any()  # no invented LA/RV labels


def test_actual_three_landmark_fitter_marks_prior_not_strong_and_assist_keeps_ai_origin():
    from echo_personal_tool.domain.services.la_segmentation_service import build_la_assist_contour
    from echo_personal_tool.domain.services.mbs_lite_service import fit_contour_from_landmarks

    prior = fit_contour_from_landmarks(septal=(20.0, 90.0), lateral=(90.0, 90.0), apex=(45.0, 15.0), phase="ED")
    assert prior.geometry_kind == "landmark_prior" and prior.auto_generated
    accepted = make_archive_sample(
        replace(prior, source="manual", frame_index=2),
        np.zeros((128, 160)),
        ArchiveContext("p", "s", "series", "sop", "0.4.2"),
        "id",
    )
    assert accepted.metadata["origin"] == "AUTO_ACCEPTED"
    y, x = np.mgrid[:128, :128]
    mask = (((x - 60) / 30) ** 2 + ((y - 60) / 40) ** 2 < 1).astype(np.uint8)
    assisted = build_la_assist_contour(
        mask, user_septal=(30.0, 90.0), user_lateral=(90.0, 90.0), user_apex=(60.0, 20.0), frame_index=2
    )
    assert assisted is not None and assisted.auto_generated and assisted.source == "manual"


def test_local_collection_defaults_on_but_explicit_env_requires_external_directory(monkeypatch, tmp_path):
    import sys

    from echo_personal_tool.application.training_archive_runtime import local_archive_capture

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.delenv("SONOFORGE_LOCAL_TRAINING_ARCHIVE", raising=False)
    monkeypatch.delenv("SONOFORGE_LOCAL_TRAINING_ARCHIVE_DIR", raising=False)
    assert local_archive_capture(permitted=True) is not None
    monkeypatch.setenv("SONOFORGE_LOCAL_TRAINING_ARCHIVE", "1")
    assert local_archive_capture(permitted=True) is None
    monkeypatch.setenv("SONOFORGE_LOCAL_TRAINING_ARCHIVE_DIR", str(tmp_path))
    assert local_archive_capture(permitted=False) is None
    assert local_archive_capture(permitted=True) is not None
    assert not list(tmp_path.iterdir())  # lazy: flags alone don't create an archive
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert local_archive_capture(permitted=True) is None


def test_local_archive_and_export_refuse_git_tree(monkeypatch, tmp_path):
    from pathlib import Path

    from echo_personal_tool.application.training_archive_runtime import local_archive_capture

    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("SONOFORGE_LOCAL_TRAINING_ARCHIVE", "1")
    monkeypatch.setenv("SONOFORGE_LOCAL_TRAINING_ARCHIVE_DIR", str(root / "measurement-training-archive"))
    assert local_archive_capture(permitted=True) is None
    with pytest.raises(ValueError, match="external"):
        export_archive(tmp_path / "not-opened", root / "measurement-training-archive", {}, "seed")


def test_geometry_and_origin_metadata_survive_clinical_codec_roundtrip(tmp_path):
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
    from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository

    contour = Contour(
        "ES",
        source="manual",
        geometry_kind="landmark_prior",
        auto_generated=True,
        auto_edited=True,
        points=[(1.0, 1.0), (2.0, 3.0), (4.0, 1.0)],
        sop_instance_uid="1.2.697.1",
        frame_index=0,
    )
    repository = MeasurementRepository(tmp_path)
    repository.save(
        "1.2.697",
        StudyMeasurementData(contours=(contour,)),
        {"1.2.697.1": {"fingerprint": "a" * 64, "frames": 1, "spacing": [0.5, 0.5]}},
        0,
    )
    restored = repository.load("1.2.697")["data"]
    assert restored.contours == (contour,)


def test_missing_patient_identity_cannot_claim_independent_holdout():
    records = [
        {
            "sample_id": str(i),
            "patient_key": str(i),
            "study_key": str(i),
            "frame_hash": str(i),
            "patient_identity_known": i != 0,
            "chamber": "LV",
            "phase_semantics": "ventricular_end_diastole",
            "points": [[i, 1]],
        }
        for i in range(20)
    ]
    result = split_archive_records(records)
    assert len({r["split_group"] for r in result}) == 1
    assert len({r["split"] for r in result}) == 1


def test_support_bundle_never_copies_archive_pixels_or_metadata(setup_archive, tmp_path, monkeypatch):
    import zipfile

    import echo_personal_tool.infrastructure.diagnostics as diagnostics

    archive, capture, context, image, contour, _ = setup_archive
    capture.observe([contour], image, 2, context)
    capture.confirm(context.instance_key, 2)
    monkeypatch.setattr(diagnostics, "system_info_text", lambda app: "safe runtime")
    # Even deliberate colocation cannot make non-log media enter diagnostics.
    target = diagnostics.create_diagnostic_bundle(tmp_path / "support.zip", log_directory=archive.path.parent)
    with zipfile.ZipFile(target) as bundle:
        assert set(bundle.namelist()) == {"system-info.txt", "manifest.json"}
        assert all(b"patient-sensitive" not in bundle.read(name) for name in bundle.namelist())


@pytest.mark.parametrize(
    "change,reason", [({"chamber": "RA"}, "RA archive supported"), ({"mitral_annulus": None}, "reviewed open arcs")]
)
def test_training_adapter_refuses_unsupported_labels_explicitly(setup_archive, tmp_path, change, reason):
    from scripts.echo_template_data import load_measurement_corpus

    archive, capture, context, image, contour, _ = setup_archive
    capture.observe([contour], image, 2, context)
    capture.confirm(context.instance_key, 2)
    [record] = archive.records()
    output = tmp_path / "reviewed"
    export_archive(archive.path, output, {record["sample_id"]: record["revision"]}, "seed")
    path = output / "manifest.json"
    data = json.loads(path.read_text())
    data["records"][0].update(change)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=reason):
        load_measurement_corpus(path)


def test_auto_ef_legacy_edited_source_and_lowercase_phase_are_not_lost(setup_archive):
    archive, capture, context, image, contour, _ = setup_archive
    edited = replace(contour, source="ai_edited", phase="ed", auto_edited=False)
    capture.observe([edited], image, 2, context)
    capture.confirm(context.instance_key, 2)
    [record] = archive.records()
    assert record["origin"] == "AUTO_EDITED"
    assert record["phase"] == "ED"
    assert record["phase_semantics"] == "ventricular_end_diastole"
    # Case normalization must not create a second measurement slot.
    capture.observe([replace(edited, phase="ED")], image, 2, context)
    capture.confirm(context.instance_key, 2)
    assert len(archive.records()) == 1


def test_training_no_excludes_only_selected_material_and_survives_restart(setup_archive):
    archive, capture, context, image, contour, skipped = setup_archive
    offers = []
    capture.saved = offers.append
    capture.observe([contour], image, 2, context)
    capture.confirm(context.instance_key, 2)
    assert len(offers) == 1 and len(archive.records()) == 1
    assert capture.reject(offers[0])
    assert archive.records() == []
    assert archive.records(include_excluded=True)[0]["excluded"]
    # Re-observing an unchanged contour, including after restart, cannot undo No.
    fresh = MeasurementArchiveCapture(SqliteMeasurementArchive(archive.path), lambda: skipped.append(True))
    fresh.saved = offers.append
    fresh.observe([contour], image, 2, context)
    fresh.confirm(context.instance_key, 2)
    assert archive.records() == [] and len(offers) == 1
    # A genuinely edited contour is new material and defaults to Yes again.
    edited = replace(contour, points=[(x + 1, y) for x, y in contour.points])
    fresh.observe([edited], image, 2, context)
    fresh.confirm(context.instance_key, 2)
    assert len(archive.records()) == 1 and len(offers) == 2
    assert not fresh.reject(offers[0])  # old prompt cannot exclude the new edit
    assert len(archive.records()) == 1 and not skipped


def test_training_yes_default_is_idempotent_and_receipt_has_no_pixels(setup_archive):
    archive, capture, context, image, contour, _ = setup_archive
    offers = []
    capture.saved = offers.append
    for _ in range(2):
        capture.observe([contour], image, 2, context)
        capture.confirm(context.instance_key, 2)
    assert len(offers) == 1 and len(archive.records()) == 1
    assert not hasattr(offers[0], "pixels")
    assert context.patient_key not in repr(offers[0])
    assert contour.points == [(20.0, 90.0), (45.0, 15.0), (70.0, 30.0), (90.0, 90.0)]


def test_training_reject_failure_does_not_escape_or_lose_saved_material(setup_archive, monkeypatch):
    archive, capture, context, image, contour, skipped = setup_archive
    offers = []
    capture.saved = offers.append
    capture.observe([contour], image, 2, context)
    capture.confirm(context.instance_key, 2)

    def fail(_decision):
        raise ArchiveWriteError("unavailable")

    monkeypatch.setattr(archive, "reject_sample", fail)
    assert capture.reject(offers[0]) is False
    assert len(archive.records()) == 1 and skipped
