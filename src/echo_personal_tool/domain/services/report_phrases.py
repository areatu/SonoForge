"""Report phrases of the report mode (UI-4 PR-3, spec §4.6, UQ-08).

The «Фразы» column inserts pre-written conclusion sentences at the cursor;
nothing is inserted automatically — a phrase enters the text only on a click
of the physician (UQ-08).  The built-in starter set below is deliberately
small (fewer than 30 neutral descriptive sentences, RU and EN) and stays a
draft for the owner's approval: every phrase repeats ordinary conclusion
wording, never a diagnosis the measurements do not support.  Phrases carry
no numbers — the physician edits the sentence after inserting it, so a stale
value can never be printed by accident.

The module is pure (no Qt): the presentation layer renders the groups and the
infrastructure store persists user phrases in exactly the document this module
encodes, so an exported file can be imported on another machine.

The text model is bilingual by design.  Both languages are stored for every
phrase, an empty translation falls back to the filled one, and the list shows
the language of the interface (UD-15).  Phrase identity is content-derived
(``section + RU + EN``), which makes import idempotent and keeps the store file
readable and hand-editable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final

from echo_personal_tool.domain.measurement_catalog import SECTIONS

#: A user library larger than this stops being a list a physician can scan.
MAX_USER_PHRASES: Final[int] = 200

#: One phrase longer than this is a paragraph, not a phrase.
MAX_PHRASE_TEXT: Final[int] = 400

#: Sections without a phrase fall back to the generic one on import.
_DEFAULT_SECTION: Final[str] = "general"

#: Sentence-closing punctuation.  A phrase without it receives a full stop on
#: insertion, so two phrases never glue into one unreadable sentence.
_SENTENCE_ENDINGS: Final[str] = ".!?…:;"

_FORMAT: Final[str] = "sonoforge.report-phrases"
_VERSION: Final[int] = 1

_WHITESPACE_RE = re.compile(r"\s+")


class PhraseDocumentError(ValueError):
    """The imported file is not a phrase document at all."""


@dataclass(frozen=True)
class ReportPhrase:
    """One bilingual conclusion phrase.

    ``id`` of a user phrase is derived from its content (:func:`phrase_id`);
    the built-in set uses stable ``builtin.*`` ids.  ``builtin`` tells the
    library that the phrase ships with the application and cannot be removed.
    """

    id: str
    section: str
    ru: str
    en: str
    builtin: bool = True

    def text(self, language: str = "ru") -> str:
        """The phrase in the requested language; unknown languages read EN."""
        return self.ru if _language(language) == "ru" else self.en


@dataclass(frozen=True)
class PhraseGroup:
    """Phrases of one catalog section, ready for the column."""

    section: str
    title: str
    phrases: tuple[ReportPhrase, ...]


@dataclass(frozen=True)
class PhraseDocument:
    """A parsed phrase file: the valid phrases and how many items were skipped."""

    phrases: tuple[ReportPhrase, ...]
    skipped: int = 0


def _language(language: str) -> str:
    code = (language or "").strip().lower()[:2]
    return code if code in ("ru", "en") else "en"


def clean_text(value: object) -> str:
    """Collapse whitespace and trim; non-strings read as an empty text."""
    if not isinstance(value, str):
        return ""
    return _WHITESPACE_RE.sub(" ", value).strip()


def _section(value: object) -> str:
    code = value.strip().lower() if isinstance(value, str) else ""
    return code if code in SECTIONS else _DEFAULT_SECTION


def phrase_id(section: str, ru: str, en: str) -> str:
    """Content-derived identity of a user phrase (stable across import/export)."""
    digest = hashlib.sha1(f"{section}\x1f{ru}\x1f{en}".encode()).hexdigest()
    return f"user.{digest[:12]}"


def make_user_phrase(section: object, ru: object, en: object) -> ReportPhrase | None:
    """A validated user phrase, or ``None`` when the input is not usable.

    One filled language is enough: the missing translation falls back to it,
    so the list never shows an empty row.  An unknown section is grouped under
    the generic one instead of being dropped — an imported phrase must not
    disappear because the catalog moved on.
    """
    ru_text = clean_text(ru)
    en_text = clean_text(en)
    if not ru_text and not en_text:
        return None
    ru_text = ru_text or en_text
    en_text = en_text or ru_text
    if len(ru_text) > MAX_PHRASE_TEXT or len(en_text) > MAX_PHRASE_TEXT:
        return None
    resolved = _section(section)
    return ReportPhrase(phrase_id(resolved, ru_text, en_text), resolved, ru_text, en_text, builtin=False)


def phrases_match(first: ReportPhrase, second: ReportPhrase) -> bool:
    """Whether two phrases carry the same text (both languages, whitespace-insensitive)."""
    return (normalize_for_search(first.ru), normalize_for_search(first.en)) == (
        normalize_for_search(second.ru),
        normalize_for_search(second.en),
    )


def _p(phrase_id_value: str, section: str, ru: str, en: str) -> ReportPhrase:
    return ReportPhrase(phrase_id_value, section, ru, en, builtin=True)


#: Starter set for the owner's approval (UQ-08): 28 neutral sentences, grouped
#: by catalog sections.  Nothing here asserts a diagnosis; the physician edits
#: the inserted sentence to match the study.
PHRASES: Final[tuple[ReportPhrase, ...]] = (
    _p(
        "builtin.general.standard",
        "general",
        "Эхокардиография выполнена в стандартном объёме",
        "Echocardiography was performed using the standard protocol",
    ),
    _p(
        "builtin.general.no_shunt",
        "general",
        "Признаков внутрисердечных шунтов не выявлено",
        "No intracardiac shunts detected",
    ),
    _p(
        "builtin.general.no_comparison",
        "general",
        "Данные предыдущих исследований для сравнения не предоставлены",
        "No previous studies were available for comparison",
    ),
    _p(
        "builtin.lv.no_dilation",
        "lv",
        "Полость левого желудочка не расширена",
        "The left ventricular cavity is not dilated",
    ),
    _p(
        "builtin.lv.wall_thickness",
        "lv",
        "Толщина стенок левого желудочка в норме",
        "Left ventricular wall thickness is normal",
    ),
    _p(
        "builtin.lv.no_hypertrophy",
        "lv",
        "Гипертрофии миокарда левого желудочка не выявлено",
        "No left ventricular hypertrophy",
    ),
    _p(
        "builtin.lv.mass_index",
        "lv",
        "Индекс массы миокарда левого желудочка в пределах нормы",
        "Left ventricular mass index is within the normal range",
    ),
    _p(
        "builtin.lv.systolic_preserved",
        "lv",
        "Глобальная систолическая функция левого желудочка сохранена",
        "Global left ventricular systolic function is preserved",
    ),
    _p(
        "builtin.lv.no_wall_motion",
        "lv",
        "Зон нарушения локальной сократимости не выявлено",
        "No regional wall motion abnormalities detected",
    ),
    _p(
        "builtin.la.no_dilation",
        "la",
        "Полость левого предсердия не расширена",
        "The left atrial cavity is not dilated",
    ),
    _p(
        "builtin.la.volume",
        "la",
        "Объём левого предсердия в пределах нормы",
        "Left atrial volume is within the normal range",
    ),
    _p(
        "builtin.la.no_thrombus",
        "la",
        "Признаков тромба в полости левого предсердия не выявлено",
        "No thrombus detected in the left atrium",
    ),
    _p(
        "builtin.ra.no_dilation",
        "ra",
        "Полость правого предсердия не расширена",
        "The right atrial cavity is not dilated",
    ),
    _p(
        "builtin.ra.pressure",
        "ra",
        "Признаков повышения давления в правом предсердии не выявлено",
        "No signs of elevated right atrial pressure",
    ),
    _p(
        "builtin.rv.no_dilation",
        "rv",
        "Полость правого желудочка не расширена",
        "The right ventricular cavity is not dilated",
    ),
    _p(
        "builtin.rv.systolic_preserved",
        "rv",
        "Систолическая функция правого желудочка сохранена",
        "Right ventricular systolic function is preserved",
    ),
    _p(
        "builtin.rv.wall_thickness",
        "rv",
        "Толщина свободной стенки правого желудочка в норме",
        "Right ventricular free wall thickness is normal",
    ),
    _p(
        "builtin.diastolic.normal",
        "diastolic",
        "Диастолическая функция левого желудочка не нарушена",
        "Left ventricular diastolic function is not impaired",
    ),
    _p(
        "builtin.diastolic.e_e_prime",
        "diastolic",
        "Показатель E/e′ в пределах нормы",
        "The E/e′ ratio is within the normal range",
    ),
    _p(
        "builtin.diastolic.e_a",
        "diastolic",
        "Соотношение E/A в пределах возрастной нормы",
        "The E/A ratio is within the age-related normal range",
    ),
    _p(
        "builtin.diastolic.filling_pressure",
        "diastolic",
        "Признаков повышения давления наполнения левого желудочка не выявлено",
        "No signs of elevated left ventricular filling pressure",
    ),
    _p(
        "builtin.mv_av.no_mr",
        "mv_av",
        "Регургитация на митральном клапане не выявлена",
        "No mitral regurgitation detected",
    ),
    _p(
        "builtin.mv_av.no_ar",
        "mv_av",
        "Регургитация на аортальном клапане не выявлена",
        "No aortic regurgitation detected",
    ),
    _p(
        "builtin.mv_av.no_significant",
        "mv_av",
        "Клапанный аппарат без гемодинамически значимых изменений",
        "No haemodynamically significant valvular abnormalities",
    ),
    _p(
        "builtin.tv_pv.no_tr",
        "tv_pv",
        "Регургитация на трикуспидальном клапане не выявлена",
        "No tricuspid regurgitation detected",
    ),
    _p(
        "builtin.tv_pv.no_ph",
        "tv_pv",
        "Признаков лёгочной гипертензии не выявлено",
        "No signs of pulmonary hypertension",
    ),
    _p(
        "builtin.aorta.no_dilation",
        "aorta",
        "Корень и восходящий отдел аорты не расширены",
        "The aortic root and ascending aorta are not dilated",
    ),
    _p(
        "builtin.aorta.no_aneurysm",
        "aorta",
        "Аневризматического расширения аорты не выявлено",
        "No aortic aneurysm detected",
    ),
)

_SECTION_ORDER: Final[dict[str, int]] = {section_id: index for index, section_id in enumerate(SECTIONS)}


def _section_title(section: str, language: str) -> str:
    spec = SECTIONS.get(section)
    return spec.label(language).short if spec is not None else section


def normalize_for_search(text: str) -> str:
    """Case- and whitespace-insensitive form used by the search and the marks."""
    return _WHITESPACE_RE.sub(" ", (text or "")).strip().casefold()


def filter_phrases(
    phrases: tuple[ReportPhrase, ...],
    language: str = "ru",
    query: str = "",
) -> tuple[ReportPhrase, ...]:
    """Phrases matching the query in either language or in their section title."""
    needle = normalize_for_search(query)
    if not needle:
        return tuple(phrases)
    return tuple(
        phrase
        for phrase in phrases
        if needle in normalize_for_search(phrase.ru)
        or needle in normalize_for_search(phrase.en)
        or needle in normalize_for_search(_section_title(phrase.section, language))
    )


def phrase_groups(
    phrases: tuple[ReportPhrase, ...],
    language: str = "ru",
    query: str = "",
) -> tuple[PhraseGroup, ...]:
    """Visible phrases grouped by catalog section, in catalog order."""
    buckets: dict[str, list[ReportPhrase]] = {}
    for phrase in filter_phrases(phrases, language, query):
        buckets.setdefault(phrase.section, []).append(phrase)
    ordered = sorted(buckets, key=lambda section: _SECTION_ORDER.get(section, len(_SECTION_ORDER)))
    return tuple(
        PhraseGroup(section, _section_title(section, language), tuple(buckets[section])) for section in ordered
    )


def insertion_segment(before: str, after: str, phrase: str) -> str:
    """The text a click inserts, with the separators the context needs.

    A phrase is a sentence: unless it already ends with punctuation it receives
    a full stop.  After a word the sentence separator is ``". "``; after
    punctuation a single space is enough.  When the cursor sits inside a
    sentence, a space keeps the following text readable.
    """
    sentence = clean_text(phrase)
    if not sentence:
        return ""
    if not sentence.endswith(tuple(_SENTENCE_ENDINGS)):
        sentence += "."
    lead = ""
    if before and not before[-1].isspace():
        lead = " " if before[-1] in _SENTENCE_ENDINGS else ". "
    trail = ""
    if after and not after[0].isspace() and after[0] not in _SENTENCE_ENDINGS:
        trail = " "
    return lead + sentence + trail


def conclusion_insertion(conclusion: str, phrase: str, cursor: int | None = None) -> tuple[str, int]:
    """Insert a phrase into a conclusion at ``cursor``; return the new text and position."""
    text = conclusion or ""
    position = len(text) if cursor is None else max(0, min(int(cursor), len(text)))
    segment = insertion_segment(text[:position], text[position:], phrase)
    return text[:position] + segment + text[position:], position + len(segment)


def phrase_is_inserted(conclusion: str, phrase: str) -> bool:
    """Whether the phrase already appears in the conclusion as whole words."""
    needle = normalize_for_search(phrase).rstrip(".!?…:;,")
    if not needle:
        return False
    haystack = normalize_for_search(conclusion)
    start = haystack.find(needle)
    while start >= 0:
        end = start + len(needle)
        before_ok = start == 0 or not (haystack[start - 1].isalnum() or haystack[start - 1] == "_")
        after_ok = end == len(haystack) or not (haystack[end].isalnum() or haystack[end] == "_")
        if before_ok and after_ok:
            return True
        start = haystack.find(needle, start + 1)
    return False


def inserted_phrase_ids(
    phrases: tuple[ReportPhrase, ...],
    conclusion: str,
    language: str = "ru",
) -> frozenset[str]:
    """Ids of the phrases already present in the conclusion (the ✓ marks)."""
    return frozenset(phrase.id for phrase in phrases if phrase_is_inserted(conclusion, phrase.text(language)))


def dumped_document(phrases: tuple[ReportPhrase, ...]) -> str:
    """Serialize user phrases into the import/export document (UTF-8 text)."""
    payload = {
        "format": _FORMAT,
        "version": _VERSION,
        "phrases": [{"section": phrase.section, "ru": phrase.ru, "en": phrase.en} for phrase in phrases],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def parse_phrase_document(text: str) -> PhraseDocument:
    """Read an import/export document, skipping unusable entries.

    Only the shape of the document can make the whole import fail; a broken
    item (not an object, both texts empty, too long, a duplicate) is counted in
    :attr:`PhraseDocument.skipped` and does not cost the rest of the file.
    """
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise PhraseDocumentError("the file is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise PhraseDocumentError("the document is not a JSON object")
    raw = payload.get("phrases")
    if not isinstance(raw, list):
        raise PhraseDocumentError("the document has no phrases list")

    phrases: list[ReportPhrase] = []
    seen: set[str] = set()
    skipped = 0
    for item in raw:
        phrase = (
            make_user_phrase(item.get("section"), item.get("ru"), item.get("en")) if isinstance(item, dict) else None
        )
        if phrase is None or phrase.id in seen or len(phrases) >= MAX_USER_PHRASES:
            skipped += 1
            continue
        seen.add(phrase.id)
        phrases.append(phrase)
    return PhraseDocument(tuple(phrases), skipped)
