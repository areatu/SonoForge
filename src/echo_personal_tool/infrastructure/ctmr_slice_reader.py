"""Read exactly one indexed classic CT/MR frame, never a whole stack."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from pydicom.pixels.utils import pixel_array

from echo_personal_tool.domain.models.ctmr_stack import StackFrameRef
from echo_personal_tool.infrastructure.ctmr_index import _frame, _read_classic_header, _stamp
from echo_personal_tool.infrastructure.file_identity import FileIdentity


class SliceReadCancelled(Exception):
    """Cooperative cancellation; native decoders cannot be forcibly interrupted."""


class SliceSourceChanged(Exception):
    """Indexed file no longer matches its identity, or changed while reading."""


def source_is_current(ref: StackFrameRef) -> bool:
    """Best-effort stat check, not a content hash or atomic file snapshot."""
    try:
        return (
            bool(ref.file_stamp)
            and not ref.path.is_symlink()
            and _stamp(FileIdentity.capture(ref.path)) == ref.file_stamp
        )
    except OSError:
        return False


def read_ctmr_slice(ref: StackFrameRef, cancelled: Callable[[], bool] = lambda: False) -> np.ndarray:
    """Decode one exact local frame as raw stored values; no rescale/VOI applied."""
    if cancelled():
        raise SliceReadCancelled
    if not source_is_current(ref):
        raise SliceSourceChanged
    identity = FileIdentity.capture(ref.path)
    # Revalidate the indexed SOP, study, series, encoding and geometry before allocating.
    if _frame(_read_classic_header(ref.path), ref.path, identity) != ref or not source_is_current(ref):
        raise SliceSourceChanged
    if cancelled():
        raise SliceReadCancelled
    pixels = pixel_array(ref.path, index=ref.local_frame)
    if cancelled():
        raise SliceReadCancelled
    if not source_is_current(ref):
        raise SliceSourceChanged
    if pixels.shape != (ref.rows, ref.columns):
        raise ValueError("unexpected_slice_shape")
    return np.array(pixels, copy=True, order="C")
