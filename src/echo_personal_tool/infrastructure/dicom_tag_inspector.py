"""Read DICOM tags for inspector UI and overlays."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pydicom

from echo_personal_tool.domain.services.dicom_tag_dictionary import (
    TAG_CONSTANTS,
    TagInfo,
    lookup,
    search_by_keyword,
)


@dataclass(frozen=True)
class DicomTagRow:
    tag_hex: str
    keyword: str
    vr: str
    description: str
    value: str


def _tag_hex(tag_int: int) -> str:
    group = (tag_int >> 16) & 0xFFFF
    element = tag_int & 0xFFFF
    return f"({group:04X},{element:04X})"


def _format_value(value: object) -> str:
    if value is None:
        return ""
    text = pydicom.valuerep.person_name_to_str(value) if hasattr(value, "components") else str(value)
    if len(text) > 240:
        return text[:237] + "..."
    return text


def _resolve_tag_int(spec: str) -> int | None:
    token = spec.strip()
    if not token:
        return None
    if token in TAG_CONSTANTS:
        return TAG_CONSTANTS[token]
    if token.startswith("(") and ")" in token:
        inner = token.strip("()")
        group_s, element_s = inner.split(",", maxsplit=1)
        return (int(group_s, 16) << 16) | int(element_s, 16)
    for info in search_by_keyword(token):
        if info.keyword == token:
            return info.tag
    try:
        tag_int = int(token, 16)
    except ValueError:
        return None
    return tag_int if lookup(tag_int) is not None else tag_int


# PHI tag groups to filter: (0010,xxxx) patient demographics,
# (0008,0080) institution, (0008,0090) referring physician
_PHI_TAG_GROUPS = frozenset({0x0010, 0x0008})
_PHI_TAG_ELEMENTS = frozenset({0x0080, 0x0090, 0x1050, 0x1040})  # 0008,0080; 0008,0090; 0008,1050; 0008,1040


def _is_phi_tag(tag_int: int) -> bool:
    group = (tag_int >> 16) & 0xFFFF
    element = tag_int & 0xFFFF
    if group == 0x0010:
        return True
    if group == 0x0008 and element in _PHI_TAG_ELEMENTS:
        return True
    return False


def read_all_dicom_tag_rows(path: Path, *, filter_phi: bool = False) -> list[DicomTagRow]:
    dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    rows: list[DicomTagRow] = []
    for element in dataset.iterall():
        tag_int = int(element.tag)
        if filter_phi and _is_phi_tag(tag_int):
            continue
        info: TagInfo | None = lookup(tag_int)
        rows.append(
            DicomTagRow(
                tag_hex=_tag_hex(tag_int),
                keyword=info.keyword if info is not None else "",
                vr=str(element.VR or (info.vr if info is not None else "")),
                description=info.description if info is not None else "",
                value=_format_value(element.value),
            )
        )
    return rows


@lru_cache(maxsize=32)
def read_interesting_dicom_tag_rows(path: Path, tag_specs: tuple[str, ...]) -> list[DicomTagRow]:
    if not tag_specs:
        return []
    dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    rows: list[DicomTagRow] = []
    for spec in tag_specs:
        tag_int = _resolve_tag_int(spec)
        if tag_int is None:
            continue
        tag = pydicom.tag.Tag(tag_int >> 16, tag_int & 0xFFFF)
        if tag not in dataset:
            continue
        elem = dataset[tag]
        info = lookup(tag_int)
        rows.append(
            DicomTagRow(
                tag_hex=_tag_hex(tag_int),
                keyword=info.keyword if info is not None else spec,
                vr=str(elem.VR or (info.vr if info is not None else "")),
                description=info.description if info is not None else "",
                value=_format_value(elem.value),
            )
        )
    return rows
