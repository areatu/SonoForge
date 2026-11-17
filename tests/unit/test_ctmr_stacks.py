"""Synthetic classic CT/MR header index; no clinical/vendor validation."""

from dataclasses import replace
from pathlib import Path

import pydicom
import pytest
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, EnhancedMRImageStorage, ExplicitVRLittleEndian, JPEG2000Lossless, MRImageStorage

from echo_personal_tool.domain.models.ctmr_stack import SliceGeometry
from echo_personal_tool.domain.services.ctmr_stacks import build_ctmr_stacks
from echo_personal_tool.infrastructure.ctmr_index import index_ctmr_files


@pytest.fixture
def make_file(tmp_path):
    def make(name, z=0, sop=None, **tags):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = tags.get("SOPClassUID", CTImageStorage)
        meta.MediaStorageSOPInstanceUID = sop or f"1.2.3.{len(list(tmp_path.iterdir())) + 1}"
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(str(tmp_path / name), {}, file_meta=meta, preamble=b"\0" * 128)
        values = dict(
            SOPClassUID=CTImageStorage,
            SOPInstanceUID=meta.MediaStorageSOPInstanceUID,
            StudyInstanceUID="1.2.10",
            SeriesInstanceUID="1.2.10.1",
            FrameOfReferenceUID="1.2.20",
            Modality="CT",
            Rows=16,
            Columns=24,
            SamplesPerPixel=1,
            BitsAllocated=16,
            BitsStored=12,
            HighBit=11,
            PixelRepresentation=1,
            PhotometricInterpretation="MONOCHROME2",
            ImagePositionPatient=[0, 0, z],
            ImageOrientationPatient=[1, 0, 0, 0, 1, 0],
            PixelSpacing=[0.7, 0.4],
            ImageType=["ORIGINAL", "PRIMARY", "AXIAL"],
            RescaleSlope=1,
            RescaleIntercept=-1024,
        )
        values.update(tags)
        for key, value in values.items():
            if value is not None:
                setattr(ds, key, value)
        ds.PixelData = b"\0" * (16 * 24 * 2)
        ds.save_as(tmp_path / name, enforce_file_format=True)
        return tmp_path / name

    return make


def _refs(result):
    return [frame for stack in result.stacks for frame in stack.frames]


def test_shuffled_names_and_instance_numbers_do_not_define_anatomical_order(make_file):
    paths = [
        make_file("z9.dcm", z=3, InstanceNumber=1),
        make_file("a1.dcm", z=-2, InstanceNumber=99),
        make_file("m5.dcm", z=0, InstanceNumber=3),
    ]
    result = index_ctmr_files(paths)
    assert result.complete and not result.diagnostics
    stack = result.stacks[0]
    assert stack.positions_mm == (-2, 0, 3)
    assert [f.path.name for f in stack.frames] == ["a1.dcm", "m5.dcm", "z9.dcm"]
    assert stack.spatial_order_verified
    assert "nonuniform_spacing_possible_gaps" in stack.warnings
    assert {f.local_frame for f in stack.frames} == {0}
    assert all(f.display.rescale_intercept == -1024 for f in stack.frames)
    assert all(f.pixel_representation == 1 and f.bits_stored == 12 for f in stack.frames)


def test_oblique_normal_projection_and_patient_coordinate_mapping(make_file):
    a = 2**-0.5
    iop = [a, 0, a, 0, 1, 0]
    paths = [
        make_file(f"{i}.dcm", ImagePositionPatient=[-a * t, 0, a * t], ImageOrientationPatient=iop)
        for i, t in enumerate((4, -1, 2))
    ]
    stack = index_ctmr_files(paths).stacks[0]
    assert stack.positions_mm == pytest.approx((-1, 2, 4))
    geometry = stack.frames[0].geometry
    assert geometry.patient_point(2, 3) == pytest.approx((a + 3 * 0.4 * a, 1.4, -a + 3 * 0.4 * a))


def test_uniform_spacing_and_monochrome1_transform_preserved(make_file):
    paths = [make_file(f"{i}.dcm", z=i * 2, PhotometricInterpretation="MONOCHROME1", RescaleSlope=2) for i in range(4)]
    stack = index_ctmr_files(paths).stacks[0]
    assert stack.adjacent_spacing_mm == (2, 2, 2)
    assert not stack.warnings
    assert stack.frames[0].display.is_monochrome1
    assert stack.frames[0].display.rescale_slope == 2
    assert stack.frames[0].display.value_unit == "HU"


@pytest.mark.parametrize(
    "tags",
    [
        {"SeriesInstanceUID": "1.2.10.2"},
        {"StudyInstanceUID": "1.2.11"},
        {"FrameOfReferenceUID": "1.2.21"},
        {"ImageOrientationPatient": [0, 1, 0, 0, 0, 1]},
        {"PixelSpacing": [0.8, 0.4]},
        {"Rows": 32},
        {"ImageType": ["ORIGINAL", "PRIMARY", "LOCALIZER"]},
        {"TemporalPositionIdentifier": 2},
        {"EchoNumbers": 2},
        {"EchoTime": 30},
        {"AcquisitionNumber": 2},
        {"TriggerTime": 100},
        {"DiffusionBValue": 1000},
        {"DiffusionGradientOrientation": [1, 0, 0]},
    ],
)
def test_incompatible_series_geometry_localizers_and_dimensions_are_partitioned(make_file, tags):
    result = index_ctmr_files([make_file("a.dcm"), make_file("b.dcm", z=1, **tags)])
    assert len(result.stacks) == 2
    if "StudyInstanceUID" not in tags and "SeriesInstanceUID" not in tags:
        assert all("series_partitioned" in stack.warnings for stack in result.stacks)


@pytest.mark.parametrize(
    "missing", ["ImagePositionPatient", "ImageOrientationPatient", "PixelSpacing", "FrameOfReferenceUID"]
)
def test_missing_spatial_information_is_not_claimed_verified(make_file, missing):
    stack = index_ctmr_files([make_file("a.dcm", **{missing: None})]).stacks[0]
    assert not stack.spatial_order_verified
    assert "spatial_order_unverified" in stack.warnings


def test_duplicate_positions_and_in_plane_shift_are_visible(make_file):
    stack = index_ctmr_files([make_file("a.dcm"), make_file("b.dcm", ImagePositionPatient=[1, 0, 0])]).stacks[0]
    assert not stack.spatial_order_verified
    assert {"duplicate_positions", "in_plane_origin_shift"} <= set(stack.warnings)


def test_duplicate_sop_deduplicates_but_does_not_claim_equal_pixels(make_file):
    a = make_file("a.dcm", sop="1.2.40")
    b = make_file("b.dcm", sop="1.2.40")
    result = index_ctmr_files([b, a, a])
    assert len(_refs(result)) == 1 and _refs(result)[0].path == a
    assert [d.code for d in result.diagnostics] == ["duplicate_sop_pixels_unverified"]


def test_conflicting_sop_is_quarantined_not_chosen_by_filename(make_file):
    result = index_ctmr_files([make_file("a.dcm", sop="1.2.40"), make_file("b.dcm", z=8, sop="1.2.40")])
    assert not result.stacks
    assert [d.code for d in result.diagnostics] == ["conflicting_sop", "conflicting_sop"]


def test_header_only_no_pixel_decode_or_read_pixel_element(make_file, monkeypatch):
    path = make_file("a.dcm")
    original = pydicom.dcmread

    def read(*args, **kwargs):
        assert kwargs["stop_before_pixels"] is True
        assert "PixelData" not in kwargs["specific_tags"]
        ds = original(*args, **kwargs)
        assert "PixelData" not in ds
        return ds

    def forbidden(_self):
        raise AssertionError("pixel decode forbidden during indexing")

    monkeypatch.setattr(pydicom, "dcmread", read)
    monkeypatch.setattr(Dataset, "pixel_array", property(forbidden))
    assert len(_refs(index_ctmr_files([path]))) == 1


@pytest.mark.parametrize(
    "tags",
    [
        {"SOPClassUID": EnhancedMRImageStorage, "Modality": "MR"},
        {"NumberOfFrames": 2},
        {"ImageOrientationPatient": [1, 0, 0, 1, 0, 0]},
        {"ImageOrientationPatient": [2, 0, 0, 0, 1, 0]},
        {"ImagePositionPatient": [float("nan"), 0, 0]},
        {"PixelSpacing": [-1, 1]},
        {"BitsStored": 17},
        {"PixelRepresentation": 4},
        {"SamplesPerPixel": 3},
        {"RescaleSlope": 0},
        {"RescaleSlope": None},
        {"RescaleIntercept": float("inf")},
        {"Modality": "MR"},
        {"SOPInstanceUID": "not-a-uid"},
    ],
)
def test_invalid_or_unsupported_headers_have_diagnostics(make_file, tags):
    result = index_ctmr_files([make_file("bad.dcm", **tags)])
    assert not result.stacks and len(result.diagnostics) == 1


def test_mr_signal_never_labelled_hu(make_file):
    frame = _refs(index_ctmr_files([make_file("mr.dcm", SOPClassUID=MRImageStorage, Modality="MR")]))[0]
    assert frame.modality == "MR" and frame.display.value_unit == ""


def test_compressed_header_does_not_need_decoder(make_file):
    path = make_file("compressed.dcm")
    ds = pydicom.dcmread(path)
    ds.file_meta.TransferSyntaxUID = JPEG2000Lossless
    from pydicom.encaps import encapsulate

    ds.PixelData = encapsulate([b"not-a-real-codestream"])
    ds["PixelData"].is_undefined_length = True
    ds.save_as(path, enforce_file_format=True)
    assert len(_refs(index_ctmr_files([path]))) == 1


def test_limits_cancellation_and_unreadable_paths_are_explicit(make_file, tmp_path):
    paths = [make_file("a.dcm"), make_file("b.dcm")]
    limited = index_ctmr_files(paths, max_files=1)
    assert not limited.complete and len(_refs(limited)) == 1
    assert limited.diagnostics[-1].code == "file_limit"
    stopped = index_ctmr_files(paths, cancelled=lambda: True)
    assert not stopped.complete and not stopped.stacks and stopped.diagnostics[0].code == "cancelled"
    result = index_ctmr_files([tmp_path / "missing"])
    assert not result.stacks and result.diagnostics[0].code == "invalid_or_unreadable_header"
    with pytest.raises(ValueError):
        index_ctmr_files([], max_files=0)


def test_source_change_during_index_refused(make_file, monkeypatch):
    path = make_file("a.dcm")
    original = pydicom.dcmread

    def read(*args, **kwargs):
        ds = original(*args, **kwargs)
        with path.open("ab") as stream:
            stream.write(b"changed")
        return ds

    monkeypatch.setattr(pydicom, "dcmread", read)
    result = index_ctmr_files([path])
    assert not result.stacks and result.diagnostics[0].code == "source_changed_during_index"


def test_permutation_stability_and_exact_sop_frame_reference(make_file):
    paths = [make_file(f"{i}.dcm", z=i) for i in (2, 0, 1)]
    first = index_ctmr_files(paths)
    assert first == index_ctmr_files(reversed(paths))
    frame = first.stacks[0].frames[1]
    assert frame.identity == (frame.sop_uid, 0)
    assert frame.file_stamp and frame.path.is_file()
    assert build_ctmr_stacks(tuple(reversed(_refs(first)))).stacks == first.stacks


@pytest.mark.parametrize("orientation", [(0, 0, 0, 0, 1, 0), (1, 0, 0, 1, 0, 0), (float("inf"), 0, 0, 0, 1, 0)])
def test_domain_geometry_rejects_invalid_direction_cosines(orientation):
    with pytest.raises(ValueError):
        SliceGeometry((0, 0, 0), orientation, (1, 1))


def test_direct_geometry_axis_semantics():
    geometry = SliceGeometry((10, 20, 30), (1, 0, 0, 0, 1, 0), (2, 3))
    assert geometry.patient_point(row=4, column=5) == (25, 28, 30)


def test_directory_index_does_not_depend_on_extensions(make_file, tmp_path):
    from echo_personal_tool.infrastructure.ctmr_index import index_ctmr_directory

    make_file("without_extension", z=1)
    make_file("wrong_extension.txt", z=2)
    (tmp_path / "unrelated.txt").write_text("not a medical image")
    result = index_ctmr_directory(tmp_path)
    assert len(_refs(result)) == 2 and result.complete
    assert len(result.diagnostics) == 1
    assert not index_ctmr_directory(tmp_path / "missing").complete


def test_corrupt_present_geometry_does_not_become_unverified_fallback(make_file):
    result = index_ctmr_files([make_file("a", ImagePositionPatient=None, PixelSpacing=[-1, 1])])
    assert not result.stacks and result.diagnostics


def test_small_direction_roundoff_groups_but_distinct_orientations_do_not(make_file):
    a = make_file("a", z=0)
    b = make_file("b", z=1, ImageOrientationPatient=[1, 0, 0, 0, 1, 0.000001])
    result = index_ctmr_files([a, b])
    assert len(result.stacks) == 1


def test_enhanced_refusal_does_not_request_functional_groups(make_file, monkeypatch):
    path = make_file("enhanced", SOPClassUID=EnhancedMRImageStorage, Modality="MR")
    original = pydicom.dcmread

    def read(*args, **kwargs):
        assert "PerFrameFunctionalGroupsSequence" not in kwargs["specific_tags"]
        return original(*args, **kwargs)

    monkeypatch.setattr(pydicom, "dcmread", read)
    assert not index_ctmr_files([path]).stacks


def test_indexed_signed_ct_values_use_existing_display_chain(make_file):
    import numpy as np

    from echo_personal_tool.imaging.dicom_display import stored_to_modality

    frame = _refs(index_ctmr_files([make_file("a", RescaleSlope=2)]))[0]
    stored = np.array([-100, 0, 100], dtype=np.int16)
    assert stored_to_modality(stored, frame.display) == pytest.approx([-1224, -1024, -824])


def test_direct_domain_refs_require_classic_frame_and_valid_identity(make_file):
    frame = _refs(index_ctmr_files([make_file("a")]))[0]
    with pytest.raises(ValueError):
        replace(frame, local_frame=1)
    with pytest.raises(ValueError):
        replace(frame, sop_uid="")
    with pytest.raises(ValueError):
        frame.geometry.patient_point(float("nan"), 0)


def test_bounded_partition_count(make_file):
    frame = _refs(index_ctmr_files([make_file("a")]))[0]
    frames = tuple(replace(frame, sop_uid=f"1.2.{i}", series_uid=f"1.3.{i}", path=Path(f"{i}")) for i in range(257))
    with pytest.raises(ValueError, match="stack_partition_limit"):
        build_ctmr_stacks(frames)


def test_deflated_whole_dataset_never_inflated_by_header_index(make_file, monkeypatch):
    from pydicom.uid import DeflatedExplicitVRLittleEndian

    path = make_file("deflated")
    ds = pydicom.dcmread(path)
    ds.file_meta.TransferSyntaxUID = DeflatedExplicitVRLittleEndian
    ds.save_as(path, enforce_file_format=True)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("dcmread would inflate the entire pixel payload")

    monkeypatch.setattr(pydicom, "dcmread", forbidden)
    result = index_ctmr_files([path])
    assert not result.stacks
    assert result.diagnostics[0].code == "unsupported_header_transfer_syntax"
