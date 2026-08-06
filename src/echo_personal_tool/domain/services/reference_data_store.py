"""Structured reference data model and YAML loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class NormRange:
    low: float | None = None
    high: float | None = None


@dataclass
class ParameterRef:
    id: str = ""
    name: str = ""
    unit: str = ""
    norm_male: NormRange | None = None
    norm_female: NormRange | None = None
    pathology_desc: str | None = None
    source: str | None = None


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


def _parse_parameters(raw: list[dict]) -> list[ParameterRef]:
    return [
        ParameterRef(
            id=p["id"],
            name=p["name"],
            unit=p.get("unit", ""),
            norm_male=_parse_norm_range(p.get("norm_male")),
            norm_female=_parse_norm_range(p.get("norm_female")),
            pathology_desc=p.get("pathology_desc"),
            source=p.get("source"),
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
