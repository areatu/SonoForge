"""DICOM Encapsulated PDF tag contract (#625) — pure domain, stdlib only.

The infrastructure adapter (pydicom) builds the dataset from this contract;
keeping the layout here makes it testable without pydicom and documents
exactly which attributes an encapsulated report must carry.

SOP Class: Encapsulated PDF Storage ``1.2.840.10008.5.1.4.1.1.104.1``.
The signed report PDF travels as ``EncapsulatedDocument`` (OB, application/pdf)
with a ``VerifyingObserverSequence`` naming the local-EP signer — the DICOM
way to say «who verified this document», honestly as a local app EP.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Encapsulated PDF Storage SOP Class UID.
ENCAPSULATED_PDF_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.104.1"
#: MIME type of the encapsulated document.
PDF_MIME_TYPE = "application/pdf"


@dataclass(frozen=True)
class VerifyingObserver:
    """One entry of ``VerifyingObserverSequence`` (0040,A073)."""

    name: str  # signer display name («ФИО, должность»)
    organization: str = ""  # verifying organization (institution)
    key_id: str = ""  # local Ed25519 key fingerprint, kept as observation text


@dataclass(frozen=True)
class EncapsulatedPdfSpec:
    """Everything needed to build the encapsulated PDF dataset."""

    patient_name: str = ""
    patient_id: str = ""
    birth_date: str = ""  # YYYYMMDD
    sex: str = ""  # M / F / U
    study_uid: str = ""
    series_uid: str = ""
    sop_instance_uid: str = ""
    study_date: str = ""  # YYYYMMDD
    study_time: str = ""  # HHMMSS
    modality: str = "DOC"
    series_description: str = "Signed report PDF"
    document_title: str = ""
    verifying_observers: tuple[VerifyingObserver, ...] = ()
    pdf_bytes: bytes = b""

    def validate(self) -> None:
        """Structural checks that do not depend on pydicom."""
        if not self.sop_instance_uid or not self.study_uid or not self.series_uid:
            raise ValueError("missing_uid")
        if not self.pdf_bytes.startswith(b"%PDF"):
            raise ValueError("not_a_pdf")
        if not self.verifying_observers:
            raise ValueError("no_verifying_observer")
