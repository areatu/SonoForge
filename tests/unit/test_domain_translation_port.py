"""The domain translation port delegates without depending on infrastructure."""

from __future__ import annotations


def test_domain_translation_port_uses_registered_adapter() -> None:
    from echo_personal_tool.domain.translation import register_translator, tr
    from echo_personal_tool.infrastructure.i18n import tr as infrastructure_tr

    calls: list[tuple[str, dict[str, object]]] = []

    def adapter(key: str, **kwargs: object) -> str:
        calls.append((key, kwargs))
        return f"translated:{key}:{kwargs['count']}"

    try:
        register_translator(adapter)
        assert tr("domain.planimeter.area_label", count="3") == "translated:domain.planimeter.area_label:3"
        assert calls == [("domain.planimeter.area_label", {"count": "3"})]
    finally:
        # Do not leak the test adapter into other tests in this process.
        register_translator(infrastructure_tr)
