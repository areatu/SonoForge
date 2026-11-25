"""DICOM display chain: modality values, VOI, MONOCHROME1 and padding (542)."""

from __future__ import annotations

import numpy as np
from pydicom.dataset import Dataset

from echo_personal_tool.domain.models.dicom_display import DicomDisplay, LookupTable, WindowPreset
from echo_personal_tool.imaging.dicom_display import (
    modality_value,
    render_dicom_frame,
    stored_to_modality,
)
from echo_personal_tool.infrastructure.dicom_metadata_mapper import map_instance_metadata


def _ct(**kwargs) -> DicomDisplay:
    base = dict(rescale_slope=1.0, rescale_intercept=-1024.0, value_unit="HU")
    base.update(kwargs)
    return DicomDisplay(**base)


def _ds(**fields) -> Dataset:
    ds = Dataset()
    ds.Modality = "CT"
    ds.SOPInstanceUID = "1.2.3"
    ds.SeriesInstanceUID = "1.2.4"
    ds.StudyInstanceUID = "1.2.5"
    ds.SeriesDescription = "CT"
    ds.PixelSpacing = [0.5, 0.5]
    for name, value in fields.items():
        setattr(ds, name, value)
    return ds


def test_rescale_maps_stored_values_to_hu() -> None:
    stored = np.array([[0, 1024, 2048]], dtype=np.int16)
    display = _ct()

    assert stored_to_modality(stored, display).tolist() == [[-1024.0, 0.0, 1024.0]]
    assert modality_value(0, display) == -1024.0
    assert modality_value(1024, display) == 0.0


def test_modality_lut_replaces_rescale() -> None:
    display = DicomDisplay(modality_lut=LookupTable(first_input=0, entries=(10.0, 20.0, 30.0)))

    assert stored_to_modality(np.array([0, 1, 2, 9]), display).tolist() == [10.0, 20.0, 30.0, 30.0]
    assert modality_value(1, display) == 20.0


def test_linear_window_keeps_negative_ct_values_distinct() -> None:
    stored = np.array([[0, 524, 1024, 1524, 2048]], dtype=np.int16)
    rendered = render_dicom_frame(
        stored,
        _ct(window_presets=(WindowPreset(center=0, width=1000, explanation="soft"),)),
    )

    assert rendered.center == 0 and rendered.width == 1000
    assert rendered.pixels.tolist() == [[0, 0, 128, 255, 255]]


def test_linear_exact_follows_the_dicom_reference_formula() -> None:
    values = np.array([-100.0, -50.0, 0.0, 50.0, 100.0])
    stored = (values + 1024).astype(np.int16)
    rendered = render_dicom_frame(
        stored,
        _ct(window_presets=(WindowPreset(center=0, width=100),), voi_lut_function="LINEAR_EXACT"),
    )
    expected = np.clip((values + 50.0) / 100.0 * 255.0, 0.0, 255.0)

    assert np.allclose(rendered.pixels.astype(float), expected, atol=1.0)


def test_monochrome1_inverts_the_presentation_not_the_source() -> None:
    stored = np.array([[0, 1024, 2048]], dtype=np.int16)
    preset = (WindowPreset(center=0, width=2000),)
    normal = render_dicom_frame(stored, _ct(window_presets=preset))
    inverted = render_dicom_frame(stored, _ct(photometric="MONOCHROME1", window_presets=preset))

    assert np.allclose(inverted.pixels.astype(int), 255 - normal.pixels.astype(int), atol=1)
    assert modality_value(0, _ct(photometric="MONOCHROME1")) == -1024.0


def test_inverse_presentation_lut_shape_is_honoured() -> None:
    stored = np.array([[0, 1024, 2048]], dtype=np.int16)
    preset = (WindowPreset(center=0, width=2000),)
    normal = render_dicom_frame(stored, _ct(window_presets=preset))
    inverted = render_dicom_frame(stored, _ct(presentation_lut_shape="INVERSE", window_presets=preset))

    assert np.allclose(inverted.pixels.astype(int), 255 - normal.pixels.astype(int), atol=1)


def test_voi_lut_is_used_while_the_window_controls_are_untouched() -> None:
    display = DicomDisplay(voi_lut=LookupTable(first_input=0, entries=(0.0, 64.0, 128.0, 255.0), bits_per_entry=8))
    rendered = render_dicom_frame(np.array([[0, 1, 2, 3]], dtype=np.uint8), display)

    assert rendered.pixels.tolist() == [[0, 64, 128, 255]]


def test_a_numeric_window_beats_the_header_preset() -> None:
    display = _ct(window_presets=(WindowPreset(center=0, width=1000),))
    rendered = render_dicom_frame(np.array([[1024]], dtype=np.int16), display, numeric_window=(-500.0, 100.0))

    assert (rendered.center, rendered.width) == (-500.0, 100.0)
    assert rendered.pixels.tolist() == [[255]], "0 HU is above a 100 HU window centred on -500 HU"


def test_pixel_padding_is_excluded_from_auto_window_and_painted_black() -> None:
    stored = np.array([[100, 150, 200, 65535]], dtype=np.uint16)
    display = DicomDisplay(pixel_padding_value=65535.0)

    rendered = render_dicom_frame(stored, display, dr_low_pct=0.0, dr_high_pct=100.0)

    assert rendered.center < 500.0, "padding must not stretch the window to 65535"
    assert rendered.width < 500.0
    assert rendered.pixels[0, -1] == 0


def test_mapper_extracts_ct_rescale_windows_and_monochrome1() -> None:
    ds = _ds(
        RescaleSlope="2",
        RescaleIntercept="-1024",
        RescaleType="HU",
        WindowCenter=["40", "400"],
        WindowWidth=["80", "2000"],
        WindowCenterWidthExplanation=["soft", "bone"],
        PixelPaddingValue="-2000",
        PixelPaddingRangeLimit="-1990",
        PhotometricInterpretation="MONOCHROME1",
        VOILUTFunction="LINEAR_EXACT",
    )

    display = map_instance_metadata(ds).display

    assert display is not None
    assert display.rescale_slope == 2.0 and display.rescale_intercept == -1024.0
    assert display.value_unit == "HU"
    assert display.is_monochrome1
    assert [(preset.center, preset.width, preset.label) for preset in display.window_presets] == [
        (40.0, 80.0, "soft"),
        (400.0, 2000.0, "bone"),
    ]
    assert display.pixel_padding_value == -2000.0
    assert display.pixel_padding_range_limit == -1990.0
    assert display.voi_lut_function == "LINEAR_EXACT"


def test_mapper_extracts_a_voi_lut_table() -> None:
    item = Dataset()
    item.LUTDescriptor = [3, 0, 8]
    item.LUTData = [0, 128, 255]
    ds = _ds(VOILUTSequence=[item])

    display = map_instance_metadata(ds).display

    assert display is not None
    assert display.voi_lut is not None
    assert display.voi_lut.entries == (0.0, 128.0, 255.0)
    assert display.voi_lut.first_input == 0.0
    assert display.voi_lut.bits_per_entry == 8
    assert display.voi_lut.last_input == 2.0


def test_plain_ultrasound_keeps_the_existing_window_path() -> None:
    ds = _ds(Modality="US", PhotometricInterpretation="MONOCHROME2", RescaleSlope=1, RescaleIntercept=0)

    assert map_instance_metadata(ds).display is None


def test_ct_without_rescale_never_claims_hu() -> None:
    ds = _ds(WindowCenter=40, WindowWidth=80)

    display = map_instance_metadata(ds).display

    assert display is not None
    assert display.value_unit == ""
    assert modality_value(0, display) == 0.0


def test_mr_never_claims_hu_even_with_rescale() -> None:
    ds = _ds(Modality="MR", RescaleSlope=2, RescaleIntercept=-10, RescaleType="US")

    display = map_instance_metadata(ds).display

    assert display is not None
    assert display.value_unit == ""
    assert modality_value(5, display) == 0.0


def test_lut_descriptor_without_data_is_ignored() -> None:
    item = Dataset()
    item.LUTDescriptor = [3, 0, 8]
    ds = _ds(VOILUTSequence=[item])

    assert map_instance_metadata(ds).display is None


def test_mapper_voi_lut_first_input_comes_from_the_second_descriptor_element() -> None:
    item = Dataset()
    item.LUTDescriptor = [3, 100, 8]
    item.LUTData = [0, 128, 255]
    ds = _ds(VOILUTSequence=[item], PhotometricInterpretation="MONOCHROME2")

    display = map_instance_metadata(ds).display

    assert display is not None and display.voi_lut is not None
    assert display.voi_lut.first_input == 100.0
    rendered = render_dicom_frame(np.array([[100, 101, 102]], dtype=np.uint16), display)
    assert rendered.pixels.tolist() == [[0, 128, 255]]


def test_anatomical_window_presets_cover_all_six_maps_and_aliases() -> None:
    from echo_personal_tool.domain.models.dicom_display import (
        ANATOMICAL_WINDOW_BY_KEY,
        ANATOMICAL_WINDOW_PRESETS,
        anatomical_window_preset,
        match_anatomical_window,
    )

    assert tuple(spec.key for spec in ANATOMICAL_WINDOW_PRESETS) == (
        "brain",
        "lungs",
        "bones",
        "chest",
        "abdomen",
        "angio",
    )
    assert anatomical_window_preset("brain").center == 40.0
    assert anatomical_window_preset("brain").width == 80.0
    assert anatomical_window_preset("lungs").center == -600.0
    assert anatomical_window_preset("lungs").width == 1500.0
    assert anatomical_window_preset("bones").center == 400.0
    assert anatomical_window_preset("bones").width == 1800.0
    assert anatomical_window_preset("chest").center == 40.0
    assert anatomical_window_preset("chest").width == 400.0
    assert anatomical_window_preset("abdomen").center == 50.0
    assert anatomical_window_preset("abdomen").width == 350.0
    assert anatomical_window_preset("angio").center == 300.0
    assert anatomical_window_preset("angio").width == 600.0
    assert match_anatomical_window("Pulmonary") == ANATOMICAL_WINDOW_BY_KEY["lungs"]
    assert match_anatomical_window("CTA") == ANATOMICAL_WINDOW_BY_KEY["angio"]
    assert match_anatomical_window("Mediastinum") == ANATOMICAL_WINDOW_BY_KEY["chest"]


def test_16bit_lut_fast_path_matches_float_reference_across_all_anatomical_windows() -> None:
    from echo_personal_tool.domain.models.dicom_display import ANATOMICAL_WINDOW_PRESETS, DicomDisplay

    display = DicomDisplay(
        photometric="MONOCHROME2",
        rescale_slope=1.0,
        rescale_intercept=-1024.0,
        value_unit="HU",
        pixel_padding_value=-2048,
    )
    stored_i16 = np.array([[-2048, -1024, -600, 0, 40, 300, 400, 1500]], dtype=np.int16)
    stored_i32 = stored_i16.astype(np.int32)
    for spec in ANATOMICAL_WINDOW_PRESETS:
        fast = render_dicom_frame(stored_i16, display, numeric_window=(spec.center, spec.width))
        ref = render_dicom_frame(stored_i32, display, numeric_window=(spec.center, spec.width))
        assert np.array_equal(fast.pixels, ref.pixels), spec.key
        assert int(fast.pixels[0, 0]) == 0
