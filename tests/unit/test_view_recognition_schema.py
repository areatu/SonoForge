"""Tests for the view-recognition dataset schema (#639 step 4 design).

Covers the canonicalisation of scanner-side view labels (ProtocolName /
view-tags), the manifest schema versions (v1 compatibility + v2 metadata),
and the persisted decision model.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.view_recognition import (
    ALL_RECOGNIZABLE_VIEWS,
    EXTENDED_KNOWN_VIEWS,
    KNOWN_VIEWS,
    MANIFEST_SCHEMA_VERSION,
    TTE_STANDARD_VIEWS,
    UNKNOWN_VIEW,
    ViewDecision,
    ViewDecisionSource,
    ViewRecognitionManifest,
    ViewRecognitionSample,
    ViewSampleMetadata,
    canonicalize_view,
    clip_label_index,
    view_category,
)


class TestCanonicalizeView:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("A4C", "A4C"),
            ("a4c", "A4C"),
            ("  A4C  ", "A4C"),
            ("AP4", "A4C"),
            ("4CH", "A4C"),
            ("4-Chamber", "A4C"),
            ("AP2", "A2C"),
            ("2CH", "A2C"),
            ("AP3", "A3C"),
            ("PLAX", "PLAX"),
            ("plax", "PLAX"),
            ("LVOT", "PLAX"),
            ("SAX", "SAX"),
            ("SHORT AXIS", "SAX"),
            ("PSAX", "PSAX"),
            ("PSSAX", "SAX"),
            ("TEE", "TEE"),
            ("Transesophageal", "TEE"),
            ("RV_A4C", "RV_A4C"),
            ("RV-A4C", "RV_A4C"),
            ("RV4C", "RV_A4C"),
            ("RV FOCUSED", "RV_A4C"),
            ("SUBCOSTAL", "SUBCOSTAL"),
            ("Subxiphoid", "SUBCOSTAL"),
            ("SC4C", "SUBCOSTAL"),
        ],
    )
    def test_aliases_map_to_canonical(self, raw: str, expected: str) -> None:
        assert canonicalize_view(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "nonsense", "A5C", "XYZ"])
    def test_unknown_labels_degrade_to_unknown(self, raw: str) -> None:
        assert canonicalize_view(raw) == UNKNOWN_VIEW

    def test_canonical_names_pass_through(self) -> None:
        for view in EXTENDED_KNOWN_VIEWS:
            assert canonicalize_view(view) == view
        assert set(KNOWN_VIEWS).issubset(ALL_RECOGNIZABLE_VIEWS)
        assert set(TTE_STANDARD_VIEWS).issubset(ALL_RECOGNIZABLE_VIEWS)

    def test_category_covers_canonical_views(self) -> None:
        for view in EXTENDED_KNOWN_VIEWS:
            assert view_category(view) != "unknown"
        assert view_category("RV_A4C") == "apical"
        assert view_category("SUBCOSTAL") == "subcostal"
        assert view_category(UNKNOWN_VIEW) == "unknown"


class TestManifestSchema:
    def test_v2_round_trip_keeps_metadata(self) -> None:
        sample = ViewRecognitionSample(
            sample_id="s1",
            source_path="/a.dcm",
            view="A4C",
            split="train",
            metadata=ViewSampleMetadata(
                protocol_name="AP4",
                vendor="vendor-x",
                view_tag="4CH",
                acquisition_note="good quality",
            ),
        )
        manifest = ViewRecognitionManifest(samples=(sample,))
        restored = ViewRecognitionManifest.from_dict(manifest.to_dict())
        assert restored == manifest
        assert restored.schema_version == MANIFEST_SCHEMA_VERSION
        assert restored.class_names == KNOWN_VIEWS
        assert restored.samples[0].metadata is not None
        assert restored.samples[0].metadata.protocol_name == "AP4"
        assert restored.samples[0].metadata.vendor == "vendor-x"

    def test_v1_manifest_loads_with_defaults(self) -> None:
        """PR-A manifests (no schema_version / class_names) stay compatible."""
        raw = {"samples": [{"sample_id": "s1", "source_path": "/a.dcm", "view": "A4C", "split": "train"}]}
        manifest = ViewRecognitionManifest.from_dict(raw)
        assert manifest.schema_version == 1
        assert manifest.class_names == KNOWN_VIEWS
        assert manifest.samples[0].metadata is None

    def test_explicit_class_names_are_pinned(self) -> None:
        subset = ("A4C", "PLAX")
        raw = {
            "schema_version": 2,
            "class_names": list(subset),
            "samples": [{"sample_id": "s1", "source_path": "/a.dcm", "view": "A4C", "split": "train"}],
        }
        manifest = ViewRecognitionManifest.from_dict(raw)
        assert manifest.class_names == subset
        assert clip_label_index("A4C", manifest.class_names) == 0
        assert clip_label_index("PLAX", manifest.class_names) == 1
        assert clip_label_index("A2C", manifest.class_names) == -1

    def test_split_assignment_query(self) -> None:
        manifest = ViewRecognitionManifest(
            samples=(
                ViewRecognitionSample("s1", "/a", "A4C", "train"),
                ViewRecognitionSample("s2", "/b", "PLAX", "val"),
                ViewRecognitionSample("s3", "/c", "SAX", "val"),
            )
        )
        assert manifest.sample_ids_with_split("val") == ["s2", "s3"]
        assert manifest.sample_ids_with_split("test") == []


class TestViewDecisionModel:
    def test_decision_round_trip(self) -> None:
        decision = ViewDecision(
            study_uid="study-1",
            series_uid="series-1",
            view="A2C",
            source=ViewDecisionSource.MANUAL,
            confidence=1.0,
            profile_id="builtin.adult_echo",
        )
        restored = ViewDecision.from_dict(decision.to_dict())
        assert restored == decision

    def test_decision_without_profile(self) -> None:
        decision = ViewDecision(
            study_uid="s",
            series_uid="se",
            view=UNKNOWN_VIEW,
            source=ViewDecisionSource.AUTO,
            confidence=0.0,
            profile_id=None,
        )
        restored = ViewDecision.from_dict(decision.to_dict())
        assert restored.profile_id is None
        assert restored.source is ViewDecisionSource.AUTO
