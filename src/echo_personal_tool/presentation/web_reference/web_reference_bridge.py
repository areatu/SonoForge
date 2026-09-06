"""Web-based reference viewer — Python bridge for QWebChannel."""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path

from PySide6.QtCore import QObject, Slot

from echo_personal_tool.domain.services.reference_data_store import (
    ReferenceDataStore,
)
from echo_personal_tool.infrastructure.i18n import get_language

log = logging.getLogger(__name__)

_IMAGES_DIR = Path(__file__).resolve().parents[2] / "resources" / "references" / "images"

_TOPIC_LABELS_RU: dict[str, str] = {
    "left_ventricle": "ЛЖ",
    "left_atrium": "ЛП",
    "right_ventricle": "ПЖ",
    "right_atrium": "ПП",
    "mitral_valve": "МК",
    "aortic_valve": "АК",
    "tricuspid_valve": "ТК",
    "pulmonary_valve": "ПМК",
    "aorta": "Ао",
    "prosthetic_valves": "ПК",
    "other": "...",
    "carotid_arteries": "СА",
    "vertebral_arteries": "ПА",
    "thyroid_gland": "ЩЖ",
    "kidneys": "Поч",
    "abdominal_organs": "ОБП",
    "abdominal_aorta": "БА",
    "lymph_nodes": "ЛУ",
}

_TOPIC_LABELS_EN: dict[str, str] = {
    "left_ventricle": "LV",
    "left_atrium": "LA",
    "right_ventricle": "RV",
    "right_atrium": "RA",
    "mitral_valve": "MV",
    "aortic_valve": "AV",
    "tricuspid_valve": "TV",
    "pulmonary_valve": "PV",
    "aorta": "Ao",
    "prosthetic_valves": "Pr",
    "other": "...",
    "carotid_arteries": "CA",
    "vertebral_arteries": "VA",
    "thyroid_gland": "Th",
    "kidneys": "Kd",
    "abdominal_organs": "Abd",
    "abdominal_aorta": "AA",
    "lymph_nodes": "LN",
}


def _topic_label(slug: str) -> str:
    labels = _TOPIC_LABELS_RU if get_language() == "ru" else _TOPIC_LABELS_EN
    return labels.get(slug, slug[:6])


_TOPIC_ICONS: dict[str, str] = {
    "left_ventricle": "LV01",
    "left_atrium": "LA01",
    "right_ventricle": "RV01",
    "right_atrium": "RA01",
    "mitral_valve": "MV01",
    "aortic_valve": "AV01",
    "tricuspid_valve": "TV01",
    "pulmonary_valve": "PV01",
    "aorta": "AV01",
    "prosthetic_valves": "MV01",
    "other": "LV01",
}


_DASH_RE = re.compile(r"[\u2013\u2014\u2212\-]")


def _as_num(text: str) -> int | float:
    """Convert numeric text to int when integral, else float."""
    text = (text or "").strip()
    f = float(text)
    if f.is_integer():
        return int(f)
    return f


def _parse_range_str(text: str) -> dict | None:
    """Parse '38–52', '≥5', '≤100', '' into a {low, high} dict."""
    text = (text or "").strip()
    if not text or text == "\u2014":
        return None
    text = text.replace(",", ".")
    if text.startswith("\u2265") or text.startswith(">="):
        try:
            return {"low": _as_num(text.lstrip("\u2265>="))}
        except ValueError:
            return None
    if text.startswith("\u2264") or text.startswith("<="):
        try:
            return {"high": _as_num(text.lstrip("\u2264<="))}
        except ValueError:
            return None
    parts = _DASH_RE.split(text, maxsplit=1)
    if len(parts) == 2:
        try:
            lo = _as_num(parts[0].strip()) if parts[0].strip() else None
            hi = _as_num(parts[1].strip()) if parts[1].strip() else None
            return {"low": lo, "high": hi}
        except ValueError:
            return None
    try:
        v = _as_num(text)
        return {"low": v, "high": v}
    except ValueError:
        return None


class WebReferenceBridge(QObject):
    """Python backend exposed to JavaScript for the reference viewer."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store: ReferenceDataStore | None = None

    def configure(self, store: ReferenceDataStore) -> None:
        self._store = store

    @Slot(result=str)
    def reload_store(self) -> str:
        """Reload the YAML data from disk and return success/error."""
        if self._store is None:
            return json.dumps({"error": "Not configured"})
        try:
            self._store.load()
            return json.dumps({"ok": True})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @Slot(result=str)
    def get_topics(self) -> str:
        """Return topic list with labels, icons, pathology counts."""
        if self._store is None:
            return json.dumps([])
        topics = self._store.get_topics()
        result = []
        for t in topics:
            n_pathos = len(t.pathologies)
            n_params = sum(
                len(p.parameters or []) + sum(len(g.parameters) for g in (p.gradations or [])) for p in t.pathologies
            )
            n_images = sum(len(p.image_paths or []) for p in t.pathologies)
            result.append(
                {
                    "name": t.name,
                    "slug": t.slug,
                    "label": _topic_label(t.slug),
                    "icon": _TOPIC_ICONS.get(t.slug, "LV01"),
                    "n_pathologies": n_pathos,
                    "n_params": n_params,
                    "n_images": n_images,
                }
            )
        return json.dumps(result, ensure_ascii=False)

    @Slot(str, result=str)
    def get_topic_detail(self, slug: str) -> str:
        """Return full topic with pathologies."""
        if self._store is None:
            return json.dumps({"error": "Not configured"})
        topic = self._store.get_topic(slug)
        if topic is None:
            return json.dumps({"error": f"Topic '{slug}' not found"})
        pathologies = []
        for p in topic.pathologies:
            n_params = len(p.parameters or []) + sum(len(g.parameters) for g in (p.gradations or []))
            pathologies.append(
                {
                    "name": p.name,
                    "slug": p.slug,
                    "description": p.description or "",
                    "param_count": n_params,
                    "image_count": len(p.image_paths or []),
                    "has_gradations": bool(p.gradations),
                }
            )
        return json.dumps(
            {"name": topic.name, "slug": topic.slug, "pathologies": pathologies},
            ensure_ascii=False,
        )

    @Slot(str, str, result=str)
    def get_pathology(self, topic_slug: str, patho_slug: str) -> str:
        """Return full pathology with parameters and images."""
        if self._store is None:
            return json.dumps({"error": "Not configured"})
        patho = self._store.get_pathology(topic_slug, patho_slug)
        if patho is None:
            return json.dumps({"error": "Pathology not found"})

        params = self._flatten_parameters(patho)

        grad_names: list[str] = []
        has_gradations = any(p.gradations for p in params)
        if has_gradations:
            seen: set[str] = set()
            for p in params:
                for g in p.gradations:
                    if g.name not in seen:
                        grad_names.append(g.name)
                        seen.add(g.name)

        rows = []
        for param in params:
            grad_map = {g.name: g for g in param.gradations}
            grad_values = []
            for gn in grad_names:
                g = grad_map.get(gn)
                if g:
                    parts = []
                    if g.range_male:
                        parts.append(self._fmt_range(g.range_male))
                    if g.range_female:
                        parts.append(self._fmt_range(g.range_female))
                    grad_values.append(" / ".join(parts) if parts else "\u2014")
                else:
                    grad_values.append("\u2014")
            rows.append(
                {
                    "id": param.id,
                    "name": param.name,
                    "full_name": param.tooltip,
                    "unit": param.unit or "",
                    "norm_male": self._fmt_range(param.norm_male) if param.norm_male else "",
                    "norm_female": self._fmt_range(param.norm_female) if param.norm_female else "",
                    "pathology_desc": param.pathology_desc or "",
                    "source": param.source or "",
                    "gradations": grad_values,
                }
            )

        images = []
        for img_name in patho.image_paths or []:
            img_path = _IMAGES_DIR / img_name
            images.append(
                {
                    "name": img_name,
                    "url": f"file://{img_path}" if img_path.exists() else "",
                    "exists": img_path.exists(),
                }
            )

        return json.dumps(
            {
                "name": patho.name,
                "slug": patho.slug,
                "description": patho.description or "",
                "grad_names": grad_names,
                "parameters": rows,
                "images": images,
            },
            ensure_ascii=False,
        )

    @Slot(str, result=str)
    def search(self, query: str) -> str:
        """Global search across all topics/pathologies/parameters."""
        if self._store is None:
            return json.dumps([])
        q = query.lower().strip()
        if not q:
            return json.dumps([])
        results = []
        for topic in self._store.get_topics():
            topic_label = _topic_label(topic.slug)
            if q in topic.name.lower() or q in topic.slug.lower():
                results.append(
                    {
                        "type": "topic",
                        "topic_slug": topic.slug,
                        "name": topic.name,
                        "parent": "",
                    }
                )
            for patho in topic.pathologies:
                if q in patho.name.lower() or q in patho.slug.lower():
                    results.append(
                        {
                            "type": "pathology",
                            "topic_slug": topic.slug,
                            "patho_slug": patho.slug,
                            "name": patho.name,
                            "parent": topic_label,
                        }
                    )
                for param in patho.parameters or []:
                    if q in param.name.lower() or q in param.id.lower():
                        results.append(
                            {
                                "type": "parameter",
                                "topic_slug": topic.slug,
                                "patho_slug": patho.slug,
                                "param_id": param.id,
                                "name": param.name,
                                "parent": topic_label + " / " + patho.name,
                            }
                        )
                for grad in patho.gradations or []:
                    for param in grad.parameters:
                        if q in param.name.lower() or q in param.id.lower():
                            results.append(
                                {
                                    "type": "parameter",
                                    "topic_slug": topic.slug,
                                    "patho_slug": patho.slug,
                                    "param_id": param.id,
                                    "name": param.name,
                                    "parent": topic_label + " / " + patho.name,
                                }
                            )
        return json.dumps(results[:50], ensure_ascii=False)

    @Slot(str, str, str, str, str, result=str)
    def update_param(self, topic_slug: str, patho_slug: str, param_id: str, field: str, value: str) -> str:
        """Update a parameter field (name|unit|norm_male|norm_female) and persist to YAML."""
        if self._store is None:
            return json.dumps({"error": "Not configured"})
        if self._store.get_pathology(topic_slug, patho_slug) is None:
            return json.dumps({"error": "Pathology not found"})
        try:
            if field in ("norm_male", "norm_female"):
                raw = value.strip()
                if raw and raw != "\u2014":
                    parsed = _parse_range_str(raw)
                    if parsed is None:
                        return json.dumps({"error": f"Некорректный диапазон: {value!r}"})
                else:
                    parsed = None
                self._store.update_param(param_id, field, parsed)
            elif field in ("name", "unit"):
                if field == "name":
                    import re as _re

                    value = _re.sub(r"\s*\([^)]+\)\s*$", "", value).strip() or value.strip()
                self._store.update_param(param_id, field, value.strip())
            else:
                return json.dumps({"error": f"Unknown field '{field}'"})
        except Exception as exc:  # noqa: BLE001
            log.exception("update_param failed")
            return json.dumps({"error": str(exc)})
        return json.dumps({"ok": True})

    @Slot(str, str, str, str, str, str, result=str)
    def update_gradation(
        self,
        topic_slug: str,
        patho_slug: str,
        param_id: str,
        grad_name: str,
        male_str: str,
        female_str: str,
    ) -> str:
        """Update a gradation range (male/female) and persist to YAML."""
        if self._store is None:
            return json.dumps({"error": "Not configured"})
        if self._store.get_pathology(topic_slug, patho_slug) is None:
            return json.dumps({"error": "Pathology not found"})
        try:
            male = _parse_range_str(male_str)
            female = _parse_range_str(female_str)
            if (male_str.strip() and male_str.strip() != "\u2014" and male is None) or (
                female_str.strip() and female_str.strip() != "\u2014" and female is None
            ):
                return json.dumps({"error": "Некорректный диапазон градации"})
            self._store.update_gradation(param_id, grad_name, male, female)
        except Exception as exc:  # noqa: BLE001
            log.exception("update_gradation failed")
            return json.dumps({"error": str(exc)})
        return json.dumps({"ok": True})

    @staticmethod
    def _fmt_range(r) -> str:
        lo = r.low
        hi = r.high
        if lo is not None and hi is not None:
            return f"{lo}\u2013{hi}"
        if lo is not None:
            return f"\u2265{lo}"
        if hi is not None:
            return f"\u2264{hi}"
        return "\u2014"

    @staticmethod
    def _flatten_parameters(patho) -> list:
        """Combine parameters from all gradations into a single list."""
        if patho.parameters:
            return list(patho.parameters)
        if not patho.gradations:
            return []
        seen: dict[str, object] = {}
        for grad in patho.gradations:
            for param in grad.parameters:
                if param.id in seen:
                    existing = seen[param.id]
                    if param.pathology_desc:
                        existing.pathology_desc = (
                            (existing.pathology_desc or "") + " / " + f"{grad.name}: {param.pathology_desc}"
                        ).lstrip(" /")
                else:
                    dup = copy.copy(param)
                    if dup.pathology_desc:
                        dup.pathology_desc = f"{grad.name}: {dup.pathology_desc}"
                    seen[param.id] = dup
        return list(seen.values())
