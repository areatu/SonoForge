"""Real study clips: the fixture bundle must stay loadable and self-describing.

The clips in ``data/dicom/For_pero`` are Git LFS objects, and the development
sandbox can reach the Git host but not the LFS content host. ``tools/ste_fixture_export.py``
runs in CI (where LFS *is* reachable) and commits a compact derivative to
``tests/fixtures/for_pero`` — frames as JPEG plus a scrubbed header summary.
These tests are the contract for that bundle: they run wherever it exists and skip
where it does not, so a checkout without the fixtures stays green while a checkout
with them can never silently lose its real-clip coverage.

What is checked (and what is deliberately not): the bundle must decode to the
frames and geometry the analysis code needs. Vendor strain values are *not*
asserted here — they live in ``docs/STE_VENDOR_REFERENCE.md`` and are only
comparable once contours for these clips exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "for_pero"
INDEX = FIXTURES / "index.json"

pytestmark = pytest.mark.skipif(not INDEX.is_file(), reason="real-clip fixtures not exported in this checkout")


def _index() -> dict:
    return json.loads(INDEX.read_text(encoding="utf-8"))


def _clips() -> list[dict]:
    return [entry for entry in _index()["clips"] if entry.get("kind") == "dicom" and entry.get("npz")]


def _decode(bundle: np.lib.npyio.NpzFile, index: int) -> np.ndarray:
    import cv2

    raw = bundle["frames_jpeg"][index]
    frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert frame is not None, "JPEG frame does not decode"
    return frame


class TestFixtureBundle:
    def test_index_lists_the_study_clips(self) -> None:
        clips = _clips()
        assert len(clips) >= 15, f"expected the full study set, got {len(clips)}"
        names = {clip["file"] for clip in clips}
        assert {"gold1.dcm", "gold7+ECG.dcm"} <= names
        for clip in clips:
            assert clip["frames"] > 0
            assert clip["fps"] >= 0.0
            assert Path(FIXTURES, clip["npz"]).is_file()

    @pytest.mark.parametrize("clip_name", ["gold1.dcm", "gold7+ECG.dcm", "gold_Ph_ECG1"])
    def test_clip_decodes_to_usable_frames(self, clip_name: str) -> None:
        clip = next((c for c in _clips() if c["file"] == clip_name), None)
        assert clip is not None, f"{clip_name} missing from the bundle"

        with np.load(FIXTURES / clip["npz"], allow_pickle=True) as bundle:
            frames = bundle["frames_jpeg"]
            assert len(frames) == clip["frames"]
            middle = _decode(bundle, len(frames) // 2)
            first = _decode(bundle, 0)
            assert middle.shape == (clip["shape"][1], clip["shape"][2])
            # A frame that is flat (or identical to the first one) would mean the
            # cine was exported as a single still — the tracker needs real motion.
            assert float(middle.std()) > 5.0, f"{clip_name}: frame looks flat"
            assert not np.array_equal(first, middle), f"{clip_name}: frames do not change"
            assert float(bundle["pixel_spacing_mm"][0]) > 0.0
            assert float(bundle["fps"]) > 0.0

    def test_geometry_is_consistent_across_frames(self) -> None:
        """Every frame of a clip must carry the same size, or overlays misalign."""
        clip = next(c for c in _clips() if c["file"] == "gold7+ECG.dcm")
        with np.load(FIXTURES / clip["npz"], allow_pickle=True) as bundle:
            for index in (0, len(bundle["frames_jpeg"]) - 1):
                frame = _decode(bundle, index)
                assert frame.shape == (clip["shape"][1], clip["shape"][2])

    def test_header_summary_is_scrubbed(self) -> None:
        """The derivative travels through the repository: no identifiers in it."""
        forbidden = {"PatientName", "PatientID", "PatientBirthDate", "InstitutionName"}
        for entry in _clips():
            summary = json.loads((FIXTURES / f"{Path(entry['file']).stem}.json").read_text(encoding="utf-8"))
            assert forbidden.isdisjoint(summary), f"{entry['file']}: identifiers leaked into the summary"
            for key in ("Manufacturer", "frames", "fps"):
                assert key in summary

    def test_ecg_is_burned_into_the_image_not_a_waveform_tag(self) -> None:
        """Documents a limitation the ECG detector has to live with."""
        for name in ("gold7+ECG", "gold8+ECG"):
            summary = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
            assert summary["ecg"] is False, "a waveform sequence appeared — the exporter should report it"
            assert summary["ecg_burn_in_hint"] is True
