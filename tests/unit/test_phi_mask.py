"""Tests for the burned-in PHI mask.

The numbers asserted here are the measured values of the 245-file corpus, not
arbitrary constants: if a profile changes, these tests must be the place where
the change is justified.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset

from echo_personal_tool.domain.services.phi_mask import (
    MaskRect,
    MaskSpec,
    apply_mask,
    band_extent,
    estimate_background,
    resolve_mask_plan,
)
from echo_personal_tool.infrastructure.phi_mask_profiles import (
    PhiMaskContext,
    clear_phi_mask_context_cache,
    masks_disabled_by_header,
    phi_mask_context,
    resolve_mask_spec,
)
from echo_personal_tool.infrastructure.vendor_profiles.base import Vendor
from echo_personal_tool.presentation.anonymization_filter import (
    BACKGROUND_REFRESH_EVERY,
    AnonymizationFilter,
)

# ── Geometry ────────────────────────────────────────────────────────────


def test_top_band_is_profile_fraction_of_height() -> None:
    spec = MaskSpec(top=0.14)
    plan = resolve_mask_plan(spec, height=1080, width=1920)
    assert len(plan.rects) == 1
    assert plan.rects[0] == MaskRect(0, 0, 1920, 151)


def test_top_band_is_clamped_to_the_first_panel_row() -> None:
    """Samsung 884x1180: 12 % would be 106 rows, the sector starts at 100."""
    spec = resolve_mask_spec(Vendor.SAMSUNG, 884, 1180)
    plan = resolve_mask_plan(spec, height=884, width=1180, panel_top=100)
    assert plan.rects[0].y1 == 100


def test_clamp_never_grows_the_band() -> None:
    spec = MaskSpec(top=0.12)
    plan = resolve_mask_plan(spec, height=800, width=1276, panel_top=90)
    assert plan.rects[0].y1 == 90
    # Panel below the profile: the profile must stay as it is, not stretch.
    plan = resolve_mask_plan(spec, height=800, width=1276, panel_top=200)
    assert plan.rects[0].y1 == 96


def test_band_survives_without_region_geometry() -> None:
    """22 Samsung strain files have no SequenceOfUltrasoundRegions."""
    spec = resolve_mask_spec(Vendor.SAMSUNG, 1080, 1920)
    plan = resolve_mask_plan(spec, height=1080, width=1920, panel_top=None)
    assert plan.rects[0].y1 == 151


def test_absurd_fraction_is_capped_at_half_the_side() -> None:
    assert band_extent(0.9, 1000) == 500
    assert band_extent(-1.0, 1000) == 0
    assert band_extent(0.0, 1000) == 0


def test_all_four_sides_are_configurable() -> None:
    spec = MaskSpec(top=0.10, bottom=0.10, left=0.05, right=0.05)
    plan = resolve_mask_plan(spec, height=200, width=400)
    assert plan.rects == (
        MaskRect(0, 0, 400, 20),
        MaskRect(0, 180, 400, 200),
        MaskRect(0, 0, 20, 200),
        MaskRect(380, 0, 400, 200),
    )


def test_empty_plan_when_nothing_to_mask() -> None:
    plan = resolve_mask_plan(MaskSpec(), height=884, width=1180)
    assert plan.is_empty
    assert plan.reason == "no-bands"


def test_disabled_and_degenerate_frames_yield_empty_plans() -> None:
    assert resolve_mask_plan(MaskSpec(top=0.12), 884, 1180, enabled=False).reason == "disabled"
    assert resolve_mask_plan(MaskSpec(top=0.12), 0, 0).reason == "empty-frame"


# ── Profiles ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("vendor", "height", "width", "expected_top"),
    [
        (Vendor.SAMSUNG, 800, 1276, 0.12),
        (Vendor.SAMSUNG, 884, 1180, 0.12),
        (Vendor.SAMSUNG, 480, 640, 0.12),
        (Vendor.SAMSUNG, 1080, 1920, 0.14),
        # Strain analysis screen: the top of the frame is UI, not a header.
        (Vendor.SAMSUNG, 668, 1280, 0.0),
        (Vendor.PHILIPS, 768, 1024, 0.0),
        (Vendor.PHILIPS, 600, 800, 0.0),
        (Vendor.GE, 708, 1016, 0.0),
    ],
)
def test_measured_profiles(vendor: Vendor, height: int, width: int, expected_top: float) -> None:
    assert resolve_mask_spec(vendor, height, width).top == expected_top


def test_strain_analysis_screen_is_marked_as_ui() -> None:
    """A text detector must not auto-extend the mask over "3 Point Contour"."""
    assert resolve_mask_spec(Vendor.SAMSUNG, 668, 1280).preserve_ui is True


def test_unmeasured_resolution_falls_back_to_the_vendor() -> None:
    assert resolve_mask_spec(Vendor.SAMSUNG, 999, 999).top == 0.12
    assert resolve_mask_spec(Vendor.PHILIPS, 999, 999).top == 0.0


def test_unknown_vendor_is_masked_conservatively() -> None:
    """MP4/JPEG exports and unmeasured scanners: 10 %, no panel to clamp to."""
    assert resolve_mask_spec(Vendor.UNKNOWN, 1080, 1920).top == 0.10


# ── Filling ─────────────────────────────────────────────────────────────


def _frame_with_header(height: int = 200, width: int = 300) -> np.ndarray:
    """A realistic header: sparse bright glyphs over a dark background.

    Glyph coverage is kept around 15 % of the band, which is what the measured
    Samsung/GE/Philips header lines actually look like.  A synthetic frame that
    fills the whole band with the text colour would break the median-based
    background estimate — not because the estimate is wrong, but because such a
    band does not exist on a scanner.
    """
    frame = np.full((height, width), 20, dtype=np.uint8)
    frame[60:, :] = 90  # "sector"
    frame[5:20, 20:80] = 250  # glyphs: 15 % of the 20-row band
    return frame


def test_mask_fills_the_band_with_the_background_median() -> None:
    frame = _frame_with_header()
    plan = resolve_mask_plan(MaskSpec(top=0.10), *frame.shape[:2])
    masked = apply_mask(frame, plan)

    assert masked[0:20, :].min() == masked[0:20, :].max() == 20
    # Everything below the band is untouched.
    np.testing.assert_array_equal(masked[20:, :], frame[20:, :])


def test_mask_never_modifies_the_source_frame() -> None:
    """Frames are shared with the cache, playback, M-mode and export."""
    frame = _frame_with_header()
    original = frame.copy()
    plan = resolve_mask_plan(MaskSpec(top=0.10), *frame.shape[:2])
    masked = apply_mask(frame, plan)

    assert masked is not frame
    np.testing.assert_array_equal(frame, original)


def test_empty_plan_returns_the_input_object_unchanged() -> None:
    frame = _frame_with_header()
    empty = resolve_mask_plan(MaskSpec(), *frame.shape[:2])
    assert apply_mask(frame, empty) is frame


def test_colour_frames_are_filled_per_channel() -> None:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[:, :] = (10, 40, 90)
    frame[0:8, 10:40] = (250, 250, 250)
    plan = resolve_mask_plan(MaskSpec(top=0.10), *frame.shape[:2])
    masked = apply_mask(frame, plan)

    assert tuple(masked[5, 60]) == (10, 40, 90)
    # A colour frame must not turn gray in the band.
    assert tuple(masked[5, 60]) != (40, 40, 40)


def test_background_estimate_ignores_sparse_glyphs() -> None:
    frame = _frame_with_header()
    rect = MaskRect(0, 0, 300, 20)
    assert estimate_background(frame, rect) == 20


def test_rect_is_clamped_to_the_frame() -> None:
    plan = resolve_mask_plan(MaskSpec(top=0.5, right=0.5), height=10, width=10)
    small = np.full((10, 10), 7, dtype=np.uint8)
    masked = apply_mask(small, plan)
    assert masked.shape == (10, 10)


# ── Filter and DICOM header ─────────────────────────────────────────────


def _write_dicom(path, *, manufacturer: str, panel_top: int | None, burned_in: str | None) -> str:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    meta.MediaStorageSOPInstanceUID = "1.2.3.4.5"
    meta.TransferSyntaxUID = "1.2.840.10008.1.2.1"
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.Manufacturer = manufacturer
    if burned_in is not None:
        ds.BurnedInAnnotation = burned_in
    if panel_top is not None:
        region = Dataset()
        region.RegionLocationMinX0 = 0
        region.RegionLocationMinY0 = panel_top
        region.RegionLocationMaxX1 = 1180
        region.RegionLocationMaxY1 = 884
        region.RegionSpatialFormat = 1
        region.RegionDataType = 1
        ds.SequenceOfUltrasoundRegions = [region]
    ds.save_as(str(path), enforce_file_format=False)
    return str(path)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_phi_mask_context_cache()


def test_context_is_read_from_the_dicom_header(tmp_path) -> None:
    path = _write_dicom(tmp_path / "samsung.dcm", manufacturer="SAMSUNG", panel_top=100, burned_in="YES")
    context = phi_mask_context(path)
    assert context.vendor is Vendor.SAMSUNG
    assert context.panel_top == 100
    assert context.burned_in == "YES"


def test_non_dicom_and_missing_files_are_safe(tmp_path) -> None:
    assert phi_mask_context(tmp_path / "clip.mp4").vendor is Vendor.UNKNOWN
    assert phi_mask_context(tmp_path / "nope.dcm").panel_top is None
    assert phi_mask_context(None) == PhiMaskContext()


def test_broken_dicom_does_not_raise(tmp_path) -> None:
    broken = tmp_path / "broken.dcm"
    broken.write_bytes(b"not a dicom at all")
    assert phi_mask_context(broken) == PhiMaskContext()


def test_burned_in_annotation_no_disables_the_mask(tmp_path) -> None:
    path = _write_dicom(tmp_path / "clean.dcm", manufacturer="SAMSUNG", panel_top=100, burned_in="NO")
    frame = np.full((884, 1180), 30, dtype=np.uint8)
    frame[0:100, :] = 200

    filter_ = AnonymizationFilter(enabled=True)
    masked = filter_.apply(frame, path)

    # The file declares no burned-in text: leave its pixels alone.
    assert masked is frame
    assert filter_.last_plan.reason == "burned-in-annotation-no"
    assert masks_disabled_by_header(phi_mask_context(path)) is True


def test_filter_masks_a_samsung_frame_when_enabled(tmp_path) -> None:
    path = _write_dicom(tmp_path / "samsung.dcm", manufacturer="SAMSUNG", panel_top=100, burned_in="YES")
    frame = np.full((884, 1180), 30, dtype=np.uint8)
    frame[0:100, 100:600] = 250

    filter_ = AnonymizationFilter(enabled=True)
    masked = filter_.apply(frame, path)

    assert masked is not frame
    assert masked[0:100, :].max() == 30
    np.testing.assert_array_equal(masked[100:, :], frame[100:, :])


def test_disabled_filter_returns_the_same_object(tmp_path) -> None:
    path = _write_dicom(tmp_path / "samsung.dcm", manufacturer="SAMSUNG", panel_top=100, burned_in="YES")
    frame = np.full((884, 1180), 30, dtype=np.uint8)
    filter_ = AnonymizationFilter(enabled=False)
    assert filter_.apply(frame, path) is frame

    filter_.set_enabled(True)
    assert filter_.apply(frame, path) is not frame
    filter_.set_enabled(False)
    assert filter_.apply(frame, path) is frame


def test_fill_colour_is_measured_once_per_clip(tmp_path) -> None:
    """The background is a property of the clip, not of the frame.

    Measuring it on every frame costs more than the fill itself (2.2 ms versus
    0.6 ms on a 720p RGB frame), so the colour is cached and reused.
    """
    path = _write_dicom(tmp_path / "samsung.dcm", manufacturer="SAMSUNG", panel_top=100, burned_in="YES")
    first = np.full((884, 1180), 30, dtype=np.uint8)
    first[0:100, 100:600] = 250
    second = np.full((884, 1180), 60, dtype=np.uint8)
    second[0:100, 100:600] = 250

    filter_ = AnonymizationFilter(enabled=True)
    first_masked = filter_.apply(first, path)
    second_masked = filter_.apply(second, path)

    assert first_masked[0, 0] == 30
    assert second_masked[0, 0] == 30  # reused, not re-measured
    assert second_masked[200, 0] == 60  # the rest of the frame is untouched


def test_fill_colour_is_refreshed_periodically(tmp_path) -> None:
    """A cached colour must not survive a clip that changes its background."""
    path = _write_dicom(tmp_path / "samsung.dcm", manufacturer="SAMSUNG", panel_top=100, burned_in="YES")
    dark = np.full((884, 1180), 30, dtype=np.uint8)
    light = np.full((884, 1180), 90, dtype=np.uint8)

    filter_ = AnonymizationFilter(enabled=True)
    for _ in range(BACKGROUND_REFRESH_EVERY + 1):
        filter_.apply(dark, path)
    refreshed = filter_.apply(light, path)

    assert refreshed[0, 0] == 90


def test_unknown_file_uses_the_conservative_default(tmp_path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\0" * 16)
    frame = np.full((1080, 1920), 15, dtype=np.uint8)
    frame[0:150, 100:600] = 240  # a text line, 36 % of the band

    filter_ = AnonymizationFilter(enabled=True)
    masked = filter_.apply(frame, str(clip))

    # 10 % of 1080 = 108 rows, filled with the band's own background.
    assert masked[0:108, :].std() == 0
    assert masked[0:108, :].max() == 15
    assert masked[130, 300] == 240  # below the band, untouched


def test_solid_band_fills_with_its_own_colour() -> None:
    """Documented degenerate case: a band that is 100 % "text".

    The fill then equals that colour, so nothing is hidden — but nothing can be
    *revealed* either.  Real scanners do not produce such a band; the test
    exists so the behaviour is a decision and not a surprise.
    """
    frame = np.full((100, 100), 7, dtype=np.uint8)
    frame[0:20, :] = 240
    plan = resolve_mask_plan(MaskSpec(top=0.2), *frame.shape[:2])
    masked = apply_mask(frame, plan)

    assert masked[0:20, :].max() == 240
    assert masked[0:20, :].std() == 0
