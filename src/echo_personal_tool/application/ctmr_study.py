"""Routing helper: build a CT/MR stack index from loaded studies (#557).

The scan pipeline produces ordinary ``StudyMetadata``/``InstanceMetadata`` for
every file, including classic CT/MR slices.  Without a routing decision those
slices are indistinguishable from ultrasound clips and land in the thumbnail
gallery one file at a time.  This module inspects the loaded instances, picks
out the classic CT/MR ones and indexes them with the header-only
``index_ctmr_files`` pipeline so the UI can present them as a single
multi-page stack.

A study set with no classic CT/MR instances returns ``None``: the regular
ultrasound path stays in charge.  Mixed study sets (US clips plus CT/MR
slices) still route to the stack viewer for the CT/MR part; keeping the two
modalities in one surface is out of scope for the MVP.
"""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.domain.models.ctmr_stack import CtMrIndex
from echo_personal_tool.domain.models.metadata import StudyMetadata
from echo_personal_tool.infrastructure.ctmr_index import index_ctmr_files

_CTMR_MODALITIES = frozenset({"CT", "MR"})


def ct_mr_instance_paths(studies: list[StudyMetadata]) -> list[Path]:
    """Return the on-disk paths of classic CT/MR instances, in load order."""
    paths: list[Path] = []
    seen: set[Path] = set()
    for study in studies:
        for series in study.series:
            for instance in series.instances:
                if instance.modality not in _CTMR_MODALITIES:
                    continue
                path = instance.path
                if path is None:
                    continue
                resolved = path if path.is_absolute() else path
                key = resolved
                if key in seen:
                    continue
                seen.add(key)
                paths.append(resolved)
    return paths


def build_ctmr_index(studies: list[StudyMetadata]) -> CtMrIndex | None:
    """Index the CT/MR instances of a loaded study set, or ``None`` when absent.

    ``None`` means "not a classic CT/MR stack": the caller keeps the ordinary
    ultrasound surface.  An index with no usable stacks (every file rejected by
    the header validator) is also treated as "not a stack" so the user still
    sees the files through the regular path rather than an empty viewer.
    """
    paths = ct_mr_instance_paths(studies)
    if not paths:
        return None
    index = index_ctmr_files(paths)
    if not index.stacks:
        return None
    return index
