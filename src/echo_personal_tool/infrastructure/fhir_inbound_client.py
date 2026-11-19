"""FHIR R4 inbound poll client (#626).

GETs ServiceRequest / Patient / DiagnosticReport bundles from a configured
FHIR endpoint through the transport policy (https, verified TLS, no
redirects) and hands the parsed Bundle to the application facade. Credentials
go as Basic/Bearer headers only, never in the URL; payloads are never logged.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from echo_personal_tool.domain.exceptions import InteropError, TransportPolicyError

#: Judged by the application facade (``evaluate_dicomweb_url``); injected so
#: this module never imports the application layer.
UrlGuard = Callable[[str, bool, str], object]


class FhirInboundClient:
    """Policy-checked HTTPS GET poll for inbound FHIR resources."""

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
        url_guard: UrlGuard | None = None,
    ) -> None:
        if url_guard is not None:
            from echo_personal_tool.domain.services.listener_policy import Verdict

            decision = url_guard(base_url, tls_verify, tls_ca_path)
            verdict = getattr(decision, "verdict", None)
            if verdict is not None and verdict is not Verdict.ALLOW:
                raise TransportPolicyError(decision)
        if not tls_verify:
            raise InteropError("tls_verification_disabled")
        self._base = base_url.rstrip("/")
        self._timeout_s = max(1.0, float(timeout_s))
        self._auth = httpx.BasicAuth(username, password) if username else None
        self._bearer = bearer_token or ""
        self._tls_ca_path = tls_ca_path

    def _client(self) -> httpx.Client:
        import ssl

        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if self._tls_ca_path:
            context.load_verify_locations(cafile=self._tls_ca_path)
        headers = {"Accept": "application/fhir+json"}
        if self._bearer:
            headers["Authorization"] = f"Bearer {self._bearer}"
        transport = httpx.HTTPTransport(verify=context)
        return httpx.Client(
            timeout=self._timeout_s,
            transport=transport,
            auth=self._auth,
            headers=headers,
            follow_redirects=False,
        )

    def fetch_bundle(self, resource_type: str, *, query: str = "") -> dict[str, Any]:
        """GET ``<base>/<resource_type>?<query>`` and return the parsed Bundle."""
        url = f"{self._base}/{resource_type.lstrip('/')}"
        if query:
            url = f"{url}?{query.lstrip('?')}"
        try:
            with self._client() as client:
                response = client.get(url)
        except httpx.HTTPError as exc:
            raise InteropError("transport") from exc
        if response.status_code != 200:
            raise InteropError("http_status")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("resourceType") != "Bundle":
            raise InteropError("not_a_bundle")
        return payload

    def fetch_all(self, *, patient: str = "") -> dict[str, Any]:
        """Fetch ServiceRequest (+Patient/DiagnosticReport when a patient is given) as one Bundle."""
        entries: list[dict[str, Any]] = []
        service_query = "status=active" + (f"&patient={patient}" if patient else "")
        for resource_type, query in (
            ("ServiceRequest", service_query),
            ("Patient", f"_id={patient}" if patient else ""),
            ("DiagnosticReport", f"patient={patient}" if patient else ""),
        ):
            try:
                bundle = self.fetch_bundle(resource_type, query=query)
            except InteropError:
                continue  # a missing optional resource class is not fatal
            entries.extend(entry for entry in bundle.get("entry", []) if isinstance(entry, dict))
        return {"resourceType": "Bundle", "type": "collection", "entry": entries}
