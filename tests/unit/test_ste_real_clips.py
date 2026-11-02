"""Real study clips: the fixture bundle must stay loadable and self-describing.

The original clips (``data/dicom/For_pero``) live in the private repository
``areatu/Sonoforge_data`` — they are not shipped with this public repo. In CI the
``ste-fixtures.yml`` workflow fetches them and ``tools/ste_fixture_export.py``
commits a compact derivative to ``tests/fixtures/for_pero`` — frames as JPEG plus
a scrubbed header summary. These tests are the contract for that bundle: they run
wherever it exists and skip where it does not, so a checkout without the fixtures
stays green while a checkout with them can never silently lose its real-clip
coverage.

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


def _is_lfs_pointer(path: Path) -> bool:
    """Return True if *path* is a Git LFS pointer file rather than real content.

    In sandboxes and in CI jobs that checkout without ``lfs: true`` the compact
    fixtures are 130-byte text pointers (``version https://git-lfs...``) instead
    of the real ``.npz`` bundle. Loading such a file with ``np.load`` raises
    ``_pickle.UnpicklingError`` — treat it as "fixtures not present" and skip
    the test rather than failing the whole suite. Once ``.gitattributes`` is
    fixed and the fixtures are re-exported as regular files this helper becomes
    a no-op (real ``.npz`` files are > 1 MB and start with the ZIP magic).
    """
    try:
        if path.stat().st_size >= 1024:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
        return text.startswith("version https://git-lfs")
    except Exception:  # noqa: BLE001
        return False


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
        # 10 true cine loops (gold1..gold8, gold_Ph_ECG1/2); the 9 vendor screen
        # captures (strain_*) are exported as PNG stills (kind=vendor_screen_still)
        # and are not counted here — see tools/ste_fixture_export.py:_is_still_screen.
        if any(_is_lfs_pointer(FIXTURES / c["npz"]) for c in clips if c.get("npz")):
            pytest.skip("LFS content not fetched — compact fixtures are still pointers")
        assert len(clips) >= 10, f"expected the full study set, got {len(clips)}"
        names = {clip["file"] for clip in clips}
        assert {"gold1.dcm", "gold7+ECG.dcm"} <= names
        for clip in clips:
            assert clip["frames"] > 0
            assert clip["fps"] >= 0.0
            p = Path(FIXTURES, clip["npz"])
            assert p.is_file()
            if _is_lfs_pointer(p):
                pytest.skip(f"{clip['npz']} is still an LFS pointer — fetch with 'git lfs pull'")

    @pytest.mark.parametrize("clip_name", ["gold1.dcm", "gold7+ECG.dcm", "gold_Ph_ECG1"])
    def test_clip_decodes_to_usable_frames(self, clip_name: str) -> None:
        clip = next((c for c in _clips() if c["file"] == clip_name), None)
        assert clip is not None, f"{clip_name} missing from the bundle"
        npz_path = FIXTURES / clip["npz"]
        if _is_lfs_pointer(npz_path):
            pytest.skip(f"{clip_name}: LFS content not fetched — {npz_path} is a pointer")

        with np.load(npz_path, allow_pickle=True) as bundle:
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
        npz_path = FIXTURES / clip["npz"]
        if _is_lfs_pointer(npz_path):
            pytest.skip("LFS content not fetched — compact fixtures are still pointers")
        with np.load(npz_path, allow_pickle=True) as bundle:
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
