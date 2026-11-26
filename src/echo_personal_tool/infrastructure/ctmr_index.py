"""Header-only classic CT/MR index; no pixel decode, Qt, or volume allocation.

Deliberately separate from the US browser's filename ordering. This API does
not activate a viewer. Enhanced and multi-frame objects are diagnosed, never
silently treated as one classic slice. Only Part-10 image files are accepted.
"""

from __future__ import annotations

import struct
from collections import OrderedDict
from collections.abc import Callable, Iterable
from math import isfinite
from pathlib import Path
from struct import error as StructError
from threading import Lock
from typing import BinaryIO, cast

import pydicom
from pydicom.dataset import Dataset
from pydicom.errors import BytesLengthException, InvalidDicomError
from pydicom.filereader import read_file_meta_info
from pydicom.uid import (
    UID,
    CTImageStorage,
    DeflatedExplicitVRLittleEndian,
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    MRImageStorage,
)

from echo_personal_tool.domain.models.ctmr_stack import (
    CtMrIndex,
    Orientation,
    SliceGeometry,
    StackFrameRef,
    StackIndexDiagnostic,
    Vector3,
)
from echo_personal_tool.domain.services.ctmr_stacks import MAX_INDEX_FRAMES, build_ctmr_stacks
from echo_personal_tool.infrastructure.dicom_frame_geometry import check_frame_geometry
from echo_personal_tool.infrastructure.dicom_metadata_mapper import map_dicom_display
from echo_personal_tool.infrastructure.file_identity import FileIdentity

_DIMENSIONS = (
    "TemporalPositionIdentifier",
    "AcquisitionNumber",
    "EchoNumbers",
    "EchoTime",
    "TriggerTime",
    "DiffusionBValue",
    "DiffusionGradientOrientation",
    "ComplexImageComponent",
    "ScanningSequence",
    "SequenceVariant",
    "InversionTime",
    "RepetitionTime",
    "FlipAngle",
)
_TAGS = (
    "SOPClassUID",
    "SOPInstanceUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "FrameOfReferenceUID",
    "Modality",
    "NumberOfFrames",
    "PerFrameFunctionalGroupsSequence",
    "SharedFunctionalGroupsSequence",
    "Rows",
    "Columns",
    "SamplesPerPixel",
    "BitsAllocated",
    "BitsStored",
    "HighBit",
    "PixelRepresentation",
    "PhotometricInterpretation",
    "ImageOrientationPatient",
    "ImagePositionPatient",
    "PixelSpacing",
    "ImageType",
    "RescaleSlope",
    "RescaleIntercept",
    "RescaleType",
    "WindowCenter",
    "WindowWidth",
    "WindowCenterWidthExplanation",
    "VOILUTSequence",
    "ModalityLUTSequence",
    "VOILUTFunction",
    "PresentationLUTShape",
    "PixelPaddingValue",
    "PixelPaddingRangeLimit",
    *_DIMENSIONS,
)


class CtMrHeaderError(ValueError):
    """Static diagnostic code only; never include arbitrary header strings."""


def _vector(ds: Dataset, key: str, length: int) -> tuple[float, ...]:
    raw = ds.get(key)
    if raw is None or len(raw) != length:
        raise CtMrHeaderError("invalid_spatial_geometry")
    result = tuple(float(v) for v in raw)
    if not all(isfinite(v) for v in result):
        raise CtMrHeaderError("invalid_spatial_geometry")
    return result


def _uid(ds: Dataset, key: str, *, optional: bool = False) -> str:
    value = str(ds.get(key, ""))
    if not value and optional:
        return ""
    if not value or not UID(value).is_valid:
        raise CtMrHeaderError("invalid_identity")
    return value


def _stamp(identity: FileIdentity) -> tuple[int, ...]:
    return identity.size, identity.mtime_ns, identity.ctime_ns, identity.device, identity.inode


def _read_classic_header(path: Path) -> Dataset:
    # Refuse Enhanced before requesting its potentially enormous functional
    # group sequences. The second pass remains header-only for classic files.
    meta = read_file_meta_info(path)
    syntax = UID(str(meta.get("TransferSyntaxUID", "")))
    if syntax == DeflatedExplicitVRLittleEndian or not syntax.is_transfer_syntax:
        # pydicom inflates the ENTIRE dataset for this syntax, including pixels,
        # even with stop_before_pixels. Do not violate the header-only contract.
        raise CtMrHeaderError("unsupported_header_transfer_syntax")
    probe = pydicom.dcmread(path, stop_before_pixels=True, specific_tags=["SOPClassUID", "NumberOfFrames"])
    if str(probe.get("SOPClassUID", "")) not in (str(CTImageStorage), str(MRImageStorage)):
        raise CtMrHeaderError("unsupported_sop_class_enhanced_requires_frame_index")
    if int(probe.get("NumberOfFrames", 1)) != 1:
        raise CtMrHeaderError("multiframe_not_supported")
    return pydicom.dcmread(path, stop_before_pixels=True, specific_tags=list(_TAGS))


def _frame(ds: Dataset, path: Path, identity: FileIdentity) -> StackFrameRef:
    sop_class = _uid(ds, "SOPClassUID")
    modality = str(ds.get("Modality", ""))
    for meta_key, key in (("MediaStorageSOPClassUID", "SOPClassUID"), ("MediaStorageSOPInstanceUID", "SOPInstanceUID")):
        if str(ds.file_meta.get(meta_key, "")) != str(ds.get(key, "")):
            raise CtMrHeaderError("file_meta_identity_mismatch")
    if sop_class not in (str(CTImageStorage), str(MRImageStorage)):
        raise CtMrHeaderError("unsupported_sop_class_enhanced_requires_frame_index")
    if modality != ("CT" if sop_class == str(CTImageStorage) else "MR"):
        raise CtMrHeaderError("modality_sop_mismatch")
    if int(ds.get("NumberOfFrames", 1)) != 1 or any(
        key in ds for key in ("PerFrameFunctionalGroupsSequence", "SharedFunctionalGroupsSequence")
    ):
        raise CtMrHeaderError("multiframe_not_supported")
    geometry = check_frame_geometry(ds)
    if geometry is None or geometry.samples_per_pixel != 1 or geometry.bits_allocated not in (8, 16, 32):
        raise CtMrHeaderError("unsupported_pixel_geometry")
    bits = int(ds.get("BitsStored", 0))
    representation = int(ds.get("PixelRepresentation", -1))
    photometric = str(ds.get("PhotometricInterpretation", ""))
    if not 1 <= bits <= geometry.bits_allocated or int(ds.get("HighBit", -1)) != bits - 1:
        raise CtMrHeaderError("invalid_pixel_encoding")
    if representation not in (0, 1) or photometric not in ("MONOCHROME1", "MONOCHROME2"):
        raise CtMrHeaderError("unsupported_pixel_encoding")
    rescale = [ds.get(key) for key in ("RescaleSlope", "RescaleIntercept")]
    if any(v is not None for v in rescale):
        if any(v is None or not isfinite(float(v)) for v in rescale) or float(rescale[0]) == 0:
            raise CtMrHeaderError("invalid_intensity_transform")
    keys = ("ImagePositionPatient", "ImageOrientationPatient", "PixelSpacing")
    # Validate present geometry independently even when another tag is absent.
    position = _vector(ds, keys[0], 3) if keys[0] in ds else (0.0, 0.0, 0.0)
    orientation = _vector(ds, keys[1], 6) if keys[1] in ds else (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    spacing = _vector(ds, keys[2], 2) if keys[2] in ds else (1.0, 1.0)
    checked = SliceGeometry(cast(Vector3, position), cast(Orientation, orientation), (spacing[0], spacing[1]))
    spatial = checked if all(key in ds for key in keys) else None
    raw_type = ds.get("ImageType", ())
    image_type = (raw_type.upper(),) if isinstance(raw_type, str) else tuple(str(v).upper() for v in raw_type)
    return StackFrameRef(
        path,
        _uid(ds, "StudyInstanceUID"),
        _uid(ds, "SeriesInstanceUID"),
        _uid(ds, "SOPInstanceUID"),
        _uid(ds, "FrameOfReferenceUID", optional=True),
        sop_class,
        modality,
        geometry.rows,
        geometry.columns,
        geometry.bits_allocated,
        bits,
        representation,
        photometric,
        spatial,
        tuple((key, str(ds.get(key, ""))) for key in _DIMENSIONS),
        image_type,
        map_dicom_display(ds, modality),
        file_stamp=_stamp(identity),
    )


_VERIFIED_REFS_LOCK = Lock()
_VERIFIED_REFS_MAX = 8192
_VERIFIED_REFS: OrderedDict[tuple[Path, int, tuple[int, ...]], tuple[StackFrameRef, tuple[int, str] | None]] = (
    OrderedDict()
)
_DEFAULT_DCMREAD = pydicom.dcmread
_DEFAULT_READ_META = read_file_meta_info


def _probe_direct_pixel_spec(
    fh: BinaryIO,
    ds: Dataset,
    frame: StackFrameRef,
    file_size: int,
) -> tuple[int, str] | None:
    """Return (byte_offset, numpy_dtype_str) for uncompressed LE classic frames."""
    syntax = UID(str(ds.file_meta.get("TransferSyntaxUID", "")))
    if syntax not in (ExplicitVRLittleEndian, ImplicitVRLittleEndian):
        return None
    if frame.bits_allocated not in (8, 16) or frame.bits_stored != frame.bits_allocated:
        return None
    itemsize = frame.bits_allocated // 8
    dtype_str = ("<i" if frame.pixel_representation == 1 else "<u") + str(itemsize)
    pos = fh.tell()
    tag_hdr = fh.read(12)
    if len(tag_hdr) < 8:
        return None
    group, elem = struct.unpack_from("<HH", tag_hdr, 0)
    if (group, elem) != (0x7FE0, 0x0010):
        return None
    if syntax == ImplicitVRLittleEndian:
        vl = int(struct.unpack_from("<I", tag_hdr, 4)[0])
        data_offset = pos + 8
    else:
        vr = tag_hdr[4:6]
        if vr in (b"OB", b"OW"):
            if len(tag_hdr) < 12:
                return None
            vl = int(struct.unpack_from("<I", tag_hdr, 8)[0])
            data_offset = pos + 12
        else:
            vl = int(struct.unpack_from("<H", tag_hdr, 6)[0])
            data_offset = pos + 8
    if vl == 0xFFFFFFFF:
        return None
    frame_bytes = frame.rows * frame.columns * itemsize
    end_byte = data_offset + (frame.local_frame + 1) * frame_bytes
    if vl < (frame.local_frame + 1) * frame_bytes or file_size < end_byte:
        return None
    return (data_offset + frame.local_frame * frame_bytes, dtype_str)


def _read_classic_header_with_stream(path: Path) -> tuple[Dataset, BinaryIO | None]:
    if pydicom.dcmread is not _DEFAULT_DCMREAD or read_file_meta_info is not _DEFAULT_READ_META:
        return _read_classic_header(path), None
    meta = read_file_meta_info(path)
    syntax = UID(str(meta.get("TransferSyntaxUID", "")))
    if syntax == DeflatedExplicitVRLittleEndian or not syntax.is_transfer_syntax:
        raise CtMrHeaderError("unsupported_header_transfer_syntax")
    fh = path.open("rb")
    keep_open = False
    try:
        probe = pydicom.dcmread(fh, stop_before_pixels=True, specific_tags=["SOPClassUID", "NumberOfFrames"])
        if str(probe.get("SOPClassUID", "")) not in (str(CTImageStorage), str(MRImageStorage)):
            raise CtMrHeaderError("unsupported_sop_class_enhanced_requires_frame_index")
        if int(probe.get("NumberOfFrames", 1)) != 1:
            raise CtMrHeaderError("multiframe_not_supported")
        fh.seek(0)
        ds = pydicom.dcmread(fh, stop_before_pixels=True, specific_tags=list(_TAGS))
        keep_open = True
        return ds, fh
    finally:
        if not keep_open:
            fh.close()


def remember_verified_ref(ref: StackFrameRef, direct_spec: tuple[int, str] | None = None) -> None:
    """Cache a header-validated StackFrameRef keyed by path, frame, and file stamp."""
    if not ref.file_stamp:
        return
    key = (ref.path, ref.local_frame, ref.file_stamp)
    with _VERIFIED_REFS_LOCK:
        existing = _VERIFIED_REFS.get(key)
        effective_spec = direct_spec if direct_spec is not None else (existing[1] if existing else None)
        _VERIFIED_REFS[key] = (ref, effective_spec)
        _VERIFIED_REFS.move_to_end(key)
        while len(_VERIFIED_REFS) > _VERIFIED_REFS_MAX:
            _VERIFIED_REFS.popitem(last=False)


def lookup_verified_entry(ref: StackFrameRef) -> tuple[StackFrameRef, tuple[int, str] | None] | None:
    """Return cached (StackFrameRef, direct_pixel_spec) if stamp was verified."""
    if not ref.file_stamp:
        return None
    key = (ref.path, ref.local_frame, ref.file_stamp)
    with _VERIFIED_REFS_LOCK:
        cached = _VERIFIED_REFS.get(key)
        if cached is not None:
            _VERIFIED_REFS.move_to_end(key)
        return cached


def lookup_verified_ref(ref: StackFrameRef) -> StackFrameRef | None:
    """Return the cached StackFrameRef if path, frame, and stamp were verified."""
    entry = lookup_verified_entry(ref)
    return entry[0] if entry is not None else None


def _index_single_path(path: Path) -> StackFrameRef | StackIndexDiagnostic:
    fh: BinaryIO | None = None
    try:
        before = FileIdentity.capture(path)
        ds, fh = _read_classic_header_with_stream(path)
        frame = _frame(ds, path, before)
        direct_spec = _probe_direct_pixel_spec(fh, ds, frame, before.size) if fh is not None else None
        if fh is not None:
            fh.close()
            fh = None
        if FileIdentity.capture(path) != before:
            raise CtMrHeaderError("source_changed_during_index")
        remember_verified_ref(frame, direct_spec)
        return frame
    except CtMrHeaderError as exc:
        return StackIndexDiagnostic(path, str(exc))
    except (
        OSError,
        InvalidDicomError,
        BytesLengthException,
        EOFError,
        StructError,
        ValueError,
        TypeError,
        OverflowError,
    ):
        return StackIndexDiagnostic(path, "invalid_or_unreadable_header")
    finally:
        if fh is not None:
            fh.close()


def index_ctmr_files(
    paths: Iterable[Path],
    *,
    cancelled: Callable[[], bool] = lambda: False,
    max_files: int = MAX_INDEX_FRAMES,
) -> CtMrIndex:
    """Index at most max_files input paths, returning explicit partial status.

    No implicit recursive filesystem traversal, filename/InstanceNumber sort,
    pixel arrays or hidden reclassification of unsupported enhanced objects.
    Callers own directory enumeration and must present diagnostics/complete.
    """
    if not 1 <= max_files <= MAX_INDEX_FRAMES:
        raise ValueError("invalid_index_limit")
    frames: list[StackFrameRef] = []
    diagnostics: list[StackIndexDiagnostic] = []
    seen: set[Path] = set()
    complete = True
    for index, candidate in enumerate(paths):
        if cancelled():
            complete = False
            diagnostics.append(StackIndexDiagnostic(None, "cancelled"))
            break
        if index >= max_files:
            complete = False
            diagnostics.append(StackIndexDiagnostic(None, "file_limit"))
            break
        path = Path(candidate)
        try:
            if path.is_symlink():
                diagnostics.append(StackIndexDiagnostic(path, "symlink_not_supported"))
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
        except OSError:
            diagnostics.append(StackIndexDiagnostic(path, "invalid_or_unreadable_header"))
            continue
        outcome = _index_single_path(resolved)
        if isinstance(outcome, StackFrameRef):
            frames.append(outcome)
        else:
            diagnostics.append(outcome)
    if cancelled():
        complete = False
        if not any(d.code == "cancelled" for d in diagnostics):
            diagnostics.append(StackIndexDiagnostic(None, "cancelled"))
    try:
        result = build_ctmr_stacks(tuple(frames))
    except ValueError:
        return CtMrIndex((), (*diagnostics, StackIndexDiagnostic(None, "stack_partition_limit")), False)
    return CtMrIndex(result.stacks, (*diagnostics, *result.diagnostics), complete)


def index_ctmr_directory(
    directory: Path,
    *,
    cancelled: Callable[[], bool] = lambda: False,
    max_files: int = MAX_INDEX_FRAMES,
) -> CtMrIndex:
    """Non-recursive directory selection with the same bounded input contract.

    All entries count toward the limit. Non-image files/subdirectories receive
    diagnostics rather than being guessed from their extensions or ignored.
    Directory-enumeration failure invalidates the result, never hides omissions.
    """
    directory = Path(directory)
    if directory.is_symlink():
        return CtMrIndex((), (StackIndexDiagnostic(directory, "symlink_not_supported"),), False)
    try:
        return index_ctmr_files(directory.iterdir(), cancelled=cancelled, max_files=max_files)
    except OSError:
        return CtMrIndex((), (StackIndexDiagnostic(directory, "directory_unreadable"),), False)
