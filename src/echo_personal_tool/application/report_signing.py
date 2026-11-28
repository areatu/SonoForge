"""Application service for local Ed25519 signing of study reports (#624).

Flow of :meth:`ReportSigningService.sign_report`:

1. the canonical snapshot of the shown :class:`ReportDocument` is hashed
   (SHA-256) and the *hex digest* is signed with the active user's Ed25519
   key — the private key is unwrapped with the password/PIN re-entered at
   this moment only (:meth:`UserSessionService.sign_payload` re-authenticates
   and enforces ``SIGN_REPORT`` plus brute-force lockout);
2. the sheet is rendered with the visual local-EP stamp (ФИО, должность,
   UTC time, key fingerprint, document SHA-256 — labelled as a local app
   EP, not УКЭП) and published atomically as PDF;
3. the detached receipt ``<name>.sig.json`` is written next to the PDF;
4. the receipt is appended to the study record's signature history in
   :class:`MeasurementRepository` (append-only; a signed revision is never
   overwritten silently) and a PHI-free ``report.signed`` audit event is
   written to the hash-chained ``audit.jsonl``.

:meth:`amend_report` adds an explicit addendum to an already signed protocol
(lifecycle ``signed → amended``) keeping the whole signature history, and
:meth:`verify_report_pdf` performs the offline «Проверить подпись…» check,
including archived public keys of deactivated or rotated users.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from echo_personal_tool.application import report_export
from echo_personal_tool.domain.exceptions import ReportSignatureError, UserAuthError
from echo_personal_tool.domain.models.audit import AuditAction
from echo_personal_tool.domain.models.report_signature import (
    ReportAddendum,
    ReportLifecycle,
    SignatureReceipt,
    SignatureStamp,
    SignatureVerificationResult,
    build_receipt,
    canonical_document_sha256,
    lifecycle_for_history,
    new_addendum_id,
    sha256_hex,
    utc_now_iso,
    validate_addendum_history,
    validate_addendum_reason,
    validate_receipt_history,
)
from echo_personal_tool.domain.models.user import ArchivedSigningKey, Permission, UserProfile
from echo_personal_tool.infrastructure.measurement_codec import study_key
from echo_personal_tool.infrastructure.report_signer import (
    read_receipt_file,
    receipt_path_for_pdf,
    write_receipt_file,
)

if TYPE_CHECKING:
    from echo_personal_tool.application.user_session import UserSessionService
    from echo_personal_tool.domain.services.report_builder import ReportDocument
    from echo_personal_tool.domain.services.report_template import ReportTemplate
    from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository


@dataclass(frozen=True)
class SignReportResult:
    """Outcome of one successful signing/amendment (no secrets, no paths of secrets)."""

    receipt: SignatureReceipt
    pdf_path: Path
    receipt_path: Path
    document_sha256: str
    pdf_sha256: str
    lifecycle: str


class ReportSigningService:
    """Sign, amend and verify study reports for the active local session."""

    def __init__(
        self,
        *,
        session: UserSessionService,
        repository: MeasurementRepository,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._repository = repository
        self._now = now

    # ── signing ──────────────────────────────────────────────────────

    def sign_report(
        self,
        document: ReportDocument,
        *,
        study_uid: str,
        output_path: Path,
        secret: str,
        font_size: int = 10,
        template: ReportTemplate | None = None,
        research_banner: bool = True,
    ) -> SignReportResult:
        """Sign the shown document and publish the stamped PDF + receipt.

        Only a *draft* study can be signed; an already signed/amended record
        must go through :meth:`amend_report` instead.
        """
        user = self._signer_user()
        previous = self._repository.load(study_uid)
        if previous is not None and str(previous.get("lifecycle", "")) in ("signed", "amended"):
            raise ReportSignatureError("already_signed")
        return self._sign_and_publish(
            document,
            study_uid=study_uid,
            output_path=output_path,
            secret=secret,
            font_size=font_size,
            template=template,
            research_banner=research_banner,
            user=user,
            lifecycle=ReportLifecycle.SIGNED.value,
            revision=(int(previous["revision"]) if previous else 0) + 1,
            addendum=None,
        )

    def amend_report(
        self,
        document: ReportDocument,
        *,
        study_uid: str,
        output_path: Path,
        secret: str,
        reason: str,
        font_size: int = 10,
        template: ReportTemplate | None = None,
        research_banner: bool = True,
    ) -> SignReportResult:
        """Amend a signed protocol: new signed revision + explicit addendum.

        The previous signature history is preserved verbatim (append-only)
        and the addendum links the previous and new document hashes with the
        mandatory reason.
        """
        user = self._signer_user()
        previous = self._repository.load(study_uid)
        if previous is None:
            raise ReportSignatureError("not_found")
        receipts = validate_receipt_history(previous.get("signatures", []))
        addenda = validate_addendum_history(previous.get("addenda", []))
        if not receipts:
            raise ReportSignatureError("not_signed")
        previous_digest = addenda[-1].new_document_sha256 if addenda else receipts[-1].document_sha256
        new_digest = canonical_document_sha256(document)
        addendum = ReportAddendum(
            addendum_id=new_addendum_id(),
            created_at=utc_now_iso(now=self._now() if self._now else None),
            author_user_id=user.user_id,
            reason=validate_addendum_reason(reason),
            previous_document_sha256=previous_digest,
            new_document_sha256=new_digest,
        )
        return self._sign_and_publish(
            document,
            study_uid=study_uid,
            output_path=output_path,
            secret=secret,
            font_size=font_size,
            template=template,
            research_banner=research_banner,
            user=user,
            lifecycle=ReportLifecycle.AMENDED.value,
            revision=int(previous["revision"]) + 1,
            addendum=addendum,
        )

    # ── verification ─────────────────────────────────────────────────

    def verify_report_pdf(
        self,
        pdf_path: Path,
        *,
        document: ReportDocument | None = None,
    ) -> SignatureVerificationResult:
        """Offline «Проверить подпись…»: receipt + PDF hash + Ed25519 check.

        The Ed25519 signature is verified against the active *or archived*
        public key of the signer, so reports signed by since-deactivated or
        key-rotated users still verify.  When *document* is given, its
        canonical hash is compared to the receipt as well.  A PHI-free
        ``signature.verified`` audit event is recorded either way.
        """
        target = Path(pdf_path)
        try:
            receipt = read_receipt_file(receipt_path_for_pdf(target))
            pdf_bytes = target.read_bytes()
        except (ReportSignatureError, OSError) as exc:
            result = SignatureVerificationResult(valid=False, reason=getattr(exc, "code", "io_error"))
            self._audit_verify(study_uid="", result=result, receipt=None)
            return result
        pdf_match = sha256_hex(pdf_bytes) == receipt.pdf_sha256
        payload = receipt.document_sha256.encode("ascii")
        signature_match = self._session.verify_user_signature(
            user_id=receipt.user_id,
            key_id=receipt.key_id,
            payload=payload,
            signature=receipt.signature_bytes(),
        )
        key_archived = False
        user_active = True
        profile = next(
            (item for item in self._session.list_users(include_inactive=True) if item.user_id == receipt.user_id),
            None,
        )
        if profile is not None:
            user_active = profile.active
            found = profile.find_public_key(receipt.key_id)
            key_archived = isinstance(found, ArchivedSigningKey)
        document_match = (
            canonical_document_sha256(document) == receipt.document_sha256 if document is not None else False
        )
        valid = signature_match and pdf_match and (document is None or document_match)
        result = SignatureVerificationResult(
            valid=valid,
            reason="ok" if valid else "mismatch",
            receipt=receipt,
            key_archived=key_archived,
            user_active=user_active,
            document_match=document_match if document is not None else False,
            pdf_match=pdf_match,
            signature_match=signature_match,
        )
        self._audit_verify(study_uid="", result=result, receipt=receipt)
        return result

    # ── internals ────────────────────────────────────────────────────

    def _signer_user(self) -> UserProfile:
        if not self._session.can(Permission.SIGN_REPORT):
            raise ReportSignatureError("permission_denied")
        user = self._session.session.user
        if user is None or not user.active:
            raise ReportSignatureError("session_locked")
        return user

    def _sign_and_publish(
        self,
        document: ReportDocument,
        *,
        study_uid: str,
        output_path: Path,
        secret: str,
        font_size: int,
        template: ReportTemplate | None,
        research_banner: bool,
        user: UserProfile,
        lifecycle: str,
        revision: int,
        addendum: ReportAddendum | None,
    ) -> SignReportResult:
        digest = canonical_document_sha256(document)
        try:
            key_pub, signature = self._session.sign_payload(secret=secret, payload=digest.encode("ascii"))
        except UserAuthError as exc:
            raise ReportSignatureError(exc.code) from exc
        signed_at = utc_now_iso(now=self._now() if self._now else None)
        stamp = SignatureStamp(
            signer_display_name=user.display_name,
            signer_title=user.title,
            signed_at=signed_at,
            key_id=key_pub.key_id,
            document_sha256=digest,
        )
        rendered = report_export.render_report(
            document, font_size=font_size, template=template, stamp=stamp, research_banner=research_banner
        )
        receipt = build_receipt(
            user_id=user.user_id,
            key_id=key_pub.key_id,
            public_key_b64=key_pub.public_key_b64,
            signature=signature,
            document=document,
            pdf_bytes=rendered.pdf,
            signed_at=signed_at,
            lifecycle=lifecycle,
            revision=revision,
            signer_display_name=user.display_name,
            signer_title=user.title,
        )
        destination = Path(output_path)
        report_export.publish_report_pdf(rendered.pdf, destination)
        receipt_path = write_receipt_file(receipt_path_for_pdf(destination), receipt)
        record = self._repository.append_signature(study_uid, receipt.to_dict(), author_id=user.user_id)
        if addendum is not None:
            record = self._repository.append_addendum(study_uid, addendum.to_dict(), author_id=user.user_id)
        self._session.record_study_audit(
            AuditAction.REPORT_SIGNED if lifecycle == ReportLifecycle.SIGNED.value else AuditAction.REPORT_AMENDED,
            study_key=study_key(study_uid),
            details={
                "key_id": receipt.key_id,
                "document_sha256": receipt.document_sha256,
                "pdf_sha256": receipt.pdf_sha256,
                "lifecycle": lifecycle,
                "revision": int(record.get("revision", revision)),
            },
        )
        return SignReportResult(
            receipt=receipt,
            pdf_path=destination,
            receipt_path=receipt_path,
            document_sha256=receipt.document_sha256,
            pdf_sha256=receipt.pdf_sha256,
            lifecycle=lifecycle,
        )

    def _audit_verify(
        self,
        *,
        study_uid: str,
        result: SignatureVerificationResult,
        receipt: SignatureReceipt | None,
    ) -> None:
        details = {
            "outcome": "ok" if result.valid else "failed",
            "status": result.reason,
        }
        if receipt is not None:
            details["key_id"] = receipt.key_id
            details["document_sha256"] = receipt.document_sha256
        self._session.record_study_audit(
            AuditAction.SIGNATURE_VERIFIED,
            study_key=study_key(study_uid) if study_uid else "",
            details=details,
        )

    def lifecycle_of(self, study_uid: str) -> ReportLifecycle:
        """Current lifecycle of a stored study record (draft when unsigned)."""
        previous = self._repository.load(study_uid)
        if previous is None:
            return ReportLifecycle.DRAFT
        receipts = validate_receipt_history(previous.get("signatures", []))
        addenda = validate_addendum_history(previous.get("addenda", []))
        return lifecycle_for_history(signatures=receipts, addenda=addenda)
