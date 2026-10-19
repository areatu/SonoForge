"""UI-5 PR-1 — модель карточки нормы S2 (спека UI §4.7, §8.5).

Карточка открывается у строки измерения и показывает значение, градацию,
норму для пола пациента, шкалу градаций, «как измерять» и источник.
Рисунков в карточке нет (UD-06): они остаются в окне справочника S1, поэтому
в модели нет ни пути к изображению, ни самого изображения.

Градация считается **здесь**, в домене: виджет получает готовую
:class:`ReferenceCardModel` и только показывает её. Правила:

* норма и градации берутся из справочника (:mod:`reference_data_store`) для
  пола пациента; пол понимается так же, как в отчёте (:func:`is_female`);
* у параметра может не быть градаций — тогда шкала пуста, а карточка
  показывает только норму. Нет и нормы — карточка говорит об этом
  («Нормы нет в справочнике») и не красит значение;
* значения модели — в **показываемых** единицах (в тех же, что число у строки),
  а не в единицах справочника: перевод делает :data:`_UNIT_SCALE`-таблица
  отчёта, чтобы вызывающая сторона не думала о единицах справочника;
* поле ``how_to`` (UI-5 PR-3, UQ-12) необязательное; пока в справочнике нет
  инструкций для параметра, блок «как измерять» пуст и в карточке не показывается.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from echo_personal_tool.domain.services.reference_data_store import (
    NormRange,
    ParameterRef,
    ReferenceDataStore,
)
from echo_personal_tool.domain.services.report_builder import (
    format_norm,
    is_female,
    is_male,
    reference_unit_scale,
)
from echo_personal_tool.infrastructure.i18n import get_language, tr_for_language

__all__ = [
    "GradeCut",
    "ReferenceCardModel",
    "build_reference_card",
    "clear_cache",
    "find_parameter",
]

_UNKNOWN_TEXT = "—"


def _number(value: float) -> str:
    """A number without a useless tail: 48, 2.8, 0.42."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True)
class GradeCut:
    """One gradation of the handbook for one sex, in the displayed unit.

    ``low`` / ``high`` are closed bounds; ``None`` means the side is open
    («Тяжёлое ≥ 211 г» has ``low=211`` and ``high=None``).
    """

    name: str = ""
    low: float | None = None
    high: float | None = None

    def contains(self, value: float) -> bool:
        if self.low is not None and value < self.low:
            return False
        if self.high is not None and value > self.high:
            return False
        return True

    def range_text(self) -> str:
        if self.low is not None and self.high is not None:
            return f"{_number(self.low)}–{_number(self.high)}"
        if self.high is not None:
            return f"≤{_number(self.high)}"
        if self.low is not None:
            return f"≥{_number(self.low)}"
        return ""


@dataclass(frozen=True)
class ReferenceCardModel:
    """Everything the S2 card shows; the widget adds nothing of its own.

    ``known`` is ``False`` when the handbook has no such parameter: the card
    then says so instead of inventing a range. ``has_norm`` is ``False`` when
    the parameter exists but carries no range for the patient — same message,
    but the label, the source and «открыть в справочнике» still work.
    """

    param_id: str = ""
    #: Short label of the row (catalog label, then the name in the handbook).
    label: str = ""
    #: Full name under the header (catalog label, then the handbook).
    full_name: str = ""
    #: The measured number in the displayed unit; ``None`` — not measured.
    value: float | None = None
    #: The number as the row shows it («48 мм»); empty when there is no value.
    value_text: str = ""
    unit: str = ""
    #: Raw DICOM-ish sex of the patient (``""`` when unknown).
    sex: str = ""
    #: «женщины» / «мужчины» / ``""`` — only when the sex is known.
    sex_label: str = ""
    #: The gradation the value falls into; ``None`` — outside the scale.
    grade: GradeCut | None = None
    #: The norm of the parameter for the patient's sex, in the displayed unit.
    norm: NormRange | None = None
    #: The norm as text («36–51 мм»), ready to show.
    norm_text: str = ""
    #: Segments of the scale, in handbook order, in the displayed unit.
    cuts: tuple[GradeCut, ...] = ()
    #: Steps of «как измерять» (UQ-12, UI-5 PR-3); empty — the block is hidden.
    how_to: tuple[str, ...] = ()
    #: «ASE/EACVI 2015 · количественная оценка камер».
    source: str = ""
    #: Method the ranges belong to («М-режим») — shown next to the norm.
    method: str = ""
    language: str = "ru"

    @property
    def known(self) -> bool:
        """Whether the handbook has the parameter at all."""
        return bool(self.param_id) and (self.norm is not None or bool(self.cuts) or bool(self.source))

    @property
    def has_norm(self) -> bool:
        """Whether there is a range to compare the value with."""
        return self.norm is not None


@lru_cache(maxsize=4)
def _store(language: str):
    """The parsed handbook of one language (never raises)."""
    try:
        return ReferenceDataStore(language="ru" if language == "ru" else "en").load()
    except Exception:  # noqa: BLE001 — a broken handbook must not break the card
        return None


def clear_cache() -> None:
    """Forget the parsed handbook (after the constructor saved it)."""
    _store.cache_clear()


def find_parameter(param_id: str, language: str | None = None) -> ParameterRef | None:
    """The handbook parameter with this id, or ``None``."""
    if not param_id:
        return None
    store = _store(_language(language))
    if store is None:
        return None
    for _topic, _pathology, _gradation, param in store.search(param_id):
        if param.id == param_id:
            return param
    return None


def _language(language: str | None) -> str:
    return (language or get_language() or "en").strip().lower()[:2] or "en"


def _pick(param: ParameterRef, female: bool) -> NormRange | None:
    """The range of one sex, falling back to the other when it is missing."""
    primary = param.norm_female if female else param.norm_male
    if primary is not None:
        return primary
    return param.norm_male if female else param.norm_female


def _how_to(param: ParameterRef, language: str) -> tuple[str, ...]:
    """Steps of «как измерять» (UQ-12).

    The structured schema and constructor use a
    ``{ru: [...], en: [...]}`` mapping. List and string forms remain accepted
    for older or programmatically generated reference data.
    """
    raw = getattr(param, "how_to", None)
    if not raw:
        return ()
    if isinstance(raw, dict):
        raw = raw.get(language) or raw.get("en") or raw.get("ru")
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, (list, tuple)):
        return tuple(str(item) for item in raw if item)
    return ()


def _to_display(value: float | None, scale: float) -> float | None:
    """Reference unit → the unit the row shows (``scale`` is app → reference)."""
    if value is None or not scale:
        return value
    return value / scale


def _format_value(value: float, decimals: int | None) -> str:
    """The number of a row: as short as it can be, unless the caller rounds.

    ``decimals=None`` decides by magnitude (48, 12.5, 0.42, 1234); an explicit
    count is a request of the row and is honoured as it is.
    """
    if decimals is None:
        decimals = 0 if abs(value) >= 100 else (1 if abs(value) >= 10 else 2)
        text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
        return text or "0"
    return f"{value:.{decimals}f}"


def build_reference_card(
    param_id: str,
    *,
    value: float | None = None,
    unit: str = "",
    sex: str = "",
    language: str | None = None,
    label: str | None = None,
    full_name: str | None = None,
    value_text: str | None = None,
    decimals: int | None = None,
    scale: float | None = None,
) -> ReferenceCardModel:
    """Build the S2 model of one handbook parameter.

    ``param_id`` is the id in the structured handbook (``lvedd``, ``lvm`` …).
    ``value`` reads in the unit ``unit`` — the unit of the row, which for a few
    parameters differs from the unit of the handbook; the conversion is taken
    from the report's table unless the caller passes ``scale`` (``1.0`` when
    the value already reads in reference units).

    The card is built even when the handbook has nothing: the row then shows
    «Нормы нет в справочнике» instead of a guess.
    """
    lang = _language(language)
    param = find_parameter(param_id, lang)
    text_value = (
        value_text
        if value_text is not None
        else (f"{_format_value(value, decimals)} {unit}".strip() if value is not None else "")
    )
    if param is None:
        return ReferenceCardModel(
            param_id=param_id or "",
            label=label or param_id or "",
            full_name=full_name or "",
            value=value,
            value_text=text_value,
            unit=unit,
            sex=sex,
            language=lang,
        )

    female = is_female(sex)
    known_sex = female or is_male(sex)
    factor = reference_unit_scale(param_id) if scale is None else scale

    norm_ref = _pick(param, female)
    norm = (
        NormRange(low=_to_display(norm_ref.low, factor), high=_to_display(norm_ref.high, factor))
        if norm_ref is not None
        else None
    )
    norm_text = format_norm(norm) if norm is not None else ""

    cuts: list[GradeCut] = []
    for gradation in param.gradations:
        ref_range = (gradation.range_female if female else gradation.range_male) or gradation.range_male
        if ref_range is None:
            continue
        cuts.append(
            GradeCut(
                name=gradation.name,
                low=_to_display(ref_range.low, factor),
                high=_to_display(ref_range.high, factor),
            )
        )
    grade = next((cut for cut in cuts if value is not None and cut.contains(value)), None)

    return ReferenceCardModel(
        param_id=param.id,
        label=label or param.name or param.id,
        full_name=full_name or (param.full_name or ""),
        value=value,
        value_text=text_value,
        unit=unit or (param.unit or ""),
        sex=sex,
        sex_label=(
            tr_for_language("ref_card.sex_female" if female else "ref_card.sex_male", lang) if known_sex else ""
        ),
        grade=grade,
        norm=norm,
        norm_text=norm_text,
        cuts=tuple(cuts),
        how_to=_how_to(param, lang),
        source=param.source or "",
        method=param.method or "",
        language=lang,
    )
