"""S1 view model of the reference window (UI-5 PR-2, spec §4.7, §8.5).

The window of the handbook shows a whole topic: its pathologies, the norm of the
patient's sex, the gradation columns and — when the measurement of the open
study matches a slot of the handbook — the patient's value with its grade.  The
model is built here, without Qt, from the same :class:`ReferenceDataStore` the
constructor edits and from the same :func:`build_reference_card` the S2 card
uses, so the window can never disagree with the card or the report about a norm.

Two deliberate conventions:

* the row keeps the *handbook* id (``lvedd``, not ``lv.lvedd``): that is the
  identifier of the YAML, the schema and the constructor.  The projection of the
  study speaks in catalogue ids, so :func:`reference_values` translates the keys
  it knows and drops the rest — a value in another unit is not a value;
* a missing norm is not an error: the row says «Нормы нет в справочнике» and
  shows no grade, exactly like the card (UD-14: no inventing a «borderline»
  grade).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache

from echo_personal_tool.domain.services.reference_card import (
    GradeCut,
    build_reference_card,
)
from echo_personal_tool.domain.services.reference_data_store import (
    ParameterRef,
    PathologyRef,
    ReferenceDataStore,
    TopicRef,
)

#: Projection key of the study → handbook id, only where the units agree.
#:
#: The projection speaks catalogue ids (``lv.lvedd``, TP-3 PR-2b) and the
#: handbook speaks its own (``lvedd``).  Only the family whose units coincide is
#: translated: lengths in millimetres, mass in grams, the relative wall
#: thickness (a ratio), the mass index in g/m², the ejection fraction in %,
#: the indexed volumes in mL/m², areas in cm², pressures in mmHg, times in ms
#: and the absolute LA/RA volumes in mL (the handbook carries those absolute;
#: absolute **LV** volumes stay out — the handbook indexes LV volumes by body
#: surface area (``lvedvi``), and an indexed norm must not meet an absolute
#: volume).
#:
#: The TDI velocities join because their unit is the same in the projection and
#: in the handbook (``e_prime_sept`` in cm/s against «см/с»).  The jet
#: velocities (``tr.vmax``, ``av.vmax`` …) stay out: the handbook stores m/s
#: while the projection speaks the report's cm/s and this translation compares
#: without conversion.  A key whose unit is still unsettled is dropped, not
#: guessed.
PROJECTION_TO_HANDBOOK: Mapping[str, str] = {
    "lv.lvedd": "lvedd",
    "lv.lvesd": "lvesd",
    "lv.ivsd": "ivsd",
    "lv.lvpwd": "lvpwd",
    "lv.mass": "lvm",
    "lv.mass_i": "lvmi_hyp",
    "lv.rwt": "rwt_hyp",
    "lv.ef_bp": "lvef",
    "lv.edvi": "lvedvi",
    "lv.edvi_a4c": "lvedvi",
    "lv.edvi_a2c": "lvedvi",
    "lv.edvi_bp": "lvedvi",
    "lv.esvi": "lvesvi",
    "lv.esvi_a4c": "lvesvi",
    "lv.esvi_a2c": "lvesvi",
    "lv.esvi_bp": "lvesvi",
    "lv.svi": "svi",
    "lv.ivrt": "ivrt",
    "lv.gls": "gls",
    "lv.gls_a4c": "gls",
    "lv.gls_a2c": "gls",
    "la.ap": "la_antpost",
    "la.lav_a4c": "lav",
    "la.lav_a2c": "lav",
    "la.lav_bp": "lav",
    "la.lavi": "lavi",
    "la.lavi_a4c": "lavi",
    "la.lavi_bp": "lavi",
    "ra.vol": "ra_volume",
    "ra.area": "ra_area",
    "ra.rap": "rap",
    "rv.basal": "rvd1",
    "rv.mid": "rvd2",
    "rv.rvot_prox": "pa_rvot",
    "rv.tapse": "tapss",
    "rv.s_prime": "s_prime_rv",
    "rv.fac": "fac_rv",
    "tdi.e_sept": "e_prime_sept",
    "tdi.e_lat": "e_prime_lat",
    "mv.e_e_avg": "e_e_prime_avg",
    "mv.pht": "ms_pht",
    "mr.dpdt": "lv_dpdt",
    "av.ava_vti": "as_ava",
    "av.avai": "as_ava_indexed",
    "ar.pht": "ar_pht",
    "tv.pht": "ts_pht",
    "tr.dpdt": "rv_dpdt",
    "pr.pht": "pr_pht",
    "pa.pasp": "spap",
    "pa.mpap": "mpap",
    "ao.sinus": "asc_aorta",
    "ao.stj": "sinotubular",
    "ao.asc": "ascending_aorta",
}

#: The three states of the sex switch of the window (spec §4.7: «по пациенту»).
SEX_BOTH = ""
SEX_MALE = "male"
SEX_FEMALE = "female"

#: Gradation names are data of the handbook and differ in gender across topics
#: («Лёгкое» in the LV sizes, «Лёгкая» in the regurgitation of the valves).  One
#: column per *meaning* keeps the table at the four columns of the mockup.
_GRADE_STEMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("normal", ("норм", "normal")),
    ("mild", ("лёгк", "легк", "mild")),
    ("moderate", ("умерен", "moderate")),
    ("severe", ("тяжёл", "тяжел", "severe")),
)


def gradation_key(name: str) -> str:
    """Stable key of a gradation name: ``normal`` / ``mild`` / … or the name."""
    lowered = (name or "").strip().lower()
    for key, stems in _GRADE_STEMS:
        if any(stem in lowered for stem in stems):
            return key
    return lowered


def chip_label(pathology_name: str, topic_name: str) -> str:
    """Short caption of a pathology chip («Размеры», «Фракция выброса»).

    The handbook names the pathology in full («Размеры левого желудочка»), the
    chips of the mockup carry only the distinguishing part: the topic is already
    the title of the page.  Trailing words are dropped only while they belong to
    the topic — the stem of its last word and the «левого/правого» of the
    chambers — so an unrelated pathology keeps its full name.
    """
    stem = topic_name.split()[-1][:4].lower() if topic_name.split() else ""
    words = pathology_name.split()
    while words:
        last = words[-1].lower().strip(",.")
        if last in ("левого", "правого", "левой", "правой") or (stem and last.startswith(stem)):
            words.pop()
            continue
        break
    return " ".join(words).strip(" ,") or pathology_name


def gradation_rank(name: str) -> int:
    """Sort order of the columns: normal → mild → moderate → severe → others."""
    key = gradation_key(name)
    for rank, (known, _stems) in enumerate(_GRADE_STEMS):
        if key == known:
            return rank
    return len(_GRADE_STEMS)


@dataclass(frozen=True)
class TopicEntry:
    """One row of the left navigation: a topic and how much it holds."""

    slug: str
    name: str
    parameter_count: int
    pathology_count: int


@dataclass(frozen=True)
class ReferenceRow:
    """One parameter of a topic, ready to be shown in the S1 table."""

    param_id: str
    name: str
    full_name: str
    unit: str
    norm_text: str
    gradation_texts: tuple[str, ...]
    value: float | None = None
    value_text: str = ""
    grade: str = ""
    how_to: tuple[str, ...] = ()
    source: str = ""
    method: str = ""
    topic_slug: str = ""
    topic_name: str = ""
    pathology_name: str = ""
    description: str = ""
    image_paths: tuple[str, ...] = ()

    @property
    def tooltip(self) -> str:
        """The full name of the parameter, as the card and the table hint show it."""
        return self.full_name or self.name


@dataclass(frozen=True)
class TopicView:
    """What the centre of the window shows: a topic, or the search results."""

    slug: str
    name: str
    rows: tuple[ReferenceRow, ...] = ()
    #: Gradation column names in order of appearance (``Норма``, ``Лёгкое`` …).
    columns: tuple[str, ...] = ()
    #: ``False`` for the search results — there the table carries a topic column.
    is_topic: bool = True

    @property
    def pathology_names(self) -> tuple[str, ...]:
        """Distinct pathologies of the rows, in order of appearance."""
        seen: list[str] = []
        for row in self.rows:
            if row.pathology_name and row.pathology_name not in seen:
                seen.append(row.pathology_name)
        return tuple(seen)


def _unique_parameters(topic: TopicRef) -> list[ParameterRef]:
    """Parameters of a topic, one per id, in the order the handbook lists them.

    A parameter may sit in several pathologies or in several gradations of one
    pathology (``_flatten_gradation_parameters`` of the old widget did the same);
    the window shows it once, under the first pathology that names it.
    """
    seen: dict[str, ParameterRef] = {}
    for pathology in topic.pathologies:
        for param in _parameters_of(pathology):
            seen.setdefault(param.id, param)
    return list(seen.values())


def _parameters_of(pathology: PathologyRef) -> Iterable[ParameterRef]:
    """Parameters of one pathology, plain or spread over its gradations."""
    if pathology.parameters:
        yield from pathology.parameters
    for gradation in pathology.gradations or ():
        yield from gradation.parameters


def _fmt_number(value: float | None) -> str:
    """A bound as the table prints it: no trailing zeros, no fake precision."""
    if value is None:
        return ""
    decimals = 0 if abs(value) >= 100 else (1 if abs(value) >= 10 else 2)
    text = f"{value:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_cut(cut: GradeCut) -> str:
    """«36–51», «≥ 52», «≤ 35» — closed bounds of one gradation (UD-14)."""
    low = _fmt_number(cut.low)
    high = _fmt_number(cut.high)
    if low and high:
        return f"{low}–{high}"
    if low:
        return f"≥ {low}"
    if high:
        return f"≤ {high}"
    return ""


def _cuts_for(param_id: str, sex: str, language: str | None) -> tuple[GradeCut, ...]:
    return build_reference_card(param_id, sex=sex, language=language).cuts


def _norm_text(param_id: str, sex: str, language: str | None) -> str:
    """The norm of the chosen sex; «оба» joins the sexes when they differ.

    An unknown sex (``SEX_BOTH``) with equal ranges shows one range, not the
    same number twice; different ranges are joined «мужская / женская» in the
    order the columns of the table use.  The header of the table says which
    order that is.
    """
    if sex in (SEX_MALE, SEX_FEMALE):
        return build_reference_card(param_id, sex=sex, language=language).norm_text
    male = build_reference_card(param_id, sex=SEX_MALE, language=language).norm_text
    female = build_reference_card(param_id, sex=SEX_FEMALE, language=language).norm_text
    if male and female and male != female:
        return f"{male} / {female}"
    return male or female


def _gradation_texts(param_id: str, sex: str, columns: tuple[str, ...], language: str | None) -> tuple[str, ...]:
    """Texts of the row's gradations, aligned with ``columns`` (empty when absent).

    ``columns`` holds display names whose :func:`gradation_key` is unique, so
    «Лёгкое» and «Лёгкая» of two pathologies of one topic fill the same cell.
    """

    def texts(side: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for cut in _cuts_for(param_id, side, language):
            found.setdefault(gradation_key(cut.name), format_cut(cut))
        return found

    if sex in (SEX_MALE, SEX_FEMALE):
        by_key = texts(sex)
        return tuple(by_key.get(gradation_key(name), "") for name in columns)
    male, female = texts(SEX_MALE), texts(SEX_FEMALE)
    cells: list[str] = []
    for name in columns:
        key = gradation_key(name)
        first, second = male.get(key, ""), female.get(key, "")
        cells.append(f"{first} / {second}" if first and second and first != second else (first or second))
    return tuple(cells)


def _columns_of(hosts: Iterable[ParameterRef], sex: str, language: str | None) -> tuple[str, ...]:
    """Gradation columns of a view, in order of appearance across its rows."""
    columns: list[str] = []
    seen: set[str] = set()
    for host in hosts:
        cut_sex = sex if sex in (SEX_MALE, SEX_FEMALE) else SEX_MALE
        for cut in _cuts_for(host.id, cut_sex, language):
            key = gradation_key(cut.name)
            if key not in seen:
                seen.add(key)
                columns.append(cut.name)
    return tuple(sorted(columns, key=gradation_rank))


def reference_values(projection_values: Mapping[str, float] | None) -> dict[str, float]:
    """Translate the values of the study projection into handbook ids.

    Unknown keys are dropped rather than guessed: a value the handbook has no
    row for would have no norm to compare with.
    """
    if not projection_values:
        return {}
    return {
        handbook_id: float(value)
        for key, value in projection_values.items()
        if (handbook_id := PROJECTION_TO_HANDBOOK.get(key)) is not None and value is not None
    }


def _row(
    param: ParameterRef,
    *,
    topic: TopicRef,
    pathology: PathologyRef,
    columns: tuple[str, ...],
    sex: str,
    value: float | None,
    language: str | None,
) -> ReferenceRow:
    card = build_reference_card(
        param.id,
        value=value,
        unit=param.unit,
        sex=sex,
        language=language,
        label=param.name,
        full_name=param.full_name,
    )
    grade = card.grade.name if card.grade is not None else ""
    return ReferenceRow(
        param_id=param.id,
        name=param.name,
        full_name=param.full_name or param.name,
        unit=param.unit or "",
        norm_text=_norm_text(param.id, sex, language),
        gradation_texts=_gradation_texts(param.id, sex, columns, language),
        value=value,
        value_text=card.value_text,
        grade=grade,
        how_to=card.how_to,
        source=param.source or "",
        method=param.method or "",
        topic_slug=topic.slug,
        topic_name=topic.name,
        pathology_name=pathology.name,
        description=pathology.description or "",
        image_paths=tuple(pathology.image_paths),
    )


def _language(language: str | None) -> str:
    """Two-letter code of the interface language, the way the card reads it."""
    from echo_personal_tool.infrastructure.i18n import get_language

    return (language or get_language() or "en").strip().lower()[:2] or "en"


@lru_cache(maxsize=4)
def _cached_store(language: str) -> ReferenceDataStore | None:
    """The parsed handbook of one language, cached like the card's own copy."""
    try:
        return ReferenceDataStore(language="ru" if language == "ru" else "en").load()
    except Exception:  # noqa: BLE001 — a broken handbook must not break the palette
        return None


def clear_cache() -> None:
    """Forget the parsed handbook (after the constructor saved it)."""
    _cached_store.cache_clear()


def parameter_matches(query: str, *, language: str | None = None, limit: int = 6) -> tuple[ParameterRef, ...]:
    """Handbook parameters whose name or id contains ``query`` (TP-6 «Справочник: КДР»).

    The palette of Ctrl+K offers these next to its commands, so «Справочник: КДР»
    opens the S1 window on the row instead of a generic list of themes.  Matching
    is the store's own (name and id, case-insensitive), deduplicated by id, and
    ``limit`` keeps the palette a palette.
    """
    needle = (query or "").strip()
    if len(needle) < 2:
        return ()
    store = _cached_store(_language(language))
    if store is None:
        return ()
    found: list[ParameterRef] = []
    seen: set[str] = set()
    for _topic, _pathology, _gradation, param in store.search(needle):
        if param.id in seen:
            continue
        seen.add(param.id)
        found.append(param)
        if len(found) >= limit:
            break
    return tuple(found)


def topic_entries(store: ReferenceDataStore) -> tuple[TopicEntry, ...]:
    """The left navigation: every topic with the number of its parameters."""
    return tuple(
        TopicEntry(
            slug=topic.slug,
            name=topic.name,
            parameter_count=len(_unique_parameters(topic)),
            pathology_count=len(topic.pathologies),
        )
        for topic in store.get_topics()
    )


def build_topic_view(
    store: ReferenceDataStore,
    topic_slug: str,
    *,
    sex: str = SEX_BOTH,
    values: Mapping[str, float] | None = None,
    language: str | None = None,
) -> TopicView:
    """Rows of one topic: norm by sex, gradation columns and the patient's values.

    ``values`` is keyed by handbook id — pass the output of
    :func:`reference_values` for the projection of the study.
    """
    topic = store.get_topic(topic_slug)
    if topic is None:
        return TopicView(slug=topic_slug, name="", is_topic=True)
    params = _unique_parameters(topic)
    columns = _columns_of(params, sex, language)
    rows: list[ReferenceRow] = []
    used: set[str] = set()
    for pathology in topic.pathologies:
        for param in _parameters_of(pathology):
            if param.id in used:
                continue
            used.add(param.id)
            rows.append(
                _row(
                    param,
                    topic=topic,
                    pathology=pathology,
                    columns=columns,
                    sex=sex,
                    value=(values or {}).get(param.id),
                    language=language,
                )
            )
    return TopicView(slug=topic.slug, name=topic.name, rows=tuple(rows), columns=columns, is_topic=True)


def search_view(
    store: ReferenceDataStore,
    query: str,
    *,
    sex: str = SEX_BOTH,
    values: Mapping[str, float] | None = None,
    language: str | None = None,
) -> TopicView:
    """Search results across the whole handbook, in the order of the store.

    The rows keep their topic and pathology so the table can show where a match
    came from — that is what «Справочник: КДР» of the command palette needs.
    """
    needle = (query or "").strip()
    if not needle:
        return TopicView(slug="", name="", rows=(), columns=(), is_topic=False)
    matches = store.search(needle)
    params = [param for _topic, _patho, _grad, param in matches]
    columns = _columns_of(params, sex, language)
    rows: list[ReferenceRow] = []
    seen: set[str] = set()
    for topic, pathology, _gradation, param in matches:
        if param.id in seen:
            continue
        seen.add(param.id)
        rows.append(
            _row(
                param,
                topic=topic,
                pathology=pathology,
                columns=columns,
                sex=sex,
                value=(values or {}).get(param.id),
                language=language,
            )
        )
    return TopicView(slug="", name=needle, rows=tuple(rows), columns=columns, is_topic=False)


__all__ = [
    "PROJECTION_TO_HANDBOOK",
    "SEX_BOTH",
    "SEX_FEMALE",
    "SEX_MALE",
    "ReferenceRow",
    "TopicEntry",
    "TopicView",
    "build_topic_view",
    "chip_label",
    "clear_cache",
    "format_cut",
    "gradation_key",
    "parameter_matches",
    "gradation_rank",
    "reference_values",
    "search_view",
    "topic_entries",
]
