"""Transport policy for PACS endpoints — the pure evaluator (QH-2b, S-08).

Before credentials or PHI leave the application, the *effective* endpoint has
to be judged: scheme, parsed host, port, TLS verification and — for redirects
— the destination authority.  This module is that judgement and nothing else:
it never opens a socket, never resolves a name, never imports Qt, settings
storage or the HTTP/DIMSE clients.  ``OrthancDicomWebClient``,
``PynetdimseClient``, server settings migration and UI dialogs consume the
decisions and :class:`TransportPolicyError` defined here.

Policy, as fixed by the QH spec §6.2:

* HTTPS / DIMSE-TLS with peer verification → allowed; a custom CA bundle is the
  supported path for self-signed PACS, not ``verify=False``.
* plaintext HTTP or clear DIMSE to a **parsed** loopback literal (``127/8``,
  ``::1``, IPv4-mapped loopback) or the exact name ``localhost`` → allowed for a
  local profile.  Look-alikes are not loopback: ``localhost.attacker.example``,
  ``127.0.0.1.nip.io``, ``127.1``, ``0177.0.0.1``, ``2130706433``,
  ``0x7f.0.0.1`` and ``user@127.0.0.1`` tricks are remote or invalid.
* plaintext to anything else — RFC1918 / link-local / ULA included — is
  **blocked** until the user grants an explicit *scoped* exception; a private
  network is not evidence of trust.
* TLS with verification disabled is blocked the same way; the exception keeps
  a visible insecure label (``Decision.insecure``).
* a redirect never downgrades HTTPS → HTTP, and credentials are not forwarded
  to another authority (scheme, host, port) even when the destination itself
  is acceptable.
* malformed URLs, unsupported schemes, embedded userinfo and unspecified
  addresses (``0.0.0.0``, ``::``) are rejected outright — no exception can
  unblock them and nothing is rewritten into a "working" address.

An exception (:class:`InsecureException`) is scoped to transport + host + port
+ TLS flavour; changing any of those invalidates it, so re-confirmation is
implicit.  Findings carry only ``host:port`` — never userinfo, query, UIDs or
secrets — so a decision can be logged as is.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from urllib.parse import SplitResult, urljoin, urlsplit

__all__ = [
    "Decision",
    "Endpoint",
    "EndpointError",
    "Finding",
    "HostKind",
    "InsecureException",
    "ProfileDecision",
    "Transport",
    "TransportPolicyError",
    "Verdict",
    "classify_host",
    "dimse_endpoint",
    "evaluate_dicomweb_url",
    "evaluate_dimse",
    "evaluate_endpoint",
    "evaluate_profile",
    "evaluate_redirect",
    "parse_dicomweb_endpoint",
]

_DEFAULT_PORTS = {"http": 80, "https": 443}
# RFC 1123 labels, plus "_" which intranet names use in practice; nothing else.
_HOSTNAME_RE = re.compile(r"^[a-z0-9_]([a-z0-9_-]*[a-z0-9_])?(\.[a-z0-9_]([a-z0-9_-]*[a-z0-9_])?)*$")
_PORT_RANGE = range(1, 65536)


class Transport(Enum):
    """Which client would carry the traffic."""

    DICOMWEB = "dicomweb"
    DIMSE = "dimse"


class HostKind(Enum):
    """What the *parsed* host literal is — never what it might resolve to."""

    #: ``127.0.0.0/8``, ``::1``, IPv4-mapped loopback, or exactly ``localhost``.
    LOOPBACK = "loopback"
    #: RFC1918, CGNAT, link-local, ULA, documentation ranges … — still remote.
    PRIVATE = "private"
    #: Any other IP literal.
    PUBLIC = "public"
    #: A DNS name that is not ``localhost``; remote until TLS proves otherwise.
    NAME = "name"
    #: Empty, unspecified (``0.0.0.0``/``::``) or syntactically impossible.
    INVALID = "invalid"


class Verdict(Enum):
    ALLOW = "allow"
    BLOCK = "block"


class EndpointError(ValueError):
    """The endpoint cannot be used at all; ``code`` is a stable finding code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Finding:
    """One reason behind a decision (stable ``code`` for logs/i18n, English ``message``)."""

    code: str
    message: str


@dataclass(frozen=True)
class Endpoint:
    """A parsed, normalised destination.  ``verify`` is only meaningful when ``secure``."""

    transport: Transport
    scheme: str
    host: str
    port: int
    secure: bool
    verify: bool = True
    ca_path: str = ""

    @property
    def authority(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    @property
    def host_kind(self) -> HostKind:
        return classify_host(self.host)

    @property
    def is_loopback(self) -> bool:
        return self.host_kind is HostKind.LOOPBACK

    @property
    def flavour(self) -> str:
        """``https`` / ``https-unverified`` / ``http`` / ``dimse-tls`` / … — the security shape."""
        if not self.secure:
            return self.scheme
        return self.scheme if self.verify else f"{self.scheme}-unverified"


@dataclass(frozen=True)
class InsecureException:
    """An explicit, user-granted exception for one insecure endpoint.

    The scope is transport + host + port + TLS flavour.  Any change to those is
    a different endpoint and needs a fresh decision (spec §6.2: consent does not
    travel with an edited profile, and there is no global "HTTP is fine").
    """

    transport: Transport
    host: str
    port: int
    secure: bool
    verify: bool

    @classmethod
    def for_endpoint(cls, endpoint: Endpoint) -> InsecureException:
        return cls(
            transport=endpoint.transport,
            host=endpoint.host,
            port=endpoint.port,
            secure=endpoint.secure,
            verify=endpoint.verify if endpoint.secure else True,
        )

    def covers(self, endpoint: Endpoint) -> bool:
        return self == InsecureException.for_endpoint(endpoint)


@dataclass(frozen=True)
class Decision:
    """The verdict for one endpoint (or one redirect hop)."""

    verdict: Verdict
    #: Stable code, e.g. ``allow``, ``allow-loopback``, ``allow-by-exception``,
    #: ``block-plaintext-remote``, ``block-tls-unverified``, ``block-dimse-clear-remote``,
    #: ``block-invalid-endpoint``, ``block-redirect-downgrade``, ``allow-redirect``,
    #: ``allow-redirect-cross-authority``.
    code: str
    findings: tuple[Finding, ...] = ()
    endpoint: Endpoint | None = None
    #: A scoped :class:`InsecureException` for ``endpoint`` would turn this BLOCK into ALLOW.
    requires_exception: bool = False
    #: Allowed only because of a scoped exception: keep a visible insecure label.
    insecure: bool = False
    #: Redirects only: credentials / custom secret headers may accompany the next request.
    forward_credentials: bool = False

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    @property
    def blocked(self) -> bool:
        return self.verdict is Verdict.BLOCK

    def summary(self) -> str:
        """Log-safe one-liner: code, transport and host kind — no host, URL or secret."""
        if self.endpoint is None:
            return f"transport-policy {self.code}"
        return (
            f"transport-policy {self.code} transport={self.endpoint.transport.value} "
            f"flavour={self.endpoint.flavour} host={self.endpoint.host_kind.value}"
        )


@dataclass(frozen=True)
class ProfileDecision:
    """All endpoints a server profile would touch, judged together."""

    decisions: tuple[Decision, ...]

    @property
    def allowed(self) -> bool:
        return all(decision.allowed for decision in self.decisions)

    @property
    def blocked(self) -> tuple[Decision, ...]:
        return tuple(decision for decision in self.decisions if decision.blocked)

    @property
    def insecure(self) -> bool:
        return any(decision.insecure for decision in self.decisions)


class TransportPolicyError(RuntimeError):
    """Raised when a network operation is blocked by the transport policy."""

    def __init__(self, decision: Decision, message: str = "") -> None:
        self.decision = decision
        if not message:
            details = "; ".join(f.message for f in decision.findings) if decision.findings else decision.summary()
            message = f"[{decision.code}] {details}"
        super().__init__(message)

    @property
    def code(self) -> str:
        return self.decision.code

    @property
    def verdict(self) -> Verdict:
        return self.decision.verdict

    @property
    def endpoint(self) -> Endpoint | None:
        return self.decision.endpoint


# ── host classification ─────────────────────────────────────────────


def classify_host(host: str) -> HostKind:
    """Classify a host literal by parsing it; substrings and suffixes prove nothing."""
    text = host.strip().lower()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    text = text.rstrip(".")
    if not text:
        return HostKind.INVALID
    literal = text.split("%", 1)[0]  # IPv6 zone id does not change the kind
    try:
        address = ipaddress.ip_address(literal)
    except ValueError:
        if text == "localhost":
            return HostKind.LOOPBACK
        return HostKind.NAME if _HOSTNAME_RE.match(text) else HostKind.INVALID
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if address.is_unspecified:
        return HostKind.INVALID
    if address.is_loopback:
        return HostKind.LOOPBACK
    if address.is_global:
        return HostKind.PUBLIC
    return HostKind.PRIVATE


# ── parsing ─────────────────────────────────────────────────────────


def _split_url(url: str) -> SplitResult:
    text = (url or "").strip()
    if not text:
        raise EndpointError("invalid-url", "server URL is empty")
    try:
        return urlsplit(text)
    except ValueError as exc:
        raise EndpointError("invalid-url", "server URL cannot be parsed") from exc


def parse_dicomweb_endpoint(url: str, *, tls_verify: bool = True, tls_ca_path: str = "") -> Endpoint:
    """Parse a DICOMweb/Orthanc URL into an :class:`Endpoint`; raise :class:`EndpointError` otherwise.

    Nothing is repaired: a missing scheme, ``ftp://``, an embedded ``user:pass@``,
    an out-of-range port or a host that is not a name or IP literal all fail.
    """
    parts = _split_url(url)
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise EndpointError(
            "unsupported-scheme", f"unsupported URL scheme {scheme or '(none)'!r}; use http:// or https://"
        )
    if parts.username is not None or parts.password is not None:
        raise EndpointError(
            "userinfo-in-url", "credentials embedded in the URL are rejected; use the username/password fields"
        )
    try:
        host = parts.hostname or ""
        port = parts.port
    except ValueError as exc:
        raise EndpointError("invalid-port", "URL port is not a number in 1-65535") from exc
    if classify_host(host) is HostKind.INVALID:
        raise EndpointError("invalid-host", "URL host is empty, unspecified or not a valid name/IP literal")
    if port is None:
        port = _DEFAULT_PORTS[scheme]
    if port not in _PORT_RANGE:
        raise EndpointError("invalid-port", "URL port is not a number in 1-65535")
    secure = scheme == "https"
    return Endpoint(
        transport=Transport.DICOMWEB,
        scheme=scheme,
        host=_normalise_host(host),
        port=port,
        secure=secure,
        verify=bool(tls_verify) if secure else True,
        ca_path=(tls_ca_path or "").strip(),
    )


def dimse_endpoint(
    host: str,
    port: int,
    *,
    use_tls: bool,
    tls_verify: bool = True,
    tls_ca_path: str = "",
) -> Endpoint:
    """Build the DIMSE :class:`Endpoint`; raise :class:`EndpointError` for an unusable host/port."""
    text = (host or "").strip()
    kind = classify_host(text)
    if kind is HostKind.INVALID:
        raise EndpointError("invalid-host", "DIMSE host is empty, unspecified or not a valid name/IP literal")
    try:
        port_number = int(port)
    except (TypeError, ValueError) as exc:
        raise EndpointError("invalid-port", "DIMSE port is not a number in 1-65535") from exc
    if port_number not in _PORT_RANGE:
        raise EndpointError("invalid-port", "DIMSE port is not a number in 1-65535")
    secure = bool(use_tls)
    return Endpoint(
        transport=Transport.DIMSE,
        scheme="dimse-tls" if secure else "dimse",
        host=_normalise_host(text),
        port=port_number,
        secure=secure,
        verify=bool(tls_verify) if secure else True,
        ca_path=(tls_ca_path or "").strip(),
    )


def _normalise_host(host: str) -> str:
    text = host.strip().lower()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text.rstrip(".")


# ── evaluation ──────────────────────────────────────────────────────


def _blocked(code: str, finding: Finding, endpoint: Endpoint, exceptions: Iterable[InsecureException]) -> Decision:
    if any(exception.covers(endpoint) for exception in exceptions):
        return Decision(
            Verdict.ALLOW,
            "allow-by-exception",
            findings=(finding,),
            endpoint=endpoint,
            insecure=True,
        )
    return Decision(Verdict.BLOCK, code, findings=(finding,), endpoint=endpoint, requires_exception=True)


def evaluate_endpoint(endpoint: Endpoint, *, exceptions: Iterable[InsecureException] = ()) -> Decision:
    """Judge one parsed endpoint against the policy table."""
    exceptions = tuple(exceptions)
    kind = endpoint.host_kind
    if kind is HostKind.INVALID:
        return Decision(
            Verdict.BLOCK,
            "block-invalid-endpoint",
            findings=(Finding("invalid-host", "host is empty, unspecified or not a valid name/IP literal"),),
            endpoint=endpoint,
        )
    if endpoint.secure and endpoint.verify:
        return Decision(Verdict.ALLOW, "allow", endpoint=endpoint)
    if kind is HostKind.LOOPBACK:
        # Local profile: plaintext / unverified TLS to the machine itself is the
        # sanctioned local path, not an exception — no insecure label.
        return Decision(Verdict.ALLOW, "allow-loopback", endpoint=endpoint)
    where = "a private network address" if kind is HostKind.PRIVATE else "a remote host"
    if not endpoint.secure:
        if endpoint.transport is Transport.DIMSE:
            finding = Finding(
                "dimse-clear-remote",
                f"DIMSE without TLS to {where} {endpoint.authority}: credentials and PHI would travel in clear; "
                "a private LAN is not evidence of trust",
            )
            return _blocked("block-dimse-clear-remote", finding, endpoint, exceptions)
        finding = Finding(
            "plaintext-remote",
            f"plaintext HTTP to {where} {endpoint.authority}: credentials and PHI would travel in clear; "
            "a private LAN is not evidence of trust — use https:// or grant a scoped exception",
        )
        return _blocked("block-plaintext-remote", finding, endpoint, exceptions)
    finding = Finding(
        "tls-unverified",
        f"TLS certificate verification is disabled for {endpoint.authority}: the peer cannot be told from an "
        "attacker — configure a CA bundle instead of disabling verification",
    )
    return _blocked("block-tls-unverified", finding, endpoint, exceptions)


def _invalid(error: EndpointError) -> Decision:
    return Decision(Verdict.BLOCK, "block-invalid-endpoint", findings=(Finding(error.code, error.message),))


def evaluate_dicomweb_url(
    url: str,
    *,
    tls_verify: bool = True,
    tls_ca_path: str = "",
    exceptions: Iterable[InsecureException] = (),
) -> Decision:
    """Parse + judge a DICOMweb URL; a URL that cannot be parsed is blocked without any exception."""
    try:
        endpoint = parse_dicomweb_endpoint(url, tls_verify=tls_verify, tls_ca_path=tls_ca_path)
    except EndpointError as error:
        return _invalid(error)
    return evaluate_endpoint(endpoint, exceptions=exceptions)


def evaluate_dimse(
    host: str,
    port: int,
    *,
    use_tls: bool,
    tls_verify: bool = True,
    tls_ca_path: str = "",
    exceptions: Iterable[InsecureException] = (),
) -> Decision:
    """Build + judge a DIMSE association target."""
    try:
        endpoint = dimse_endpoint(host, port, use_tls=use_tls, tls_verify=tls_verify, tls_ca_path=tls_ca_path)
    except EndpointError as error:
        return _invalid(error)
    return evaluate_endpoint(endpoint, exceptions=exceptions)


def evaluate_redirect(
    origin_url: str,
    location: str,
    *,
    tls_verify: bool = True,
    tls_ca_path: str = "",
    exceptions: Iterable[InsecureException] = (),
) -> Decision:
    """Judge the effective destination of a redirect issued by ``origin_url``.

    * the destination must pass the endpoint policy on its own (a loopback
      origin does not extend trust to a remote ``Location``);
    * HTTPS → HTTP is a downgrade and is blocked outright, exception or not;
    * credentials and custom secret headers may follow only when the
      destination is the very same authority (scheme, host, port).
    """
    try:
        origin = parse_dicomweb_endpoint(origin_url, tls_verify=tls_verify, tls_ca_path=tls_ca_path)
    except EndpointError as error:
        return _invalid(error)
    try:
        target_url = urljoin(origin_url.strip(), (location or "").strip())
        target = parse_dicomweb_endpoint(target_url, tls_verify=tls_verify, tls_ca_path=tls_ca_path)
    except (EndpointError, ValueError) as error:
        code = error.code if isinstance(error, EndpointError) else "invalid-url"
        message = error.message if isinstance(error, EndpointError) else "redirect location cannot be parsed"
        return Decision(Verdict.BLOCK, "block-invalid-endpoint", findings=(Finding(code, message),))
    if origin.secure and not target.secure:
        return Decision(
            Verdict.BLOCK,
            "block-redirect-downgrade",
            findings=(
                Finding(
                    "redirect-downgrade",
                    f"redirect from https {origin.authority} to plaintext http {target.authority} refused: "
                    "no HTTPS to HTTP fallback",
                ),
            ),
            endpoint=target,
        )
    decision = evaluate_endpoint(target, exceptions=exceptions)
    if decision.blocked:
        return decision
    same_authority = (origin.scheme, origin.host, origin.port) == (target.scheme, target.host, target.port)
    if same_authority:
        return Decision(
            Verdict.ALLOW,
            "allow-redirect",
            findings=decision.findings,
            endpoint=target,
            insecure=decision.insecure,
            forward_credentials=True,
        )
    cross = Finding(
        "redirect-cross-authority",
        f"redirect leaves {origin.authority} for {target.authority}: credentials and custom headers are withheld",
    )
    return Decision(
        Verdict.ALLOW,
        "allow-redirect-cross-authority",
        findings=(*decision.findings, cross),
        endpoint=target,
        insecure=decision.insecure,
        forward_credentials=False,
    )


def evaluate_profile(
    *,
    url: str,
    tls_verify: bool = True,
    tls_ca_path: str = "",
    stow_url: str = "",
    dimse_enabled: bool = False,
    dimse_host: str = "",
    dimse_port: int = 0,
    dimse_use_tls: bool = False,
    dimse_tls_verify: bool = True,
    dimse_tls_ca_path: str = "",
    exceptions: Iterable[InsecureException] = (),
) -> ProfileDecision:
    """Judge every endpoint a server profile would contact (QIDO/WADO root, STOW override, DIMSE)."""
    exceptions = tuple(exceptions)
    decisions = [evaluate_dicomweb_url(url, tls_verify=tls_verify, tls_ca_path=tls_ca_path, exceptions=exceptions)]
    if (stow_url or "").strip():
        decisions.append(
            evaluate_dicomweb_url(stow_url, tls_verify=tls_verify, tls_ca_path=tls_ca_path, exceptions=exceptions)
        )
    if dimse_enabled:
        decisions.append(
            evaluate_dimse(
                dimse_host,
                dimse_port,
                use_tls=dimse_use_tls,
                tls_verify=dimse_tls_verify,
                tls_ca_path=dimse_tls_ca_path,
                exceptions=exceptions,
            )
        )
    return ProfileDecision(tuple(decisions))
