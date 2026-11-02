"""The domain translation port delegates without depending on infrastructure."""

from __future__ import annotations


def test_domain_translation_port_uses_registered_adapter() -> None:
    from echo_personal_tool.domain.translation import get_language, register_translator, tr, tr_for_language, tr_plural
    from echo_personal_tool.infrastructure.i18n import tr as infrastructure_tr

    calls: list[tuple[str, dict[str, object]]] = []

    def adapter(key: str, **kwargs: object) -> str:
        calls.append((key, kwargs))
        return f"translated:{key}:{kwargs['count']}"

    def explicit_adapter(key: str, language: str, **_kwargs: object) -> str:
        return f"{language}:{key}"

    def plural_adapter(key: str, count: int | float, **_kwargs: object) -> str:
        return f"{key}:{count}"

    try:
        register_translator(
            adapter,
            translate_for_language=explicit_adapter,
            translate_plural=plural_adapter,
            get_language=lambda: "test",
        )
        assert tr("domain.planimeter.area_label", count="3") == "translated:domain.planimeter.area_label:3"
        assert tr_for_language("label", "ru") == "ru:label"
        assert tr_plural("items", 4) == "items:4"
        assert get_language() == "test"
        assert calls == [("domain.planimeter.area_label", {"count": "3"})]
    finally:
        # Do not leak the test adapter into other tests in this process.
        from echo_personal_tool.infrastructure.i18n import get_language, tr_for_language, tr_plural

        register_translator(
            infrastructure_tr,
            translate_for_language=tr_for_language,
            translate_plural=tr_plural,
            get_language=get_language,
        )
