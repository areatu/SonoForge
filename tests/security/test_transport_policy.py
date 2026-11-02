"""Transport policy evaluator (QH-2b slice 1, S-08, acceptance A-09/A-10 — decision layer).

Every scenario of spec §6.2/§6.3 "unit tests pure evaluator" has a test here:
parsed loopback / IPv6 / look-alikes, HTTP vs HTTPS, invalid URLs, a changed
scope invalidating an exception, STOW/DIMSE overrides, downgrade and
cross-authority redirects.  Nothing here touches the network, Qt or settings
storage; the production clients adopt the decisions in slice 2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.application import transport_policy as policy
from echo_personal_tool.application.transport_policy import (
    Decision,
    Endpoint,
    EndpointError,
    HostKind,
    InsecureException,
    Transport,
    Verdict,
    classify_host,
    dimse_endpoint,
    evaluate_dicomweb_url,
    evaluate_dimse,
    evaluate_endpoint,
    evaluate_profile,
    evaluate_redirect,
    parse_dicomweb_endpoint,
)

pytestmark = pytest.mark.security


# ── host classification: parsed, never substring ─────────────────────


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.1.2.3",
        "127.255.255.254",
        "::1",
        "[::1]",
        "::ffff:127.0.0.1",
        "::ffff:7f00:1",
        "localhost",
        "LOCALHOST",
        "localhost.",
    ],
)
def test_loopback_is_recognised_from_the_parsed_literal(host: str) -> None:
    assert classify_host(host) is HostKind.LOOPBACK


@pytest.mark.parametrize(
    "host",
    [
        "localhost.attacker.example",  # suffix trick
        "127.0.0.1.nip.io",  # prefix trick
        "127.0.0.1.attacker.example",
        "mylocalhost",
        "localhost-proxy",
        "127.1",  # shorthand the OS resolver would accept
        "0177.0.0.1",  # octal
        "0x7f.0.0.1",  # hex
        "2130706433",  # decimal
        "127.000.000.001",  # leading zeros
        "::ffff:127.0.0.1.evil",
    ],
)
def test_loopback_look_alikes_are_not_loopback(host: str) -> None:
    assert classify_host(host) is not HostKind.LOOPBACK


@pytest.mark.parametrize(
    ("host", "kind"),
    [
        ("192.168.1.111", HostKind.PRIVATE),
        ("10.0.0.5", HostKind.PRIVATE),
        ("172.16.0.1", HostKind.PRIVATE),
        ("169.254.10.10", HostKind.PRIVATE),
        ("100.64.0.1", HostKind.PRIVATE),
        ("fe80::1%eth0", HostKind.PRIVATE),
        ("fd12:3456::1", HostKind.PRIVATE),
        ("172.32.0.1", HostKind.PUBLIC),
        ("8.8.8.8", HostKind.PUBLIC),
        ("2606:4700::1", HostKind.PUBLIC),
        ("pacs.hospital.example", HostKind.NAME),
        ("pacs_01.intranet", HostKind.NAME),
        ("", HostKind.INVALID),
        ("   ", HostKind.INVALID),
        ("0.0.0.0", HostKind.INVALID),
        ("::", HostKind.INVALID),
        ("exa mple.com", HostKind.INVALID),
        ("-bad.example", HostKind.INVALID),
        ("bad..example", HostKind.INVALID),
    ],
)
def test_private_public_name_and_invalid_hosts(host: str, kind: HostKind) -> None:
    assert classify_host(host) is kind


# ── parsing: nothing is repaired ─────────────────────────────────────


def test_parse_normalises_scheme_host_and_default_ports() -> None:
    endpoint = parse_dicomweb_endpoint("HTTPS://PACS.Example.COM/dicom-web")
    assert (endpoint.scheme, endpoint.host, endpoint.port, endpoint.secure) == ("https", "pacs.example.com", 443, True)
    assert parse_dicomweb_endpoint("http://pacs.example.com").port == 80
    ipv6 = parse_dicomweb_endpoint("http://[::1]:8042/dicom-web")
    assert (ipv6.host, ipv6.port, ipv6.authority) == ("::1", 8042, "[::1]:8042")
    assert ipv6.transport is Transport.DICOMWEB


def test_verify_flag_only_means_something_for_tls() -> None:
    plain = parse_dicomweb_endpoint("http://127.0.0.1:8042", tls_verify=False)
    assert plain.verify is True  # normalised: plaintext has no peer to verify
    assert plain.flavour == "http"
    unverified = parse_dicomweb_endpoint("https://pacs.example.com", tls_verify=False)
    assert unverified.verify is False
    assert unverified.flavour == "https-unverified"
    assert parse_dicomweb_endpoint("https://pacs.example.com", tls_ca_path=" /etc/ca.pem ").ca_path == "/etc/ca.pem"


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("", "invalid-url"),
        ("   ", "invalid-url"),
        ("http://[::1", "invalid-url"),
        ("pacs.example.com:8042", "unsupported-scheme"),  # no scheme: not guessed into http://
        ("ftp://pacs.example.com/", "unsupported-scheme"),
        ("file:///etc/passwd", "unsupported-scheme"),
        ("dicom://pacs.example.com", "unsupported-scheme"),
        ("http://user:secret@127.0.0.1:8042/", "userinfo-in-url"),
        ("http://127.0.0.1@evil.example/", "userinfo-in-url"),  # looks like loopback, is not
        ("http://127.0.0.1:8042@evil.example/", "userinfo-in-url"),
        ("http://:8042/", "invalid-host"),
        ("http://0.0.0.0:8042/", "invalid-host"),
        ("http://[::]:8042/", "invalid-host"),
        ("http://exa mple.com/", "invalid-host"),
        ("http://pacs.example.com:99999/", "invalid-port"),
        ("http://pacs.example.com:0/", "invalid-port"),
        ("http://pacs.example.com:abc/", "invalid-port"),
    ],
)
def test_malformed_urls_are_rejected_with_a_stable_code(url: str, code: str) -> None:
    with pytest.raises(EndpointError) as excinfo:
        parse_dicomweb_endpoint(url)
    assert excinfo.value.code == code
    decision = evaluate_dicomweb_url(url)
    assert decision.blocked
    assert decision.code == "block-invalid-endpoint"
    assert decision.requires_exception is False  # no consent can make a malformed address valid
    assert [finding.code for finding in decision.findings] == [code]


def test_dimse_endpoint_validation() -> None:
    endpoint = dimse_endpoint(" PACS.Example.com ", 104, use_tls=True, tls_verify=True)
    assert (endpoint.transport, endpoint.scheme, endpoint.host, endpoint.port) == (
        Transport.DIMSE,
        "dimse-tls",
        "pacs.example.com",
        104,
    )
    assert dimse_endpoint("::1", 4242, use_tls=False).host == "::1"
    assert dimse_endpoint("[::1]", 4242, use_tls=False).host == "::1"
    for host, port, code in [
        ("", 104, "invalid-host"),
        ("0.0.0.0", 104, "invalid-host"),
        ("pacs", 0, "invalid-port"),
        ("pacs", 70000, "invalid-port"),
        ("pacs", "x", "invalid-port"),
    ]:
        with pytest.raises(EndpointError) as excinfo:
            dimse_endpoint(host, port, use_tls=False)  # type: ignore[arg-type]
        assert excinfo.value.code == code


# ── the policy table ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://pacs.example.com/dicom-web",
        "https://192.168.1.111:8042/dicom-web",
        "https://[2606:4700::1]/",
        "https://127.0.0.1:8043/",
    ],
)
def test_https_with_verification_is_allowed_everywhere(url: str) -> None:
    decision = evaluate_dicomweb_url(url, tls_verify=True)
    assert decision.allowed
    assert decision.code == "allow"
    assert decision.findings == ()
    assert decision.insecure is False


def test_custom_ca_bundle_is_the_supported_path_for_self_signed_pacs() -> None:
    decision = evaluate_dicomweb_url(
        "https://pacs.local:8443/dicom-web", tls_verify=True, tls_ca_path="/opt/pacs/ca.pem"
    )
    assert decision.allowed and decision.code == "allow"
    assert decision.endpoint is not None and decision.endpoint.ca_path == "/opt/pacs/ca.pem"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8042/dicom-web",
        "http://localhost:8042/dicom-web",
        "http://[::1]:8042/",
        "http://[::ffff:127.0.0.1]:8042/",
    ],
)
def test_plaintext_to_parsed_loopback_is_allowed_for_a_local_profile(url: str) -> None:
    decision = evaluate_dicomweb_url(url)
    assert decision.allowed
    assert decision.code == "allow-loopback"
    assert decision.insecure is False


def test_unverified_tls_to_loopback_is_also_the_local_profile() -> None:
    assert evaluate_dicomweb_url("https://127.0.0.1:8443/", tls_verify=False).code == "allow-loopback"


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.111:8042/dicom-web",  # the settings-dialog placeholder: RFC1918 is remote
        "http://10.0.0.5:8042/dicom-web",
        "http://172.16.0.1/dicom-web",
        "http://100.64.0.1:8042/",  # CGNAT
        "http://[fd12:3456::1]:8042/",  # ULA
        "http://[fe80::1%25eth0]:8042/",  # link-local
        "http://pacs.hospital.example/dicom-web",
        "http://8.8.8.8/",
        "http://localhost.attacker.example:8042/",
        "http://127.0.0.1.nip.io:8042/",
        "http://127.1:8042/",
        "http://0177.0.0.1:8042/",
        "http://2130706433:8042/",
    ],
)
def test_plaintext_to_anything_else_is_blocked_until_a_scoped_exception(url: str) -> None:
    decision = evaluate_dicomweb_url(url)
    assert decision.blocked
    assert decision.code == "block-plaintext-remote"
    assert decision.requires_exception is True
    assert [finding.code for finding in decision.findings] == ["plaintext-remote"]


def test_private_network_is_named_but_not_trusted() -> None:
    private = evaluate_dicomweb_url("http://192.168.1.111:8042/dicom-web")
    public = evaluate_dicomweb_url("http://pacs.hospital.example/dicom-web")
    assert private.blocked and public.blocked
    assert "private network" in private.findings[0].message
    assert "not evidence of trust" in private.findings[0].message


@pytest.mark.parametrize(
    "url", ["https://pacs.example.com/", "https://192.168.1.111:8042/", "https://localhost.attacker.example/"]
)
def test_disabled_verification_outside_loopback_is_blocked(url: str) -> None:
    decision = evaluate_dicomweb_url(url, tls_verify=False)
    assert decision.blocked
    assert decision.code == "block-tls-unverified"
    assert decision.requires_exception is True
    assert decision.findings[0].code == "tls-unverified"
    assert "CA bundle" in decision.findings[0].message


def test_dimse_policy_mirrors_dicomweb() -> None:
    assert evaluate_dimse("127.0.0.1", 4242, use_tls=False).code == "allow-loopback"
    assert evaluate_dimse("::1", 4242, use_tls=False).code == "allow-loopback"
    clear = evaluate_dimse("192.168.1.2", 4242, use_tls=False)
    assert clear.blocked and clear.code == "block-dimse-clear-remote" and clear.requires_exception
    assert clear.findings[0].code == "dimse-clear-remote"
    assert evaluate_dimse("pacs.example.com", 2762, use_tls=True, tls_verify=True).code == "allow"
    unverified = evaluate_dimse("pacs.example.com", 2762, use_tls=True, tls_verify=False)
    assert unverified.blocked and unverified.code == "block-tls-unverified"
    invalid = evaluate_dimse("", 104, use_tls=False)
    assert invalid.blocked and invalid.code == "block-invalid-endpoint" and not invalid.requires_exception


# ── scoped exceptions ────────────────────────────────────────────────


def test_a_scoped_exception_unblocks_exactly_one_insecure_endpoint_and_keeps_the_label() -> None:
    url = "http://192.168.1.111:8042/dicom-web"
    endpoint = parse_dicomweb_endpoint(url)
    exception = InsecureException.for_endpoint(endpoint)
    decision = evaluate_dicomweb_url(url, exceptions=[exception])
    assert decision.allowed
    assert decision.code == "allow-by-exception"
    assert decision.insecure is True  # persistent visible label
    assert [finding.code for finding in decision.findings] == ["plaintext-remote"]
    # Same authority, different path: the same endpoint.
    assert evaluate_dicomweb_url("http://192.168.1.111:8042/", exceptions=[exception]).allowed


@pytest.mark.parametrize(
    ("changed_url", "tls_verify", "reason"),
    [
        ("http://192.168.1.111:8043/dicom-web", True, "port changed"),
        ("http://192.168.1.112:8042/dicom-web", True, "host changed"),
        ("https://192.168.1.111:8042/dicom-web", False, "transport flavour changed: https without verification"),
        ("http://pacs.hospital.example:8042/dicom-web", True, "name instead of address"),
    ],
)
def test_a_changed_scope_invalidates_the_exception(changed_url: str, tls_verify: bool, reason: str) -> None:
    exception = InsecureException.for_endpoint(parse_dicomweb_endpoint("http://192.168.1.111:8042/dicom-web"))
    decision = evaluate_dicomweb_url(changed_url, tls_verify=tls_verify, exceptions=[exception])
    assert decision.blocked, reason
    assert decision.requires_exception, reason


def test_an_exception_does_not_cross_transports() -> None:
    http_exception = InsecureException.for_endpoint(parse_dicomweb_endpoint("http://192.168.1.111:4242/"))
    assert evaluate_dimse("192.168.1.111", 4242, use_tls=False, exceptions=[http_exception]).blocked
    dimse_exception = InsecureException.for_endpoint(dimse_endpoint("192.168.1.111", 4242, use_tls=False))
    assert (
        evaluate_dimse("192.168.1.111", 4242, use_tls=False, exceptions=[dimse_exception]).code == "allow-by-exception"
    )
    assert evaluate_dicomweb_url("http://192.168.1.111:4242/", exceptions=[dimse_exception]).blocked


def test_no_exception_can_unblock_a_malformed_endpoint() -> None:
    forged = InsecureException(Transport.DICOMWEB, "0.0.0.0", 8042, secure=False, verify=True)
    decision = evaluate_dicomweb_url("http://0.0.0.0:8042/", exceptions=[forged])
    assert decision.blocked and decision.code == "block-invalid-endpoint"
    unspecified = Endpoint(Transport.DICOMWEB, "http", "0.0.0.0", 8042, secure=False)
    assert evaluate_endpoint(unspecified, exceptions=[forged]).blocked


def test_there_is_no_global_http_allowed_switch() -> None:
    """An exception is a value with a concrete scope; a broad one cannot be expressed."""
    exception = InsecureException.for_endpoint(parse_dicomweb_endpoint("http://192.168.1.111:8042/"))
    others = [
        "http://192.168.1.1:8042/",
        "http://10.0.0.5:8042/",
        "http://pacs.example.com/",
        "http://192.168.1.111:80/",
    ]
    assert all(evaluate_dicomweb_url(url, exceptions=[exception]).blocked for url in others)


# ── redirects ────────────────────────────────────────────────────────


def test_https_to_http_redirect_is_a_downgrade_and_is_refused_even_with_an_exception() -> None:
    origin = "https://pacs.example.com/dicom-web/studies"
    exception = InsecureException.for_endpoint(parse_dicomweb_endpoint("http://pacs.example.com/"))
    decision = evaluate_redirect(origin, "http://pacs.example.com/dicom-web/studies", exceptions=[exception])
    assert decision.blocked
    assert decision.code == "block-redirect-downgrade"
    assert decision.requires_exception is False
    assert decision.forward_credentials is False
    assert decision.findings[0].code == "redirect-downgrade"


def test_same_authority_redirect_keeps_credentials() -> None:
    origin = "https://pacs.example.com/dicom-web/studies"
    for location in [
        "/dicom-web/studies/",
        "studies/",
        "https://pacs.example.com:443/dicom-web/studies/",
        "https://PACS.example.com/other",
    ]:
        decision = evaluate_redirect(origin, location)
        assert decision.allowed, location
        assert decision.code == "allow-redirect", location
        assert decision.forward_credentials is True, location


@pytest.mark.parametrize(
    "location",
    [
        "https://other.example.com/dicom-web/studies",  # other host
        "https://pacs.example.com:8443/dicom-web/studies",  # other port
        "//cdn.example.com/dicom-web/studies",  # scheme-relative
    ],
)
def test_cross_authority_redirect_withholds_credentials(location: str) -> None:
    decision = evaluate_redirect("https://pacs.example.com/dicom-web/studies", location)
    assert decision.allowed  # the destination itself is fine over verified TLS …
    assert decision.code == "allow-redirect-cross-authority"
    assert decision.forward_credentials is False  # … but auth / custom secret headers stay home
    assert decision.findings[-1].code == "redirect-cross-authority"


def test_loopback_trust_does_not_extend_to_a_remote_redirect() -> None:
    decision = evaluate_redirect("http://127.0.0.1:8042/dicom-web/studies", "http://192.168.1.5:8042/dicom-web/studies")
    assert decision.blocked
    assert decision.code == "block-plaintext-remote"
    assert decision.forward_credentials is False
    # Loopback → loopback on another port is a different authority: allowed, credentials withheld.
    local = evaluate_redirect("http://127.0.0.1:8042/dicom-web/studies", "http://127.0.0.1:8043/dicom-web/studies")
    assert local.allowed and local.code == "allow-redirect-cross-authority" and local.forward_credentials is False


def test_http_to_https_upgrade_redirect_is_allowed_but_is_another_authority() -> None:
    decision = evaluate_redirect("http://127.0.0.1:8042/dicom-web", "https://127.0.0.1:8443/dicom-web")
    assert decision.allowed and decision.forward_credentials is False


def test_redirect_to_an_unusable_location_is_blocked() -> None:
    origin = "https://pacs.example.com/dicom-web/studies"
    for location in [
        "http://user:pw@pacs.example.com/",
        "ftp://pacs.example.com/",
        "https://0.0.0.0/",
        "https://pacs.example.com:99999/",
    ]:
        decision = evaluate_redirect(origin, location)
        assert decision.blocked, location
        assert decision.code == "block-invalid-endpoint", location
    assert evaluate_redirect("not a url", "/x").code == "block-invalid-endpoint"


def test_remote_unverified_redirect_target_needs_its_own_exception() -> None:
    origin = "https://pacs.example.com/dicom-web/studies"
    blocked = evaluate_redirect(origin, "https://mirror.example.com/dicom-web/studies", tls_verify=False)
    assert blocked.blocked and blocked.code == "block-tls-unverified"
    target_exception = InsecureException.for_endpoint(
        parse_dicomweb_endpoint("https://mirror.example.com/", tls_verify=False)
    )
    allowed = evaluate_redirect(
        origin, "https://mirror.example.com/dicom-web/studies", tls_verify=False, exceptions=[target_exception]
    )
    assert allowed.allowed and allowed.insecure and allowed.forward_credentials is False


# ── overrides and whole profiles ─────────────────────────────────────


def test_profile_judges_the_stow_override_and_dimse_separately() -> None:
    profile = evaluate_profile(
        url="https://pacs.example.com/dicom-web",
        stow_url="http://192.168.1.50:8042/dicom-web",  # an insecure STOW override hides behind a secure QIDO root
        dimse_enabled=True,
        dimse_host="192.168.1.50",
        dimse_port=4242,
        dimse_use_tls=False,
    )
    assert not profile.allowed
    assert [decision.code for decision in profile.decisions] == [
        "allow",
        "block-plaintext-remote",
        "block-dimse-clear-remote",
    ]
    assert [decision.code for decision in profile.blocked] == ["block-plaintext-remote", "block-dimse-clear-remote"]
    assert profile.insecure is False  # nothing was *allowed* insecurely — it was blocked


def test_profile_with_exceptions_for_each_insecure_endpoint_is_allowed_and_labelled() -> None:
    stow = InsecureException.for_endpoint(parse_dicomweb_endpoint("http://192.168.1.50:8042/"))
    dimse = InsecureException.for_endpoint(dimse_endpoint("192.168.1.50", 4242, use_tls=False))
    profile = evaluate_profile(
        url="https://pacs.example.com/dicom-web",
        stow_url="http://192.168.1.50:8042/dicom-web",
        dimse_enabled=True,
        dimse_host="192.168.1.50",
        dimse_port=4242,
        dimse_use_tls=False,
        exceptions=[stow, dimse],
    )
    assert profile.allowed
    assert profile.insecure is True
    # The QIDO exception alone is not enough for the DIMSE association (scope is per transport).
    partial = evaluate_profile(
        url="https://pacs.example.com/dicom-web",
        stow_url="http://192.168.1.50:8042/dicom-web",
        dimse_enabled=True,
        dimse_host="192.168.1.50",
        dimse_port=4242,
        dimse_use_tls=False,
        exceptions=[stow],
    )
    assert not partial.allowed and [d.code for d in partial.blocked] == ["block-dimse-clear-remote"]


def test_local_dev_profile_keeps_working_without_any_exception() -> None:
    profile = evaluate_profile(
        url="http://127.0.0.1:8042/dicom-web",
        dimse_enabled=True,
        dimse_host="localhost",
        dimse_port=4242,
        dimse_use_tls=False,
    )
    assert profile.allowed
    assert [decision.code for decision in profile.decisions] == ["allow-loopback", "allow-loopback"]
    assert profile.insecure is False


def test_disabled_dimse_and_empty_stow_override_are_not_evaluated() -> None:
    profile = evaluate_profile(
        url="https://pacs.example.com/dicom-web", stow_url="   ", dimse_enabled=False, dimse_host="", dimse_port=0
    )
    assert profile.allowed and len(profile.decisions) == 1


# ── log safety and purity ────────────────────────────────────────────


def test_findings_and_summaries_never_carry_secrets_paths_or_query() -> None:
    url = "http://192.168.1.111:8042/dicom-web/studies?PatientName=Doe%5EJohn&StudyInstanceUID=1.2.3"
    decision = evaluate_dicomweb_url(url)
    text = " ".join([decision.summary(), *(f.message for f in decision.findings)])
    for secret in ("Doe", "PatientName", "1.2.3", "/dicom-web", "studies"):
        assert secret not in text
    assert "192.168.1.111" not in decision.summary()  # summary is host-kind only
    rejected = evaluate_dicomweb_url("http://admin:hunter2@192.168.1.111:8042/dicom-web")
    assert "hunter2" not in " ".join(f.message for f in rejected.findings)
    assert "admin" not in " ".join(f.message for f in rejected.findings)


def test_decisions_are_immutable_values() -> None:
    decision = evaluate_dicomweb_url("http://127.0.0.1:8042/")
    with pytest.raises(AttributeError):
        decision.verdict = Verdict.BLOCK  # type: ignore[misc]
    assert isinstance(decision, Decision)


def test_the_evaluator_is_pure_stdlib() -> None:
    """No Qt, no settings store, no HTTP/DIMSE client: the decision layer stays testable and layering-safe."""
    source = Path(policy.__file__).read_text(encoding="utf-8")
    for name in (
        "PySide6",
        "httpx",
        "pynetdicom",
        "echo_personal_tool.infrastructure",
        "echo_personal_tool.presentation",
    ):
        assert f"import {name}" not in source
        assert f"from {name}" not in source
