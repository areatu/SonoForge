"""HTTPS client for FHIR R4 Bundle exchange (#625).

Infrastructure adapter for :class:`~echo_personal_tool.domain.ports.FhirHttpPort`.
POSTs a Bundle to the configured FHIR base URL (``…/Bundle``), Basic or
Bearer auth from the portable credential store, TLS judged by
:mod:`application.transport_policy` (DICOMweb/https kind).  Bundle payloads
carry PHI, so nothing but the status code is ever logged.
"""

from __future__ import annotations

import ssl
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from echo_personal_tool.application.transport_policy import (
    InsecureException,
    TransportPolicyError,
    Verdict,
    evaluate_dicomweb_url,
)
from echo_personal_tool.domain.exceptions import InteropError

#: Cap on the response body we are willing to read (FHIR errors are small).
MAX_RESPONSE_BYTES = 256 * 1024


@dataclass(frozen=True)
class FhirPostResult:
    """Outcome of one Bundle POST (no PHI, no credentials)."""

    status_code: int
    accepted: bool
    response_excerpt: str = ""  # first bytes of the body, truncated, for the status line


class FhirHttpsClient:
    """POST FHIR R4 Bundles over HTTPS with policy-checked TLS."""

    def __init__(
        self,
        *,
        base_url: str,
        username: str = "",
        password: str = "",
        bearer_token: str = "",
        timeout_s: float = 30.0,
        tls_verify: bool = True,
        tls_ca_path: str = "",
        exceptions: Iterable[InsecureException] = (),
    ) -> None:
        decision = evaluate_dicomweb_url(
            base_url,
            tls_verify=tls_verify,
            tls_ca_path=tls_ca_path,
            exceptions=exceptions,
        )
        if decision.verdict is not Verdict.ALLOW:
            raise TransportPolicyError(decision)
        if not base_url.rstrip("/").lower().endswith("/fhir") and not base_url.rstrip("/").endswith("/Bundle"):
            base_url = base_url.rstrip("/") + "/Bundle"
        self._url = base_url
        self._timeout_s = max(1.0, float(timeout_s))
        self._tls_verify = tls_verify
        self._tls_ca_path = tls_ca_path
        self._auth = httpx.BasicAuth(username, password) if username else None
        self._bearer = bearer_token or ""
        self._insecure = decision.insecure

    @property
    def url(self) -> str:
        return self._url

    @property
    def insecure(self) -> bool:
        return self._insecure

    def _client(self) -> httpx.Client:
        if not self._tls_verify:
            # Unreachable in practice: the transport policy blocks tls_verify=False at construction.
            raise InteropError("tls_verification_disabled")
        headers = {"Accept": "application/fhir+json", "Content-Type": "application/fhir+json"}
        if self._bearer:
            headers["Authorization"] = f"Bearer {self._bearer}"
        # Always a verifying SSLContext (default CAs, optionally plus a local CA bundle).
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if self._tls_ca_path:
            context.load_verify_locations(cafile=self._tls_ca_path)
        transport = httpx.HTTPTransport(verify=context)
        return httpx.Client(
            timeout=self._timeout_s,
            transport=transport,
            auth=self._auth,
            headers=headers,
            follow_redirects=False,
        )

    def post_bundle(self, bundle_json: bytes) -> FhirPostResult:
        """POST one Bundle; 2xx means accepted. Raises :class:`InteropError` on transport failure."""
        if not isinstance(bundle_json, (bytes, bytearray)) or not bundle_json:
            raise InteropError("invalid_payload")
        try:
            with self._client() as client:
                response = client.post(self._url, content=bytes(bundle_json))
        except httpx.HTTPError as exc:
            raise InteropError("transport") from exc
        excerpt = response.text[:200].replace("\n", " ")
        return FhirPostResult(
            status_code=response.status_code,
            accepted=200 <= response.status_code < 300,
            response_excerpt=excerpt,
        )


def post_bundle_once(payload: bytes, **kwargs: Any) -> FhirPostResult:
    """Convenience one-shot POST used by the application facade and tests."""
    return FhirHttpsClient(**kwargs).post_bundle(payload)
