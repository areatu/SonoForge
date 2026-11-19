"""DICOM Structured Report (TID 5200 Adult Echocardiography Procedure Report)
serialization on pydicom (#626).

The content tree comes from the pure :mod:`domain.services.interop_sr` model
(LOINC/UCUM from the Stage-3 terminology dictionary); this module maps it onto
a pydicom SR dataset (SOP Class ``1.2.840.10008.5.1.4.1.1.88.65``) and can send
it to the PACS via the existing STOW-RS / C-STORE upload targets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import UID, generate_uid

from echo_personal_tool.domain.exceptions import InteropError
from echo_personal_tool.domain.services.interop_sr import SrNode

SR_SOP_CLASS_UID = UID("1.2.840.10008.5.1.4.1.1.88.65")  # Comprehensive SR Storage
# TID 5200 "Adult Echocardiography Procedure Report" mapping resource.
TID_5200 = UID("1.2.840.10008.6.1.5200")


def _code_ds(value: str, scheme: str, meaning: str) -> Dataset:
    ds = Dataset()
    ds.CodeValue = value
    ds.CodingSchemeDesignator = scheme
    ds.CodeMeaning = meaning
    return ds


def _to_content_item(node: SrNode, *, now: datetime) -> Dataset:
    item = Dataset()
    item.ContentTemplateSequence = [Dataset()]
    item.ContentTemplateSequence[0].MappingResource = "DCM"
    item.ContentTemplateSequence[0].TemplateIdentifier = TID_5200
    item.ValueType = node.value_type
    item.ConceptNameCodeSequence = [_code_ds(node.concept.value, node.concept.scheme, node.concept.meaning)]
    if node.value_type == "NUM" and node.num is not None:
        item.MeasuredValueSequence = [Dataset()]
        mv = item.MeasuredValueSequence[0]
        try:
            mv.NumericValue = float(node.num.value)
        except ValueError:
            mv.NumericValue = node.num.value
        mv.MeasurementUnitsCodeSequence = [_code_ds(node.num.unit_code, "UCUM", node.num.unit_meaning)]
    elif node.value_type == "TEXT" and node.text is not None:
        item.TextValue = node.text.value
    elif node.value_type == "CODE":
        item.ConceptCodeSequence = [_code_ds(node.concept.value, node.concept.scheme, node.concept.meaning)]
    if node.children:
        item.ContentSequence = [_to_content_item(child, now=now) for child in node.children]
    return item


def build_sr_dataset(
    tree: SrNode,
    *,
    patient_id: str = "",
    patient_name: str = "",
    birth_date: str = "",
    sex: str = "",
    study_uid: str = "",
    accession: str = "",
    physician: str = "",
    now: datetime | None = None,
) -> FileDataset:
    """Serialize the SR content tree into a TID 5200 FileDataset."""
    current = now or datetime.now(timezone.utc)
    study_uid = study_uid or generate_uid(prefix="1.3.6.1.4.1.61074.")
    series_uid = generate_uid(prefix="1.3.6.1.4.1.61074.")
    sop_uid = generate_uid(prefix="1.3.6.1.4.1.61074.")
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SR_SOP_CLASS_UID
    file_meta.MediaStorageSOPInstanceUID = UID(sop_uid)
    file_meta.TransferSyntaxUID = UID("1.2.840.10008.1.2.1")  # Explicit VR Little Endian
    file_meta.ImplementationClassUID = UID("1.3.6.1.4.1.61074.1")
    ds = FileDataset(b"", {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = SR_SOP_CLASS_UID
    ds.SOPInstanceUID = UID(sop_uid)
    ds.StudyInstanceUID = UID(study_uid)
    ds.SeriesInstanceUID = UID(series_uid)
    ds.Modality = "SR"
    ds.PatientID = patient_id
    ds.PatientName = patient_name
    ds.PatientBirthDate = birth_date.replace("-", "")
    ds.PatientSex = sex or "O"
    ds.AccessionNumber = accession
    ds.ReferringPhysicianName = physician
    ds.StudyDate = current.strftime("%Y%m%d")
    ds.StudyTime = current.strftime("%H%M%S")
    ds.SeriesDate = ds.StudyDate
    ds.SeriesTime = ds.StudyTime
    ds.ContentDate = ds.StudyDate
    ds.ContentTime = ds.StudyTime
    ds.VerificationFlag = "VERIFIED" if physician else "UNVERIFIED"
    ds.CompletionFlag = "COMPLETE"
    ds.VerificationDateTime = current.strftime("%Y%m%d%H%M%S")
    ds.ContentSequence = [_to_content_item(tree, now=current)]
    return ds


def sr_bytes(tree: SrNode, **kwargs: Any) -> bytes:
    """Serialize the SR dataset to bytes."""
    ds = build_sr_dataset(tree, **kwargs)
    import io

    buffer = io.BytesIO()
    ds.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()


def send_sr(
    tree: SrNode,
    *,
    upload_client: Any = None,
    use_stow: bool = False,
    stow_client: Any = None,
    **kwargs: Any,
) -> bool:
    """Send the SR object via STOW-RS or DIMSE C-STORE; True when accepted."""
    payload = sr_bytes(tree, **kwargs)
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
