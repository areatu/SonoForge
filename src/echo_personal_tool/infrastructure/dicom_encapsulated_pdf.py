"""Build a DICOM Encapsulated PDF (SOP 1.2.840.10008.5.1.4.1.1.104.1) and send it (#625).

Infrastructure adapter over pydicom.  The dataset layout comes from the pure
contract in :mod:`domain.services.interop_dicom_pdf`; sending reuses the
existing STOW-RS (:class:`DicomWebClient`) or DIMSE (:class:`DicomUploadClient`)
upload path, so transport policy and credentials stay exactly where they are
today.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import UID, generate_uid

from echo_personal_tool.domain.exceptions import InteropError
from echo_personal_tool.domain.services.interop_dicom_pdf import (
    ENCAPSULATED_PDF_SOP_CLASS_UID,
    PDF_MIME_TYPE,
    EncapsulatedPdfSpec,
)

_UTC = timezone.utc  # noqa: UP017 - aligned with ruff target py310


def _dicom_date(iso_date: str) -> str:
    """``YYYY-MM-DD`` → DICOM DA ``YYYYMMDD``; empty stays empty."""
    text = (iso_date or "").strip().replace("-", "")
    return text if len(text) == 8 and text.isdigit() else ""


def _dicom_time(iso_time: str) -> str:
    text = (iso_time or "").strip().replace(":", "")
    return text if len(text) == 6 and text.isdigit() else ""


def build_encapsulated_pdf_dataset(spec: EncapsulatedPdfSpec, *, now: datetime | None = None) -> FileDataset:
    """Build the encapsulated-PDF FileDataset from *spec* (validates it first)."""
    spec.validate()
    current = now or datetime.now(_UTC)
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = UID(ENCAPSULATED_PDF_SOP_CLASS_UID)
    meta.MediaStorageSOPInstanceUID = UID(spec.sop_instance_uid)
    meta.TransferSyntaxUID = UID("1.2.840.10008.1.2.1")  # Explicit VR Little Endian
    meta.ImplementationClassUID = generate_uid(prefix="1.3.6.1.4.1.61074.")  # SonoForge private root

    ds = FileDataset(b"", {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = UID(ENCAPSULATED_PDF_SOP_CLASS_UID)
    ds.SOPInstanceUID = UID(spec.sop_instance_uid)
    ds.Modality = spec.modality
    ds.PatientName = spec.patient_name
    ds.PatientID = spec.patient_id
    ds.PatientBirthDate = _dicom_date(spec.birth_date)
    ds.PatientSex = (spec.sex or "U").strip().upper()[:1] or "U"
    ds.StudyInstanceUID = UID(spec.study_uid)
    ds.SeriesInstanceUID = UID(spec.series_uid)
    ds.InstanceNumber = 1
    ds.SeriesDescription = spec.series_description
    ds.ContentDate = current.strftime("%Y%m%d")
    ds.ContentTime = current.strftime("%H%M%S")
    ds.StudyDate = _dicom_date(spec.study_date) or ds.ContentDate
    ds.StudyTime = _dicom_time(spec.study_time) or ds.ContentTime
    ds.SpecificCharacterSet = "ISO_IR 192"  # UTF-8: Cyrillic names survive the write
    ds.ConversionType = "WSD"
    ds.BurnedAnnotation = "NO"
    ds.DocumentTitle = spec.document_title
    ds.MIMETypeOfEncapsulatedDocument = PDF_MIME_TYPE
    ds.EncapsulatedDocument = spec.pdf_bytes
    observers = []
    for observer in spec.verifying_observers:
        item = Dataset()
        item.VerifyingObserverName = observer.name
        if observer.organization:
            item.VerifyingOrganization = observer.organization
        if observer.key_id:
            code_item = Dataset()
            code_item.CodeValue = observer.key_id
            code_item.CodingSchemeDesignator = "99SONOFORGE"
            code_item.CodeMeaning = "Local app EP signing key fingerprint (not QES)"
            item.VerifyingObserverIdentificationCodeSequence = [code_item]
        observers.append(item)
    ds.VerifyingObserverSequence = observers
    return ds


def encapsulated_pdf_bytes(spec: EncapsulatedPdfSpec, *, now: datetime | None = None) -> bytes:
    """Serialize the dataset to DICOM bytes."""
    dataset = build_encapsulated_pdf_dataset(spec, now=now)
    import io

    buffer = io.BytesIO()
    dataset.save_as(buffer, enforce_file_format=True) if hasattr(dataset, "save_as") else dataset.save_as(buffer)
    return buffer.getvalue()


def new_sop_uid() -> str:
    return generate_uid(prefix="1.3.6.1.4.1.61074.")


def send_encapsulated_pdf(
    spec: EncapsulatedPdfSpec,
    *,
    upload_client: Any = None,
    use_stow: bool = False,
    stow_client: Any = None,
    now: datetime | None = None,
) -> bool:
    """Send the encapsulated PDF via STOW-RS or DIMSE C-STORE.

    *upload_client* is a :class:`DicomUploadClient` (C-STORE);
    *stow_client* a :class:`DicomWebClient` when ``use_stow`` is set.
    Returns True when the receiver accepted the object.
    """
    payload = encapsulated_pdf_bytes(spec, now=now)
    if len(payload) > 512 * 1024 * 1024:
        raise InteropError("payload_too_large")
    if use_stow:
        if stow_client is None:
            raise InteropError("invalid_client")
        result = stow_client.stow_instances([payload])
        return bool(getattr(result, "success", 0)) and int(getattr(result, "success", 0)) >= 1
    if upload_client is None:
        raise InteropError("invalid_client")
    return bool(upload_client.upload_instance(payload))


def new_series_uid() -> str:
    return generate_uid(prefix="1.3.6.1.4.1.61074.")


__all__ = [
    "ENCAPSULATED_PDF_SOP_CLASS_UID",
    "build_encapsulated_pdf_dataset",
    "encapsulated_pdf_bytes",
    "new_series_uid",
    "new_sop_uid",
    "send_encapsulated_pdf",
    "uuid",  # re-exported for tests that need a raw uuid
]
