"""Read exactly one indexed classic CT/MR frame, never a whole stack."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from pydicom.pixels.utils import pixel_array

from echo_personal_tool.domain.models.ctmr_stack import StackFrameRef
from echo_personal_tool.infrastructure.ctmr_index import (
    _frame,
    _probe_direct_pixel_spec,
    _read_classic_header_with_stream,
    _stamp,
    lookup_verified_entry,
    remember_verified_ref,
)
from echo_personal_tool.infrastructure.file_identity import FileIdentity

_DEFAULT_PIXEL_ARRAY = pixel_array


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


def _resolve_verified_entry(
    ref: StackFrameRef,
    identity: FileIdentity,
) -> tuple[bool, tuple[int, str] | None]:
    """Validate header against ref via cache, falling back to full header parse."""
    if _stamp(identity) != ref.file_stamp:
        return False, None
    entry = lookup_verified_entry(ref)
    if entry is not None and entry[0] == ref:
        return True, entry[1]
    fh = None
    try:
        ds, fh = _read_classic_header_with_stream(ref.path)
        parsed = _frame(ds, ref.path, identity)
        if parsed != ref:
            return False, None
        direct_spec = _probe_direct_pixel_spec(fh, ds, parsed, identity.size) if fh is not None else None
        remember_verified_ref(parsed, direct_spec)
        return True, direct_spec
    finally:
        if fh is not None:
            fh.close()


def read_ctmr_slice(ref: StackFrameRef, cancelled: Callable[[], bool] = lambda: False) -> np.ndarray:
    """Decode one exact local frame as raw stored values; no rescale/VOI applied."""
    if cancelled():
        raise SliceReadCancelled
    if not source_is_current(ref):
        raise SliceSourceChanged
    identity = FileIdentity.capture(ref.path)
    # Revalidate the indexed SOP, study, series, encoding and geometry before allocating.
    ok, direct_spec = _resolve_verified_entry(ref, identity)
    if not ok or not source_is_current(ref):
        raise SliceSourceChanged
    if cancelled():
        raise SliceReadCancelled
    if direct_spec is not None and pixel_array is _DEFAULT_PIXEL_ARRAY:
        offset, dtype_str = direct_spec
        dtype = np.dtype(dtype_str)
        expected_bytes = ref.rows * ref.columns * dtype.itemsize
        with ref.path.open("rb") as fh:
            fh.seek(offset)
            raw = fh.read(expected_bytes)
        if len(raw) != expected_bytes:
            raise ValueError("unexpected_slice_shape")
        pixels = np.frombuffer(raw, dtype=dtype).reshape(ref.rows, ref.columns).copy()
    else:
        pixels = pixel_array(ref.path, index=ref.local_frame)
    if cancelled():
        raise SliceReadCancelled
    if not source_is_current(ref):
        raise SliceSourceChanged
    if pixels.shape != (ref.rows, ref.columns):
        raise ValueError("unexpected_slice_shape")
    if isinstance(pixels, np.ndarray) and pixels.flags.c_contiguous and pixels.flags.owndata:
        return pixels
    return np.array(pixels, copy=True, order="C")
