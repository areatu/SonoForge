"""Research IMT use cases: propose, correct, then explicitly confirm (#558).

No implicit write to the clinical document. The GUI/persistence adapter must
supply the current source and its generation at every edit/confirmation/export;
this seam never consults a mutable 'current frame' while computing a result.
"""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.imt import Boundary, ImtDraft, ImtPolicy, ImtRefusal, ImtSource
from echo_personal_tool.domain.services.imt_detection import BoundaryHint, detect_boundaries, edge_evidence
from echo_personal_tool.domain.services.imt_geometry import measure_boundaries


def propose_imt(
    image: np.ndarray, source: ImtSource, policy: ImtPolicy, *, lumen_y: BoundaryHint, adventitia_y: BoundaryHint
) -> ImtDraft:
    """Propose two boundaries in the bounded ROI; output is always a draft."""
    evidence = edge_evidence(image, source)
    li, ma = detect_boundaries(evidence, source, policy, lumen_y=lumen_y, adventitia_y=adventitia_y)
    return measure_boundaries(source, policy, li, ma, evidence)


def correct_imt(
    draft: ImtDraft, current: ImtSource, image: np.ndarray, *, lumen_intima: Boundary, media_adventitia: Boundary
) -> ImtDraft:
    """Re-evaluate edited overlays, resetting confirmation and incrementing revision.

    Editing is not a back door around scale, geometry or image-quality gates.
    A previously accepted result stays unchanged if correction is refused.
    """
    if draft.source != current:
        raise ImtRefusal("stale_draft")
    evidence = edge_evidence(image, current)
    return measure_boundaries(
        current, draft.policy, lumen_intima, media_adventitia, evidence, revision=draft.revision + 1
    )
