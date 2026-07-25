"""Migration tests for gold store merge_frame_into_gold with conflicting data."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.gold_store import (
    audit_gold_instance_completeness,
    dedupe_gold_frames,
    frame_merge_key,
    make_gold_frame,
    make_gold_study,
    merge_frame_into_gold,
)


def _make_existing() -> dict:
    return make_gold_study(
        study_id="1.2.840.merge",
        instance_path="/data/gold1.dcm",
        pixel_spacing_mm=[0.15, 0.15],
    )


class TestMergeFrameConflicts:
    """merge_frame_into_gold handles conflicting data correctly."""

    def test_merge_same_instance_replaces(self) -> None:
        existing = _make_existing()
        frame_ed = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[0, 0], [5, 0], [5, 5]],
            mitral_annulus=[[0, 0], [5, 0]],
            instance_path="/data/gold1.dcm",
        )
        existing = merge_frame_into_gold(existing, frame_ed)
        assert len(existing["frames"]) == 1

        # Re-save ED on same instance
        updated_ed = make_gold_frame(
            frame_index=99,
            phase="ED",
            points=[[1, 1], [6, 1], [6, 6]],
            mitral_annulus=[[1, 1], [6, 1]],
            instance_path="/data/gold1.dcm",
        )
        merged = merge_frame_into_gold(existing, updated_ed)
        assert len(merged["frames"]) == 1
        assert merged["frames"][0]["frame_index"] == 99

    def test_merge_different_instance_adds(self) -> None:
        existing = _make_existing()
        frame_ed = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[0, 0], [5, 0], [5, 5]],
            mitral_annulus=[[0, 0], [5, 0]],
            instance_path="/data/gold1.dcm",
        )
        existing = merge_frame_into_gold(existing, frame_ed)

        # Add ED from different DICOM
        other_ed = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[0, 0], [6, 0], [6, 6]],
            mitral_annulus=[[0, 0], [6, 0]],
            instance_path="/data/gold2.dcm",
        )
        merged = merge_frame_into_gold(existing, other_ed)
        assert len(merged["frames"]) == 2

    def test_merge_updates_top_level_instance_path(self) -> None:
        existing = _make_existing()
        frame = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[0, 0], [5, 0], [5, 5]],
            mitral_annulus=[[0, 0], [5, 0]],
            instance_path="/data/gold2.dcm",
        )
        merged = merge_frame_into_gold(existing, frame)
        assert merged["instance_path"] == "/data/gold2.dcm"

    def test_merge_preserves_existing_instance_path(self) -> None:
        existing = _make_existing()
        frame = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[0, 0], [5, 0], [5, 5]],
            mitral_annulus=[[0, 0], [5, 0]],
            instance_path="/data/gold1.dcm",
        )
        merged = merge_frame_into_gold(existing, frame)
        assert merged["instance_path"] == "/data/gold1.dcm"

    def test_merge_ed_and_es_same_instance(self) -> None:
        existing = _make_existing()
        frame_ed = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[0, 0], [5, 0], [5, 5]],
            mitral_annulus=[[0, 0], [5, 0]],
            instance_path="/data/gold1.dcm",
        )
        existing = merge_frame_into_gold(existing, frame_ed)

        frame_es = make_gold_frame(
            frame_index=25,
            phase="ES",
            points=[[0, 0], [4, 0], [4, 4]],
            mitral_annulus=[[0, 0], [4, 0]],
            instance_path="/data/gold1.dcm",
        )
        merged = merge_frame_into_gold(existing, frame_es)
        assert len(merged["frames"]) == 2
        phases = {f["phase"] for f in merged["frames"]}
        assert phases == {"ED", "ES"}

    def test_merge_does_not_duplicate_same_key(self) -> None:
        existing = _make_existing()
        frame = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[0, 0], [5, 0], [5, 5]],
            mitral_annulus=[[0, 0], [5, 0]],
            instance_path="/data/gold1.dcm",
        )
        existing = merge_frame_into_gold(existing, frame)
        existing = merge_frame_into_gold(existing, frame)
        assert len(existing["frames"]) == 1

    def test_merge_conflicting_points_keeps_newest(self) -> None:
        existing = _make_existing()
        frame_old = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[0, 0], [5, 0], [5, 5]],
            mitral_annulus=[[0, 0], [5, 0]],
            instance_path="/data/gold1.dcm",
        )
        existing = merge_frame_into_gold(existing, frame_old)

        frame_new = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[1, 1], [6, 1], [6, 6]],
            mitral_annulus=[[1, 1], [6, 1]],
            instance_path="/data/gold1.dcm",
        )
        merged = merge_frame_into_gold(existing, frame_new)
        assert merged["frames"][0]["points"] == [[1, 1], [6, 1], [6, 6]]


class TestMergeMultipleInstances:
    """Multiple DICOM instances in one study."""

    def test_three_instances(self) -> None:
        existing = _make_existing()
        for i in range(3):
            frame = make_gold_frame(
                frame_index=10 + i,
                phase="ED",
                points=[[0, 0], [5 + i, 0], [5 + i, 5]],
                mitral_annulus=[[0, 0], [5 + i, 0]],
                instance_path=f"/data/gold{i}.dcm",
            )
            existing = merge_frame_into_gold(existing, frame)

        assert len(existing["frames"]) == 3
        keys = {frame_merge_key(f, study=existing) for f in existing["frames"]}
        assert len(keys) == 3

    def test_ed_es_per_instance(self) -> None:
        existing = _make_existing()
        for phase, idx in [("ED", 10), ("ES", 20)]:
            frame = make_gold_frame(
                frame_index=idx,
                phase=phase,
                points=[[0, 0], [5, 0], [5, 5]],
                mitral_annulus=[[0, 0], [5, 0]],
                instance_path="/data/gold1.dcm",
            )
            existing = merge_frame_into_gold(existing, frame)

        report = audit_gold_instance_completeness(existing)
        assert report["complete_count"] == 1


class TestMergeFrameIntoGoldEdgeCases:
    """Edge cases for merge_frame_into_gold."""

    def test_merge_empty_study(self) -> None:
        existing = {
            "study_id": "test",
            "instance_path": "/data/test.dcm",
            "frames": [],
        }
        frame = make_gold_frame(
            frame_index=0,
            phase="ED",
            points=[[0, 0], [1, 0], [0, 1]],
            mitral_annulus=[[0, 0], [1, 0]],
        )
        merged = merge_frame_into_gold(existing, frame)
        assert len(merged["frames"]) == 1

    def test_merge_preserves_existing_fields(self) -> None:
        existing = _make_existing()
        existing["custom_field"] = "keep_me"
        frame = make_gold_frame(
            frame_index=0,
            phase="ED",
            points=[[0, 0], [1, 0], [0, 1]],
            mitral_annulus=[[0, 0], [1, 0]],
        )
        merged = merge_frame_into_gold(existing, frame)
        assert merged.get("custom_field") == "keep_me"

    def test_merge_does_not_mutate_original(self) -> None:
        existing = _make_existing()
        original_frames = list(existing["frames"])
        frame = make_gold_frame(
            frame_index=0,
            phase="ED",
            points=[[0, 0], [1, 0], [0, 1]],
            mitral_annulus=[[0, 0], [1, 0]],
        )
        merge_frame_into_gold(existing, frame)
        assert existing["frames"] == original_frames
