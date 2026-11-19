"""Security/integration tests for #624: report signing lifecycle, guard, verification.

Covers the :class:`MeasurementRepository` signed-revision guard, the
``draft → signed → amended`` lifecycle, the detached ``.sig.json`` receipt,
offline verification (including archived keys of deactivated users) and the
PHI-free audit events ``report.signed`` / ``report.amended`` /
``signature.verified``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from echo_personal_tool.application.report_signing import ReportSigningService
from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
from echo_personal_tool.application.user_session import UserSessionService
from echo_personal_tool.domain.exceptions import ReportSignatureError
from echo_personal_tool.domain.models.audit import AuditAction
from echo_personal_tool.domain.models.report_signature import (
    ReportLifecycle,
    canonical_document_sha256,
    validate_receipt_history,
)
from echo_personal_tool.domain.models.user import SecretKind, UserRole
from echo_personal_tool.infrastructure.measurement_codec import MeasurementStorageError
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository
from echo_personal_tool.infrastructure.report_signer import (
    Ed25519SignerAdapter,
    read_receipt_file,
    receipt_path_for_pdf,
    write_receipt_file,
)

pytestmark = pytest.mark.security

FAST_N = 1 << 12
SECRET = "Physician#2026"
STUDY_UID = "1.2.840.113619.2.5.1"
SOURCES = {"1.2.3.4": {"fingerprint": "a" * 64, "frames": 5, "spacing": [0.5, 0.6]}}


from echo_personal_tool.domain.services.report_document import (
    PatientInfo,
    ReportDocument,
    ReportGroup,
    ReportValue,
)


def _document(value: str = "55") -> ReportDocument:
    return ReportDocument(
        patient=PatientInfo(name="Иванов И.И.", patient_id="P-1", study_date="2026-11-18", physician="Петров П.П."),
        groups=(
            ReportGroup(title="Левый желудочек", key="lv", values=(ReportValue(label="Е", value=value, unit="%"),)),
        ),
        title="Протокол ЭхоКГ",
        profile_id="echo",
    )


@pytest.fixture
def env(tmp_path: Path) -> tuple[UserSessionService, MeasurementRepository, ReportSigningService]:
    users_root = tmp_path / "users"
    session = UserSessionService(users_root, scrypt_n=FAST_N, scope_paths=False)
    session.bootstrap_first_admin(
        username="petrov",
        display_name="Петров П.П.",
        secret=SECRET,
        secret_kind=SecretKind.PASSWORD,
        title="врач УЗД",
    )
    repository = MeasurementRepository(tmp_path / "measurements")
    service = ReportSigningService(session=session, repository=repository)
    return session, repository, service


def _save_draft(repository: MeasurementRepository) -> dict:
    return repository.save(STUDY_UID, data=StudyMeasurementData(), sources=SOURCES, expected_revision=0, author_id="")


class TestRepositoryLifecycleGuard:
    def test_plain_save_of_signed_revision_is_locked(self, env, tmp_path: Path) -> None:
        _, repository, service = env
        _save_draft(repository)
        service.sign_report(_document(), study_uid=STUDY_UID, output_path=tmp_path / "a.pdf", secret=SECRET)
        with pytest.raises(MeasurementStorageError) as exc_info:
            repository.save(STUDY_UID, data=StudyMeasurementData(), sources=SOURCES, expected_revision=2)
        assert exc_info.value.code == "signed_locked"

    def test_signature_history_must_be_append_only(self, env, tmp_path: Path) -> None:
        _, repository, service = env
        _save_draft(repository)
        result = service.sign_report(_document(), study_uid=STUDY_UID, output_path=tmp_path / "r.pdf", secret=SECRET)
        receipt_dict = result.receipt.to_dict()
        forged = dict(receipt_dict, document_sha256="0" * 64)
        with pytest.raises(MeasurementStorageError) as exc_info:
            repository.save(
                STUDY_UID, data=StudyMeasurementData(), sources=SOURCES, expected_revision=2, signatures=[forged]
            )
        assert exc_info.value.code == "signed_locked"

    def test_codec_rejects_malformed_signature_envelope(self, env) -> None:
        from echo_personal_tool.infrastructure.measurement_codec import loads

        _, repository, _ = env
        record = _save_draft(repository)
        record["lifecycle"] = "signed"
        record["signatures"] = [{"format": "bogus"}]
        from echo_personal_tool.infrastructure.measurement_codec import dumps

        with pytest.raises(MeasurementStorageError):
            loads(dumps(record))


class TestSigningService:
    def test_sign_publishes_pdf_receipt_and_locks_record(self, env, tmp_path: Path) -> None:
        session, repository, service = env
        _save_draft(repository)
        pdf_path = tmp_path / "protocol.pdf"
        result = service.sign_report(_document(), study_uid=STUDY_UID, output_path=pdf_path, secret=SECRET)

        assert pdf_path.read_bytes().startswith(b"%PDF")
        receipt_path = receipt_path_for_pdf(pdf_path)
        assert receipt_path.exists()
        receipt = read_receipt_file(receipt_path)
        assert receipt.document_sha256 == canonical_document_sha256(_document())
        assert receipt.signer_display_name == "Петров П.П."
        assert receipt.signer_title == "врач УЗД"
        assert result.lifecycle == ReportLifecycle.SIGNED.value

        record = repository.load(STUDY_UID)
        assert record["lifecycle"] == "signed"
        assert len(record["signatures"]) == 1
        assert service.lifecycle_of(STUDY_UID) is ReportLifecycle.SIGNED

        # Audit event recorded, PHI-free.
        actions = [entry.action for entry in session.recent_audit_entries(limit=50)]
        assert AuditAction.REPORT_SIGNED.value in actions

    def test_wrong_secret_is_rejected_and_no_receipt_written(self, env, tmp_path: Path) -> None:
        _, repository, service = env
        _save_draft(repository)
        with pytest.raises(ReportSignatureError):
            service.sign_report(_document(), study_uid=STUDY_UID, output_path=tmp_path / "x.pdf", secret="Wrong#1")
        assert not (tmp_path / "x.pdf").exists()
        assert not (tmp_path / "x.sig.json").exists()

    def test_resign_signed_study_requires_amend(self, env, tmp_path: Path) -> None:
        _, repository, service = env
        _save_draft(repository)
        service.sign_report(_document(), study_uid=STUDY_UID, output_path=tmp_path / "a.pdf", secret=SECRET)
        with pytest.raises(ReportSignatureError) as exc_info:
            service.sign_report(_document("60"), study_uid=STUDY_UID, output_path=tmp_path / "b.pdf", secret=SECRET)
        assert exc_info.value.code == "already_signed"

    def test_amend_preserves_signature_history_and_adds_addendum(self, env, tmp_path: Path) -> None:
        session, repository, service = env
        _save_draft(repository)
        first = service.sign_report(_document(), study_uid=STUDY_UID, output_path=tmp_path / "a.pdf", secret=SECRET)
        amended = service.amend_report(
            _document("60"),
            study_uid=STUDY_UID,
            output_path=tmp_path / "b.pdf",
            secret=SECRET,
            reason="уточнение фракции выброса",
        )
        record = repository.load(STUDY_UID)
        assert record["lifecycle"] == "amended"
        signatures = validate_receipt_history(record["signatures"])
        assert len(signatures) == 2
        assert signatures[0].document_sha256 == first.receipt.document_sha256
        assert signatures[1].document_sha256 == amended.receipt.document_sha256
        assert signatures[1].lifecycle == "amended"
        addenda = record["addenda"]
        assert len(addenda) == 1
        assert addenda[0]["previous_document_sha256"] == first.receipt.document_sha256
        assert addenda[0]["new_document_sha256"] == amended.receipt.document_sha256
        assert addenda[0]["reason"] == "уточнение фракции выброса"
        actions = [entry.action for entry in session.recent_audit_entries(limit=50)]
        assert AuditAction.REPORT_AMENDED.value in actions

    def test_amend_of_draft_is_rejected(self, env, tmp_path: Path) -> None:
        _, repository, service = env
        _save_draft(repository)
        with pytest.raises(ReportSignatureError) as exc_info:
            service.amend_report(
                _document(), study_uid=STUDY_UID, output_path=tmp_path / "a.pdf", secret=SECRET, reason="x"
            )
        assert exc_info.value.code == "not_signed"


class TestOfflineVerification:
    def test_verify_valid_signed_pdf(self, env, tmp_path: Path) -> None:
        session, repository, service = env
        _save_draft(repository)
        pdf_path = tmp_path / "protocol.pdf"
        service.sign_report(_document(), study_uid=STUDY_UID, output_path=pdf_path, secret=SECRET)

        result = service.verify_report_pdf(pdf_path, document=_document())
        assert result.valid
        assert result.pdf_match and result.signature_match and result.document_match
        assert result.receipt is not None
        actions = [entry.action for entry in session.recent_audit_entries(limit=50)]
        assert AuditAction.SIGNATURE_VERIFIED.value in actions

    def test_verify_detects_tampered_pdf(self, env, tmp_path: Path) -> None:
        _, repository, service = env
        _save_draft(repository)
        pdf_path = tmp_path / "protocol.pdf"
        service.sign_report(_document(), study_uid=STUDY_UID, output_path=pdf_path, secret=SECRET)
        data = bytearray(pdf_path.read_bytes())
        data[-10] ^= 0xFF
        pdf_path.write_bytes(bytes(data))
        result = service.verify_report_pdf(pdf_path, document=_document())
        assert not result.valid
        assert not result.pdf_match
        assert result.signature_match  # receipt itself is intact

    def test_verify_detects_document_mismatch(self, env, tmp_path: Path) -> None:
        _, repository, service = env
        _save_draft(repository)
        pdf_path = tmp_path / "protocol.pdf"
        service.sign_report(_document(), study_uid=STUDY_UID, output_path=pdf_path, secret=SECRET)
        result = service.verify_report_pdf(pdf_path, document=_document("61"))
        assert not result.valid
        assert not result.document_match

    def test_verify_missing_receipt(self, env, tmp_path: Path) -> None:
        _, _, service = env
        pdf_path = tmp_path / "unsigned.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        result = service.verify_report_pdf(pdf_path)
        assert not result.valid
        assert result.receipt is None

    def test_verify_with_archived_key_after_rotation(self, env, tmp_path: Path) -> None:
        session, repository, service = env
        _save_draft(repository)
        pdf_path = tmp_path / "protocol.pdf"
        result = service.sign_report(_document(), study_uid=STUDY_UID, output_path=pdf_path, secret=SECRET)
        user_id = result.receipt.user_id
        key_id = result.receipt.key_id
        # Admin reset rotates the Ed25519 key: the signing key moves to the archive.
        session.admin_reset_secret(user_id, new_secret="Physician#2027", new_kind=SecretKind.PASSWORD)
        verify = service.verify_report_pdf(pdf_path, document=_document())
        assert verify.valid
        assert verify.key_archived
        assert verify.receipt is not None and verify.receipt.key_id == key_id
        assert verify.user_active


class TestSignerAdapterAndReceiptStore:
    def test_adapter_signs_and_verifies_roundtrip(self, tmp_path: Path) -> None:
        from echo_personal_tool.infrastructure.user_repository import LocalUserRepository

        repo = LocalUserRepository(tmp_path / "users", scrypt_n=FAST_N)
        now = datetime.now(timezone.utc)
        profile = repo.create_user(
            username="petrov",
            display_name="Петров П.П.",
            role=UserRole.ADMIN,
            secret=SECRET,
            secret_kind=SecretKind.PASSWORD,
            title="врач",
            enable_multi_user=False,
            now=now,
        )
        adapter = Ed25519SignerAdapter(repo, profile.user_id)
        payload = canonical_document_sha256(_document()).encode("ascii")
        signature = adapter.sign(payload, secret=SECRET)
        assert signature.algorithm == "ed25519"
        assert adapter.verify(payload, signature)
        assert not adapter.verify(payload + b" ", signature)
        with pytest.raises(ReportSignatureError):
            adapter.sign(payload, secret="Wrong#1")
        assert adapter.find_public_key(profile.user_id, signature.key_id) is not None

    def test_receipt_store_atomic_and_bounded(self, tmp_path: Path) -> None:
        from echo_personal_tool.domain.models.report_signature import SignatureReceipt

        receipt = SignatureReceipt.from_dict(
            {
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
                "signer_display_name": "Петров П.П.",
            }
        )
        target = tmp_path / "out" / "protocol.sig.json"
        write_receipt_file(target, receipt)
        assert read_receipt_file(target).to_dict() == receipt.to_dict()
        assert receipt_path_for_pdf(tmp_path / "protocol.pdf") == tmp_path / "protocol.sig.json"
        with pytest.raises(ReportSignatureError):
            read_receipt_file(tmp_path / "missing.sig.json")
        with pytest.raises(ReportSignatureError):
            write_receipt_file(tmp_path / "protocol.sig.txt", receipt)
