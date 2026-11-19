class IncompleteCineError(RuntimeError):
    """Raised when speckle tracking requires full cine but frames were evicted."""


class TrackingIncompleteError(RuntimeError):
    """Raised when too few kernels tracked successfully."""


class UserAuthError(RuntimeError):
    """Domain error for local user authentication, RBAC and account validation.

    ``code`` is a stable, allowlisted identifier safe for logs and i18n lookup;
    it never carries passwords, PINs, names or filesystem paths.
    """

    def __init__(self, code: str, message: str = "", *, retry_after_seconds: int = 0) -> None:
        super().__init__(message or code)
        self.code = code
        self.retry_after_seconds = max(0, int(retry_after_seconds))


class ReportSignatureError(RuntimeError):
    """Domain error for local report signing, verification and amendment.

    ``code`` is a stable, allowlisted identifier safe for logs and i18n lookup;
    it never carries patient data, secrets, signatures or filesystem paths.
    """

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class TransportPolicyError(RuntimeError):
    """Raised when a network operation or listener bind is blocked by policy.

    ``decision`` is the policy verdict object (duck-typed: ``code``, ``verdict``,
    ``findings``, ``summary()``) so the domain never imports the application layer.
    """

    def __init__(self, decision: object, message: str = "") -> None:
        self.decision = decision
        if not message:
            findings = getattr(decision, "findings", ()) or ()
            if findings:
                details = "; ".join(str(getattr(f, "message", f)) for f in findings)
            else:
                summary = getattr(decision, "summary", None)
                details = str(summary()) if callable(summary) else str(decision)
            message = f"[{getattr(decision, 'code', '')}] {details}"
        super().__init__(message)

    @property
    def code(self) -> str:
        return str(getattr(self.decision, "code", ""))

    @property
    def verdict(self) -> object:
        return getattr(self.decision, "verdict", None)

    @property
    def endpoint(self) -> object:
        return getattr(self.decision, "endpoint", None)


class InteropError(RuntimeError):
    """Domain error for outbound interop exchange (#625).

    ``code`` is a stable, allowlisted identifier safe for logs and i18n lookup;
    it never carries patient data, credentials, UIDs or filesystem paths.
    """

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
