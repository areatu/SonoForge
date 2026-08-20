"""Structured reference data model and YAML loader."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


@dataclass
class NormRange:
    low: float | None = None
    high: float | None = None


@dataclass
class ParameterGradationRef:
    name: str = ""
    range_male: NormRange | None = None
    range_female: NormRange | None = None


@dataclass
class ParameterRef:
    id: str = ""
    name: str = ""
    full_name: str = ""
    unit: str = ""
    norm_male: NormRange | None = None
    norm_female: NormRange | None = None
    pathology_desc: str | None = None
    source: str | None = None
    gradations: list[ParameterGradationRef] = field(default_factory=list)

    @property
    def tooltip(self) -> str:
        """Full descriptive name for hover tooltips (falls back to short name)."""
        return self.full_name or self.name


@dataclass
class GradationRef:
    name: str = ""
    parameters: list[ParameterRef] = field(default_factory=list)


@dataclass
class PathologyRef:
    name: str = ""
    slug: str = ""
    description: str | None = None
    image_paths: list[str] = field(default_factory=list)
    gradations: list[GradationRef] | None = None
    parameters: list[ParameterRef] | None = None

    @property
    def image_path(self) -> str | None:
        """Backward-compatible: first image path or None."""
        return self.image_paths[0] if self.image_paths else None


@dataclass
class TopicRef:
    name: str = ""
    slug: str = ""
    pathologies: list[PathologyRef] = field(default_factory=list)


def _parse_norm_range(val: Any) -> NormRange | None:
    if val is None:
        return None
    return NormRange(low=val.get("low"), high=val.get("high"))


def _parse_parameter_gradations(raw: list[dict] | None) -> list[ParameterGradationRef]:
    if not raw:
        return []
    return [
        ParameterGradationRef(
            name=g["name"],
            range_male=_parse_norm_range(g.get("range_male")),
            range_female=_parse_norm_range(g.get("range_female")),
        )
        for g in raw
    ]


def _parse_parameters(raw: list[dict]) -> list[ParameterRef]:
    return [
        ParameterRef(
            id=p["id"],
            name=p["name"],
            full_name=p.get("full_name", ""),
            unit=p.get("unit", ""),
            norm_male=_parse_norm_range(p.get("norm_male")),
            norm_female=_parse_norm_range(p.get("norm_female")),
            pathology_desc=p.get("pathology_desc"),
            source=p.get("source"),
            gradations=_parse_parameter_gradations(p.get("gradations")),
        )
        for p in raw
    ]


def _parse_gradations(raw: list[dict]) -> list[GradationRef]:
    return [
        GradationRef(
            name=g["name"],
            parameters=_parse_parameters(g.get("parameters", [])),
        )
        for g in raw
    ]


def _parse_pathologies(raw: list[dict]) -> list[PathologyRef]:
    result = []
    for p in raw:
        # Support image_paths (list), image_path (str), or neither
        img = p.get("image_paths") or p.get("image_path")
        if isinstance(img, list):
            image_paths = img
        elif isinstance(img, str):
            image_paths = [img]
        else:
            image_paths = []

        result.append(
            PathologyRef(
                name=p["name"],
                slug=p["slug"],
                description=p.get("description"),
                image_paths=image_paths,
                gradations=_parse_gradations(p["gradations"]) if "gradations" in p else None,
                parameters=_parse_parameters(p.get("parameters", [])) if "parameters" in p else None,
            )
        )
    return result


def _norm_from_dict(d: dict) -> NormRange:
    """Create NormRange from a {low, high} dict."""
    return NormRange(low=d.get("low"), high=d.get("high"))


def _norm_to_dict(norm: NormRange | None) -> dict | None:
    """Serialize NormRange to a {low, high} dict, omitting None values."""
    if norm is None:
        return None
    d: dict[str, float] = {}
    if norm.low is not None:
        d["low"] = norm.low
    if norm.high is not None:
        d["high"] = norm.high
    return d if d else None


def _param_to_dict(param: ParameterRef) -> dict:
    """Serialize a ParameterRef to a YAML-compatible dict."""
    d: dict[str, Any] = {"id": param.id, "name": param.name}
    if param.full_name:
        d["full_name"] = param.full_name
    if param.unit:
        d["unit"] = param.unit
    nm = _norm_to_dict(param.norm_male)
    if nm:
        d["norm_male"] = nm
    nf = _norm_to_dict(param.norm_female)
    if nf:
        d["norm_female"] = nf
    if param.pathology_desc:
        d["pathology_desc"] = param.pathology_desc
    if param.source:
        d["source"] = param.source
    if param.gradations:
        d["gradations"] = []
        for g in param.gradations:
            gd: dict[str, Any] = {"name": g.name}
            rm = _norm_to_dict(g.range_male)
            if rm:
                gd["range_male"] = rm
            rf = _norm_to_dict(g.range_female)
            if rf:
                gd["range_female"] = rf
            d["gradations"].append(gd)
    return d


def _flow_dict_representer(dumper, data):
    """Use flow style for small dicts (NormRange, gradation ranges)."""
    if all(isinstance(k, str) and k in ("low", "high", "name") for k in data):
        return dumper.represent_mapping("tag:yaml.org,2002:map", data.items(), flow_style=True)
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items())


class ReferenceDataStore:
    """Loads and provides access to structured reference data."""

    def __init__(self, yaml_path: str | Path | None = None) -> None:
        self._yaml_path = Path(yaml_path) if yaml_path else self._default_path()
        self._topics: list[TopicRef] = []
        self._param_index: dict[str, tuple[TopicRef, PathologyRef, GradationRef | None]] = {}

    @staticmethod
    def _default_path() -> Path:
        return Path(__file__).resolve().parents[2] / "resources" / "references" / "references_structured.yaml"

    def load(self) -> ReferenceDataStore:
        raw = yaml.safe_load(self._yaml_path.read_text(encoding="utf-8"))
        self._topics = [
            TopicRef(name=t["name"], slug=t["slug"], pathologies=_parse_pathologies(t.get("pathologies", [])))
            for t in raw.get("topics", [])
        ]
        self._rebuild_index()
        return self

    def _rebuild_index(self) -> None:
        self._param_index = {}
        for topic in self._topics:
            for patho in topic.pathologies:
                if patho.gradations:
                    for grad in patho.gradations:
                        for param in grad.parameters:
                            if param.id not in self._param_index:
                                self._param_index[param.id] = (topic, patho, grad)
                if patho.parameters:
                    for param in patho.parameters:
                        if param.id not in self._param_index:
                            self._param_index[param.id] = (topic, patho, None)

    def get_topics(self) -> list[TopicRef]:
        return list(self._topics)

    def get_topic(self, slug: str) -> TopicRef | None:
        for t in self._topics:
            if t.slug == slug:
                return t
        return None

    def get_pathology(self, topic_slug: str, pathology_slug: str) -> PathologyRef | None:
        topic = self.get_topic(topic_slug)
        if topic is None:
            return None
        for p in topic.pathologies:
            if p.slug == pathology_slug:
                return p
        return None

    def lookup(self, param_id: str) -> tuple[TopicRef, PathologyRef, GradationRef | None] | None:
        return self._param_index.get(param_id)

    def search(self, query: str) -> list[tuple[TopicRef, PathologyRef, GradationRef | None, ParameterRef]]:
        q = query.casefold()
        results: list[tuple[TopicRef, PathologyRef, GradationRef | None, ParameterRef]] = []
        for topic in self._topics:
            for patho in topic.pathologies:
                if patho.gradations:
                    for grad in patho.gradations:
                        for param in grad.parameters:
                            if q in param.name.casefold() or q in param.id.casefold():
                                results.append((topic, patho, grad, param))
                if patho.parameters:
                    for param in patho.parameters:
                        if q in param.name.casefold() or q in param.id.casefold():
                            results.append((topic, patho, None, param))
        return results

    def update_param(self, param_id: str, field_name: str, value: Any) -> None:
        """Update a parameter field in-memory and persist to YAML."""
        for topic in self._topics:
            for patho in topic.pathologies:
                params = list(patho.parameters or [])
                if patho.gradations:
                    for grad in patho.gradations:
                        params.extend(grad.parameters)
                for param in params:
                    if param.id == param_id:
                        if field_name == "name":
                            # Preserve the previous full name for hover tooltips when
                            # the display name is shortened (captured only once).
                            if value != param.name and not param.full_name:
                                param.full_name = param.name
                            param.name = value
                        elif field_name == "unit":
                            param.unit = value
                        elif field_name == "norm_male":
                            param.norm_male = _norm_from_dict(value) if isinstance(value, dict) else value
                        elif field_name == "norm_female":
                            param.norm_female = _norm_from_dict(value) if isinstance(value, dict) else value
                        self._save_to_yaml()
                        return

    def update_gradation(
        self,
        param_id: str,
        grad_name: str,
        male_range: dict | None,
        female_range: dict | None,
    ) -> None:
        """Update a gradation's range in-memory and persist to YAML."""
        for topic in self._topics:
            for patho in topic.pathologies:
                params = list(patho.parameters or [])
                if patho.gradations:
                    for grad in patho.gradations:
                        params.extend(grad.parameters)
                for param in params:
                    if param.id == param_id:
                        for g in param.gradations:
                            if g.name == grad_name:
                                if male_range is not None:
                                    g.range_male = _norm_from_dict(male_range)
                                if female_range is not None:
                                    g.range_female = _norm_from_dict(female_range)
                                self._save_to_yaml()
                                return

    def _save_to_yaml(self) -> None:
        """Serialize the current data model back to the YAML file."""
        data = {"topics": []}
        for topic in self._topics:
            t: dict[str, Any] = {"name": topic.name, "slug": topic.slug, "pathologies": []}
            for patho in topic.pathologies:
                p: dict[str, Any] = {"name": patho.name, "slug": patho.slug}
                if patho.description:
                    p["description"] = patho.description
                if patho.image_paths:
                    p["image_paths"] = patho.image_paths
                if patho.gradations:
                    p["gradations"] = []
                    for grad in patho.gradations:
                        g: dict[str, Any] = {"name": grad.name, "parameters": []}
                        for param in grad.parameters:
                            g["parameters"].append(_param_to_dict(param))
                        p["gradations"].append(g)
                if patho.parameters:
                    p["parameters"] = [_param_to_dict(param) for param in patho.parameters]
                t["pathologies"].append(p)
            data["topics"].append(t)

        dumper = yaml.Dumper
        dumper.add_representer(dict, _flow_dict_representer)

        try:
            with open(self._yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    data,
                    f,
                    Dumper=dumper,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
            log.info("Saved reference data to %s", self._yaml_path)
        except Exception:
            log.exception("Failed to save reference data")
