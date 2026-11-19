"""Pure-domain tests for the #624 report-signature model (stdlib only)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from echo_personal_tool.domain.exceptions import ReportSignatureError
from echo_personal_tool.domain.models.report_signature import (
    MAX_ADDENDA_PER_RECORD,
    MAX_SIGNATURES_PER_RECORD,
    ReportAddendum,
    ReportLifecycle,
    SignatureReceipt,
    build_receipt,
    build_stamp,
    canonical_document_sha256,
    canonical_report_bytes,
    canonical_report_dict,
    lifecycle_for_history,
    new_addendum_id,
    next_lifecycle_after_sign,
    validate_addendum_history,
    validate_addendum_reason,
    validate_receipt_history,
    validate_signer_name,
    validate_signer_title,
)


@dataclass(frozen=True)
class _Value:
    label: str = "Е"
    value: str = "55"
    unit: str = "%"
    norm: str = "50–70"
    pathological: bool = False
    group: str = "LV"
    sample_count: int | None = None
    key: str = "ef"
    parameter_id: str = "lv_ef"
    repeat_sd: str = ""
    repeat_cv: str = ""


@dataclass(frozen=True)
class _Group:
    title: str = "Левый желудочек"
    key: str = "lv"
    notes: tuple[str, ...] = ()
    values: tuple[_Value, ...] = field(default_factory=lambda: (_Value(),))


@dataclass(frozen=True)
class _Patient:
    name: str = "Иванов И.И."
    patient_id: str = "P-1"
    birth_date: str = "1980-01-01"
    age: str = "46"
    sex: str = "М"
    study_date: str = "2026-11-18"
    height_cm: float | None = 180.0
    weight_kg: float | None = 80.0
    bsa_m2: float | None = 1.98
    physician: str = "Петров П.П., врач"
    institution: str = "Клиника"
    indication: str = "Плановый осмотр"
    conclusion: str = "Без патологии"
    equipment: str = "SonoForge"


@dataclass(frozen=True)
class _Document:
    patient: _Patient = field(default_factory=_Patient)
    groups: tuple[_Group, ...] = field(default_factory=lambda: (_Group(),))
    title: str = "Протокол ЭхоКГ"
    profile_id: str = "echo"
    draft: bool = False
    notices: tuple[str, ...] = ()


def _receipt_dict(**overrides) -> dict:
    base = {
        "format": "sonoforge.report-signature",
        "schema_version": 1,
        "user_id": "0123456789abcdef0123456789abcdef",
        "key_id": "0123456789abcdef",
        "algorithm": "ed25519",
        "public_key_b64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "signed_at": "2026-11-18T10:00:00+00:00",
        "document_sha256": "a" * 64,
        "pdf_sha256": "b" * 64,
        "signature_b64": "A" * 86 + "==",
        "lifecycle": "signed",
        "revision": 1,
        "signer_display_name": "Петров П.П.",
        "signer_title": "врач УЗД",
    }
    base.update(overrides)
    return base


class TestCanonicalSnapshot:
    def test_canonical_bytes_are_deterministic_and_content_bound(self) -> None:
        doc = _Document()
        assert canonical_report_bytes(doc) == canonical_report_bytes(doc)
        assert canonical_document_sha256(doc) == canonical_document_sha256(_Document())
        changed = _Document(title="Другой протокол")
        assert canonical_document_sha256(changed) != canonical_document_sha256(doc)

    def test_snapshot_covers_printed_content_only(self) -> None:
        payload = canonical_report_dict(_Document())
        assert payload["patient"]["name"] == "Иванов И.И."
        assert payload["groups"][0]["values"][0]["label"] == "Е"
        assert payload["title"] == "Протокол ЭхоКГ"
        assert set(payload) == {"patient", "title", "profile_id", "draft", "notices", "groups"}


class TestReceiptRoundtrip:
    def test_receipt_dict_roundtrip(self) -> None:
        receipt = SignatureReceipt.from_dict(_receipt_dict())
        assert receipt.to_dict() == _receipt_dict()
        assert len(receipt.signature_bytes()) == 64

    @pytest.mark.parametrize(
        "override",
        [
            {"format": "other"},
            {"schema_version": 2},
            {"algorithm": "rsa"},
            {"user_id": "not-hex"},
            {"key_id": "zz"},
            {"document_sha256": "xyz"},
            {"signature_b64": "!!!"},
            {"lifecycle": "bogus"},
            {"revision": -1},
            {"signer_display_name": ""},
        ],
    )
    def test_from_dict_rejects_malformed_receipts(self, override: dict) -> None:
        with pytest.raises(ReportSignatureError):
            SignatureReceipt.from_dict(_receipt_dict(**override))

    def test_build_receipt_hashes_document_and_pdf(self) -> None:
        doc = _Document()
        receipt = build_receipt(
            user_id="0123456789abcdef0123456789abcdef",
            key_id="0123456789abcdef",
            public_key_b64="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            signature=b"\x01" * 64,
            document=doc,
            pdf_bytes=b"%PDF-1.4 fake",
            signed_at="2026-11-18T10:00:00+00:00",
            signer_display_name="Петров П.П.",
            signer_title="врач",
        )
        assert receipt.document_sha256 == canonical_document_sha256(doc)
        import hashlib

        assert receipt.pdf_sha256 == hashlib.sha256(b"%PDF-1.4 fake").hexdigest()
        stamp = build_stamp(receipt)
        assert stamp.signer_label == "Петров П.П., врач"
        assert stamp.key_id == "0123456789abcdef"


class TestHistoriesAndLifecycle:
    def test_lifecycle_derivation(self) -> None:
        receipt = SignatureReceipt.from_dict(_receipt_dict())
        assert lifecycle_for_history(signatures=(), addenda=()) is ReportLifecycle.DRAFT
        assert lifecycle_for_history(signatures=(receipt,), addenda=()) is ReportLifecycle.SIGNED
        addendum = ReportAddendum.from_dict(
            {
                "addendum_id": new_addendum_id(),
                "created_at": "2026-11-18T11:00:00+00:00",
                "author_user_id": "0123456789abcdef0123456789abcdef",
                "reason": "уточнение",
                "previous_document_sha256": "a" * 64,
                "new_document_sha256": "c" * 64,
            }
        )
        assert lifecycle_for_history(signatures=(receipt,), addenda=(addendum,)) is ReportLifecycle.AMENDED

    def test_next_lifecycle_after_sign(self) -> None:
        assert next_lifecycle_after_sign(ReportLifecycle.DRAFT) is ReportLifecycle.SIGNED
        assert next_lifecycle_after_sign(ReportLifecycle.AMENDED) is ReportLifecycle.AMENDED
        with pytest.raises(ReportSignatureError):
            next_lifecycle_after_sign(ReportLifecycle.SIGNED)

    def test_histories_are_bounded(self) -> None:
        receipt = _receipt_dict()
        with pytest.raises(ReportSignatureError):
            validate_receipt_history([receipt] * (MAX_SIGNATURES_PER_RECORD + 1))
        assert len(validate_receipt_history([receipt])) == 1
        with pytest.raises(ReportSignatureError):
            validate_addendum_history(["nope"] * (MAX_ADDENDA_PER_RECORD + 1))


class TestValidators:
    def test_signer_name_and_title(self) -> None:
        assert validate_signer_name("  Петров П.П. ") == "Петров П.П."
        assert validate_signer_title("") == ""
        with pytest.raises(ReportSignatureError):
            validate_signer_name("")
        with pytest.raises(ReportSignatureError):
            validate_signer_name("x" * 121)
        with pytest.raises(ReportSignatureError):
            validate_signer_name("bad\nname")

    def test_addendum_reason(self) -> None:
        assert validate_addendum_reason("  правка ") == "правка"
        with pytest.raises(ReportSignatureError):
            validate_addendum_reason("")
        with pytest.raises(ReportSignatureError):
            validate_addendum_reason("a\tb")
