"""Storage boundary validation for structured research IMT records."""

from __future__ import annotations

from echo_personal_tool.domain.models.imt import ImtDraft, ImtRefusal
from echo_personal_tool.domain.services.imt_validation import MAX_IMT_MEASUREMENTS, imt_key, validate_imt


def validate_imt_storage(entries: tuple[ImtDraft, ...], sources: dict) -> None:
    if len(entries) > MAX_IMT_MEASUREMENTS:
        raise ImtRefusal("limit")
    seen = set()
    for draft in entries:
        source = draft.source
        descriptor = sources.get(source.instance_uid)
        if descriptor is None or descriptor["frames"] != source.frame_count:
            raise ImtRefusal("source")
        if imt_key(draft) in seen:
            raise ImtRefusal("invalid")
        seen.add(imt_key(draft))
        try:
            validate_imt(draft)
        except ImtRefusal as exc:
            raise ImtRefusal("invalid") from exc
