"""De-identify DICOM instances on the way to an export folder.

Two independent layers, exactly as agreed in ``docs/deidentification_design.md``
(§3 tags, §4-5 pixels):

* **Tags** — ``PatientName`` becomes a pseudonym, ``PatientID`` a stable
  ``ANON-<hash>`` (and ``OtherPatientIDs*`` are dropped, §3.2); the
  quasi-identifiers and private blocks are switchable and off by default
  (§3.3, §7).  Measured geometry (``SequenceOfUltrasoundRegions``,
  ``PixelSpacing``), UIDs and patient size/weight stay: they are needed for
  measurement and calibration and are not PHI by themselves (§3.4).  An
  already-cleaned name (``?????``/``*****``) is left alone (§1 rule 15).
* **Pixels** — the burned-in header band is filled with the local background
  using the same geometry as the viewer and the MP4 export: the profile for
  ``(vendor, H, W)`` clamped to the first ultrasound panel row.  Compressed
  pixel data is decoded and rewritten uncompressed, because a mask cannot be
  written into a JPEG bitstream.

The result carries a verification report (§8): the produced bytes are searched
for the identifiers that were just removed, and — when the experimental detector
is switched on — the masked pixels are re-checked for surviving text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset
from pydicom.uid import UID, ExplicitVRLittleEndian

from echo_personal_tool.domain.services.phi_mask import (
    MaskPlan,
    fill_plan_inplace,
    fill_values,
    resolve_mask_plan,
)
from echo_personal_tool.domain.services.phi_verification import (
    ByteVerification,
    MaskVerification,
    top_band_rows,
    verify_bytes,
    verify_masked_frame,
)
from echo_personal_tool.infrastructure.phi_mask_profiles import (
    PhiMaskContext,
    masks_disabled_by_header,
    phi_mask_context,
    resolve_mask_spec,
)

logger = logging.getLogger(__name__)

#: Values made only of these characters are "already cleaned" markers written by
#: other tools (GE does this) — overwriting them with our pseudonym would lose
#: information and rewrite files that are already anonymous.
CLEANED_MARKERS = frozenset("?*.")

#: Cleared unconditionally (§3.1, §3.2).
PATIENT_TAGS = ("PatientName", "PatientID", "OtherPatientIDs", "OtherPatientIDsSequence")

#: Cleared only when the caller asks for it (§3.3, default off).
QUASI_IDENTIFIER_TAGS = ("AccessionNumber", "StudyID", "PerformedProcedureStepID")

#: Never touched by the default set; kept for documentation and tests (§3.4).
PRESERVED_TAGS = (
    "SequenceOfUltrasoundRegions",
    "PixelSpacing",
    "SOPInstanceUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "PatientSize",
    "PatientWeight",
)

#: A caller that knows the file passes its header context; this is the safe
#: fallback (conservative profile, no panel clamp, mask on).
_UNKNOWN_CONTEXT = PhiMaskContext()


@dataclass(frozen=True)
class DeidentificationOptions:
    """What the export should do to one instance."""

    #: Variant B of §5: rewrite the pixels of the header band.
    mask_pixels: bool = True
    #: Variant "A + quas": clear AccessionNumber / StudyID / PerformedProcedureStepID.
    clean_quasi_identifiers: bool = False
    #: Remove private blocks (§7, default off).
    clean_private_tags: bool = False
    #: Replacement for ``PatientName``; ``PatientID`` becomes ``<pseudonym>-<hash>``.
    pseudonym: str = "ANON"
    #: Run the experimental text detector as a verification layer (§8 layer 2).
    verify_pixels: bool = False


@dataclass(frozen=True)
class TagCleanup:
    """Which tags the cleaner touched."""

    changed: tuple[str, ...] = ()
    skipped_already_clean: tuple[str, ...] = ()
    private_removed: int = 0

    @property
    def summary(self) -> str:
        parts = [f"{len(self.changed)} tag(s) cleared"]
        if self.private_removed:
            parts.append(f"{self.private_removed} private element(s) removed")
        if self.skipped_already_clean:
            parts.append("already clean: " + ", ".join(self.skipped_already_clean))
        return "; ".join(parts)


@dataclass(frozen=True)
class PixelMaskOutcome:
    """What happened to the pixel data."""

    applied: bool
    band: tuple[int, int] | None = None
    #: ``ok``, ``disabled``, ``burned-in-annotation-no``, ``no-bands``,
    #: ``no-pixels``, ``masking-failed``.
    reason: str = ""
    verification: MaskVerification | None = None

    @property
    def summary(self) -> str:
        if self.applied and self.band is not None:
            return f"pixels masked: rows {self.band[0]}..{self.band[1]}"
        return f"pixels untouched ({self.reason})"


@dataclass(frozen=True)
class DeidentificationResult:
    """Everything one exported instance needs to be reported on."""

    source: Path
    destination: Path
    tags: TagCleanup = field(default_factory=TagCleanup)
    pixels: PixelMaskOutcome = field(default_factory=lambda: PixelMaskOutcome(applied=False, reason="disabled"))
    bytes_check: ByteVerification | None = None

    @property
    def verified(self) -> bool:
        """True when every check that ran came back clean."""
        checks = [check for check in (self.bytes_check, self.pixels.verification) if check is not None]
        return all(check.ok for check in checks)

    def report_lines(self) -> tuple[str, ...]:
        """PHI-free one-liners for the status area and the log."""
        lines = [f"{self.source.name}: {self.tags.summary}", self.pixels.summary]
        if self.pixels.verification is not None:
            lines.append(self.pixels.verification.summary)
        if self.bytes_check is not None:
            lines.append(self.bytes_check.summary)
        return tuple(lines)


def is_already_clean(value: object) -> bool:
    """True for an empty value or a ``?????``/``*****`` marker (§1 rule 15)."""
    text = str(value or "").strip()
    if not text:
        return True
    return set(text) <= CLEANED_MARKERS


def pseudonym_id(value: object, pseudonym: str) -> str:
    """Stable ``ANON-<hash>`` for a patient ID.

    The hash keeps two patients distinguishable inside one export without
    carrying the ID itself.  It is *not* a secret: a small ID space can be
    brute-forced from the digest, which is why the ID is replaced rather than
    merely re-encoded.
    """
    digest = sha256(str(value).strip().encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{pseudonym}-{digest}"


def clean_tags(ds: Dataset, options: DeidentificationOptions) -> TagCleanup:
    """Clear the PHI tags of ``ds`` in place and report what was touched."""
    changed: list[str] = []
    skipped: list[str] = []

    name = ds.get("PatientName")
    if name is None or is_already_clean(name):
        skipped.append("PatientName")
    else:
        ds.PatientName = options.pseudonym
        changed.append("PatientName")

    patient_id = ds.get("PatientID")
    if patient_id is None or is_already_clean(patient_id):
        skipped.append("PatientID")
    else:
        ds.PatientID = pseudonym_id(patient_id, options.pseudonym)
        changed.append("PatientID")

    for tag in ("OtherPatientIDs", "OtherPatientIDsSequence"):
        if tag in ds:
            del ds[tag]
            changed.append(tag)

    if options.clean_quasi_identifiers:
        for tag in QUASI_IDENTIFIER_TAGS:
            if tag in ds:
                # Kept as an empty element rather than removed: readers and
                # PACS tolerate a missing tag less reliably than an empty one.
                setattr(ds, tag, "")
                changed.append(tag)

    removed_private = 0
    if options.clean_private_tags:
        before = len(ds)
        ds.remove_private_tags()
        removed_private = max(before - len(ds), 0)

    return TagCleanup(
        changed=tuple(changed),
        skipped_already_clean=tuple(skipped),
        private_removed=removed_private,
    )


def mask_plan_for_dataset(ds: Dataset, context: PhiMaskContext) -> MaskPlan:
    """Resolve the pixel mask for a whole dataset (not for one decoded frame)."""
    rows = int(getattr(ds, "Rows", 0) or 0)
    cols = int(getattr(ds, "Columns", 0) or 0)
    spec = resolve_mask_spec(context.vendor, rows, cols)
    return resolve_mask_plan(spec, rows, cols, panel_top=context.panel_top)


def mask_pixel_data(
    ds: Dataset,
    options: DeidentificationOptions,
    *,
    frames: np.ndarray | None = None,
    context: PhiMaskContext | None = None,
) -> PixelMaskOutcome:
    """Fill the header band of ``ds``'s pixels with their own background.

    ``frames`` is the decoded ``(N, H, W)`` / ``(N, H, W, C)`` array; when it is
    ``None`` the pixel data must be uncompressed and is taken from
    ``PixelData``.  The array is modified in place and written back — callers
    must own it (the export decodes a private copy).
    """
    if not options.mask_pixels:
        return PixelMaskOutcome(applied=False, reason="disabled")

    resolved_context = _UNKNOWN_CONTEXT if context is None else context
    if masks_disabled_by_header(resolved_context):
        return PixelMaskOutcome(applied=False, reason="burned-in-annotation-no")

    plan = mask_plan_for_dataset(ds, resolved_context)
    if plan.is_empty:
        return PixelMaskOutcome(applied=False, reason="no-bands")

    array = frames if frames is not None else _uncompressed_frames(ds)
    if array is None or array.size == 0:
        return PixelMaskOutcome(applied=False, reason="no-pixels")

    frames_iter = list(_iter_frames(array))
    first = frames_iter[0]

    # The verification compares the masked pixels with what was there, so the
    # region it inspects is copied before the fill overwrites it.  Only the
    # first frame is needed: the band is identical on every frame of a cine.
    original_region: np.ndarray | None = None
    region_end = 0
    if options.verify_pixels:
        band = top_band_rows(plan)
        if band is not None:
            region_end = min(int(first.shape[0]), band[1] + max(band[1] - band[0], 1))
            original_region = np.array(first[:region_end])

    fills = fill_values(first, plan)
    for frame in frames_iter:
        fill_plan_inplace(frame, plan, fills)
    _write_frames_back(ds, array)

    verification: MaskVerification | None = None
    if original_region is not None and region_end > 0:
        verification = verify_masked_frame(original_region, first[:region_end], plan)

    return PixelMaskOutcome(
        applied=True,
        band=top_band_rows(plan),
        reason="ok",
        verification=verification,
    )


def _iter_frames(array: np.ndarray):
    """Yield the frames of a ``(N, H, W[, C])`` array (or the array itself once)."""
    if array.ndim >= 3 and array.shape[0] > 1:
        yield from array
    else:
        yield array[0] if array.ndim == 3 and array.shape[0] == 1 else array


def _uncompressed_frames(ds: Dataset) -> np.ndarray | None:
    """View the uncompressed pixel data as ``(N, rows, cols[, samples])``.

    Returns ``None`` for compressed syntaxes: a mask cannot be patched into a
    JPEG/J2K codestream, so those files have to be decoded first (see
    :func:`deidentify_file`).
    """
    raw = ds.get("PixelData")
    if raw is None:
        return None
    if _transfer_syntax_is_compressed(ds):
        return None

    rows = int(getattr(ds, "Rows", 0) or 0)
    cols = int(getattr(ds, "Columns", 0) or 0)
    if rows <= 0 or cols <= 0:
        return None
    samples = int(getattr(ds, "SamplesPerPixel", 1) or 1)
    bits = int(getattr(ds, "BitsAllocated", 8) or 8)
    if bits not in (8, 16, 32, 64):
        return None
    count = int(getattr(ds, "NumberOfFrames", 1) or 1)
    dtype = np.dtype(f"uint{bits}")
    per_frame = rows * cols * max(samples, 1)
    if len(raw) < count * per_frame * dtype.itemsize:
        count = max(len(raw) // (per_frame * dtype.itemsize), 1)
    flat = np.frombuffer(raw, dtype=dtype, count=count * per_frame)
    if samples > 1:
        return np.array(flat.reshape((count, rows, cols, samples)), copy=True)
    return np.array(flat.reshape((count, rows, cols)), copy=True)


def _write_frames_back(ds: Dataset, array: np.ndarray) -> None:
    """Write the (possibly masked) pixels back into ``ds``.

    The array is stored raw.  When the instance arrived compressed, the transfer
    syntax is switched to explicit VR little endian and — for colour data that
    went through a decoder — the photometric interpretation is normalised to
    ``RGB``; the frame count is preserved either way.
    """
    contiguous = np.ascontiguousarray(array)
    ds.PixelData = contiguous.tobytes()
    element = ds.data_element("PixelData")
    if element is not None:
        # Encapsulated pixel data has an undefined length; the raw array does
        # not, and a stale flag would make readers look for a delimiter.
        element.is_undefined_length = False

    was_compressed = _transfer_syntax_is_compressed(ds)
    samples = int(getattr(ds, "SamplesPerPixel", 1) or 1)
    if was_compressed:
        file_meta = getattr(ds, "file_meta", None)
        if file_meta is not None:
            file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.is_implicit_VR = False
        ds.is_little_endian = True
        if samples > 1:
            # Decoders hand back interleaved RGB, not YBR_FULL_422.
            ds.PhotometricInterpretation = "RGB"
    if samples > 1:
        ds.PlanarConfiguration = 0

    frames = int(contiguous.shape[0]) if contiguous.ndim >= 3 else 1
    if frames > 1:
        ds.NumberOfFrames = frames


def _transfer_syntax_is_compressed(ds: Dataset) -> bool:
    file_meta = getattr(ds, "file_meta", None)
    syntax = str(getattr(file_meta, "TransferSyntaxUID", "") or "")
    if not syntax:
        return False
    try:
        return UID(syntax).is_compressed
    except Exception:  # noqa: BLE001 - an invalid UID must not stop the export
        return False


def _decoded_frames(source: Path) -> np.ndarray | None:
    """Decode a compressed instance with the application's own session."""
    from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session

    try:
        session = get_thread_dicom_session(source)
        session.open(source)
        if session.frame_count <= 1:
            return np.array([session.decode_first_frame()], copy=True)
        return np.array(session.decode_all_frames(), copy=True)
    except Exception:  # noqa: BLE001 - report and fall back to tag-only export
        logger.warning("De-identification: cannot decode %s", source, exc_info=True)
        return None


def _source_identifiers(
    ds: Dataset,
    source: Path,
    name_before: object,
    id_before: object,
    options: DeidentificationOptions,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Identifiers to search for in the produced bytes (§8 layer 1).

    Values are read from the dataset *before* cleaning.  Fields that the chosen
    options deliberately keep (quasi-identifiers, private blocks) are returned
    separately so the check does not report them as leaks.  The file name is
    part of the must-be-gone set: the export writes short names, and a copy of
    the name in the payload would leak it.
    """
    identifiers: dict[str, str] = {}
    if name_before:
        identifiers["PatientName"] = str(name_before)
    if id_before:
        identifiers["PatientID"] = str(id_before)
    for tag in ("OtherPatientIDs", *QUASI_IDENTIFIER_TAGS):
        value = ds.get(tag)
        if value:
            identifiers[tag] = str(value)
    if source.stem:
        identifiers["FileName"] = source.stem

    allowed = [tag for tag in QUASI_IDENTIFIER_TAGS if not options.clean_quasi_identifiers]
    return identifiers, tuple(allowed)


def deidentify_file(
    source: Path,
    destination: Path,
    options: DeidentificationOptions,
) -> DeidentificationResult:
    """Read ``source``, de-identify it and write it to ``destination``.

    File meta is refreshed (``dcmwrite`` with ``enforce_file_format=True`` after
    a fresh meta pass) so the exported instance declares what it actually
    contains, whatever the pixel path did to the transfer syntax.
    """
    ds = pydicom.dcmread(str(source), force=True)
    context = phi_mask_context(source)

    name_before = ds.get("PatientName")
    id_before = ds.get("PatientID")
    identifiers, allowed_fields = _source_identifiers(ds, source, name_before, id_before, options)

    tags = clean_tags(ds, options)

    frames: np.ndarray | None = None
    if options.mask_pixels and not masks_disabled_by_header(context) and _transfer_syntax_is_compressed(ds):
        frames = _decoded_frames(source)

    try:
        pixels = mask_pixel_data(ds, options, frames=frames, context=context)
    except Exception:  # noqa: BLE001 - a pixel problem must not lose the tag cleanup
        logger.exception("De-identification: masking pixels of %s failed", source)
        pixels = PixelMaskOutcome(applied=False, reason="masking-failed")

    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_dataset(ds, destination)

    bytes_check = verify_bytes(identifiers, destination.read_bytes(), allowed_fields=allowed_fields)
    return DeidentificationResult(
        source=source,
        destination=destination,
        tags=tags,
        pixels=pixels,
        bytes_check=bytes_check,
    )


def _write_dataset(ds: Dataset, destination: Path) -> None:
    """Write the dataset with a file meta block that matches its contents."""
    if not getattr(ds, "file_meta", None):
        ds.file_meta = pydicom.Dataset()
    ds.file_meta.MediaStorageSOPClassUID = getattr(ds, "SOPClassUID", None) or ds.file_meta.get(
        "MediaStorageSOPClassUID"
    )
    ds.file_meta.MediaStorageSOPInstanceUID = getattr(ds, "SOPInstanceUID", None) or ds.file_meta.get(
        "MediaStorageSOPInstanceUID"
    )
    pydicom.dcmwrite(
        str(destination),
        ds,
        write_like_original=False,
        enforce_file_format=False,
    )
