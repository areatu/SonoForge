"""Mutable working copy model for the reference constructor."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormRangeModel:
    low: float | None = None
    high: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"low": self.low, "high": self.high}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> NormRangeModel | None:
        if d is None:
            return None
        return cls(low=d.get("low"), high=d.get("high"))


@dataclass
class ParameterModel:
    id: str = ""
    name: str = ""
    unit: str = ""
    norm_male: NormRangeModel | None = None
    norm_female: NormRangeModel | None = None
    pathology_desc: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "unit": self.unit,
        }
        if self.norm_male:
            d["norm_male"] = self.norm_male.to_dict()
        if self.norm_female:
            d["norm_female"] = self.norm_female.to_dict()
        if self.pathology_desc:
            d["pathology_desc"] = self.pathology_desc
        if self.source:
            d["source"] = self.source
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ParameterModel:
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            unit=d.get("unit", ""),
            norm_male=NormRangeModel.from_dict(d.get("norm_male")),
            norm_female=NormRangeModel.from_dict(d.get("norm_female")),
            pathology_desc=d.get("pathology_desc"),
            source=d.get("source"),
        )


@dataclass
class GradationModel:
    name: str = ""
    parameters: list[ParameterModel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parameters": [p.to_dict() for p in self.parameters],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GradationModel:
        return cls(
            name=d.get("name", ""),
            parameters=[ParameterModel.from_dict(p) for p in d.get("parameters", [])],
        )


@dataclass
class PathologyModel:
    name: str = ""
    slug: str = ""
    description: str | None = None
    image_paths: list[str] = field(default_factory=list)
    parameters: list[ParameterModel] = field(default_factory=list)
    gradations: list[GradationModel] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Convert dicts to GradationModel if needed
        self.gradations = [g if isinstance(g, GradationModel) else GradationModel.from_dict(g) for g in self.gradations]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "slug": self.slug,
        }
        if self.description:
            d["description"] = self.description
        if self.image_paths:
            d["image_paths"] = list(self.image_paths)
        if self.gradations:
            d["gradations"] = [g.to_dict() for g in self.gradations]
        # Always include parameters to satisfy schema anyOf requirement
        d["parameters"] = [p.to_dict() for p in self.parameters]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PathologyModel:
        return cls(
            name=d.get("name", ""),
            slug=d.get("slug", ""),
            description=d.get("description"),
            image_paths=list(d.get("image_paths", [])),
            parameters=[ParameterModel.from_dict(p) for p in d.get("parameters", [])],
            gradations=[GradationModel.from_dict(g) for g in d.get("gradations", [])],
        )

    @property
    def has_gradations(self) -> bool:
        return len(self.gradations) > 0

    def all_parameters(self) -> list[ParameterModel]:
        """Return flat list of all parameters (from gradations or flat)."""
        if self.has_gradations:
            return [p for g in self.gradations for p in g.parameters]
        return list(self.parameters)


@dataclass
class TopicModel:
    name: str = ""
    slug: str = ""
    pathologies: list[PathologyModel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "slug": self.slug,
            "pathologies": [p.to_dict() for p in self.pathologies],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TopicModel:
        return cls(
            name=d.get("name", ""),
            slug=d.get("slug", ""),
            pathologies=[PathologyModel.from_dict(p) for p in d.get("pathologies", [])],
        )


@dataclass
class ReferenceModel:
    """Mutable working copy of the entire reference handbook."""

    topics: list[TopicModel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"topics": [t.to_dict() for t in self.topics]}

    def to_yaml(self) -> str:
        """Serialize to YAML string."""
        import yaml

        return yaml.dump(
            self.to_dict(),
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=120,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReferenceModel:
        return cls(
            topics=[TopicModel.from_dict(t) for t in data.get("topics", [])],
        )

    @classmethod
    def from_yaml(cls, yaml_str: str) -> ReferenceModel:
        import yaml

        data = yaml.safe_load(yaml_str)
        return cls.from_dict(data or {"topics": []})

    def deep_copy(self) -> ReferenceModel:
        return copy.deepcopy(self)

    def get_topic(self, slug: str) -> TopicModel | None:
        for t in self.topics:
            if t.slug == slug:
                return t
        return None

    def get_pathology(self, topic_slug: str, pathology_slug: str) -> PathologyModel | None:
        topic = self.get_topic(topic_slug)
        if topic is None:
            return None
        for p in topic.pathologies:
            if p.slug == pathology_slug:
                return p
        return None

    def find_parameter(self, param_id: str) -> tuple[TopicModel, PathologyModel, ParameterModel] | None:
        """Find parameter by id across all topics/pathologies."""
        for topic in self.topics:
            for patho in topic.pathologies:
                for param in patho.all_parameters():
                    if param.id == param_id:
                        return (topic, patho, param)
        return None

    def all_param_ids(self) -> set[str]:
        """Collect all parameter IDs."""
        ids: set[str] = set()
        for topic in self.topics:
            for patho in topic.pathologies:
                for param in patho.all_parameters():
                    ids.add(param.id)
        return ids

    def all_image_paths(self) -> set[str]:
        """Collect all referenced image filenames."""
        paths: set[str] = set()
        for topic in self.topics:
            for patho in topic.pathologies:
                paths.update(patho.image_paths)
        return paths
