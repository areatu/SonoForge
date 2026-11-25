"""View-recognition corpus assembly helpers (pure, no Qt / no IO).

Pure functions over :class:`~echo_personal_tool.domain.models.view_recognition.ViewRecognitionSample`
sequences: stratified train/val splitting and corpus validation. The
manifest schema itself lives in
:mod:`echo_personal_tool.domain.models.view_recognition`; this module adds
the deterministic assignment and the checks that make a corpus usable for
training (#639 step 1).

Splitting is stratified by view so every class keeps a representative share
of the validation set, and is fully deterministic for a fixed seed — the same
corpus always yields the same assignment, which keeps a trained model's
validation numbers reproducible.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence

from echo_personal_tool.domain.models.view_recognition import (
    KNOWN_VIEWS,
    MANIFEST_SCHEMA_VERSION,
    SPLIT_NAMES,
    UNKNOWN_VIEW,
    ViewRecognitionManifest,
    ViewRecognitionSample,
)


def split_corpus(
    samples: Sequence[ViewRecognitionSample],
    *,
    val_ratio: float,
    seed: int,
    views: Sequence[str] = KNOWN_VIEWS,
) -> tuple[tuple[ViewRecognitionSample, ...], tuple[ViewRecognitionSample, ...]]:
    """Split ``samples`` into deterministic, view-stratified ``(train, val)``.

    For every view the members are shuffled with ``random.Random(seed)`` and
    the first ``ceil(len(group) * val_ratio)`` go to validation; a single-member
    group goes entirely to train (a one-sample class has nothing to validate
    against). Samples whose view is not in ``views`` (or is
    :data:`UNKNOWN_VIEW`) are grouped separately and follow the same rule, so
    the split never silently drops them.

    Returns a ``(train, val)`` tuple of sample tuples in a deterministic order
    (train keeps the original sample order within each view group, val likewise).
    """
    if not 0.0 <= val_ratio < 1.0:
        raise ValueError(f"val_ratio must be in [0, 1), got {val_ratio}")
    groups: dict[str, list[ViewRecognitionSample]] = {view: [] for view in views}
    groups[UNKNOWN_VIEW] = []
    for sample in samples:
        groups.setdefault(sample.view, []).append(sample)

    rng = random.Random(seed)
    train_samples: list[ViewRecognitionSample] = []
    val_samples: list[ViewRecognitionSample] = []
    extra_views = tuple(sorted(set(groups) - set(views) - {UNKNOWN_VIEW}))
    for view in (*views, *extra_views, UNKNOWN_VIEW):
        members = groups.get(view) or []
        if not members:
            continue
        shuffled = list(members)
        rng.shuffle(shuffled)
        n_val = int(round(len(shuffled) * val_ratio))
        if view not in views:
            # Unknown-view samples are a diagnostic group: keep at most one in
            # val so the split shape stays predictable.
            n_val = min(n_val, 1)
        val_group = sorted(shuffled[:n_val], key=lambda s: s.sample_id)
        train_group = sorted(shuffled[n_val:], key=lambda s: s.sample_id)
        train_samples.extend(train_group)
        val_samples.extend(val_group)
    return tuple(train_samples), tuple(val_samples)


def build_manifest(
    samples: Sequence[ViewRecognitionSample],
    *,
    class_names: Sequence[str] = KNOWN_VIEWS,
    schema_version: int | None = None,
) -> ViewRecognitionManifest:
    """Assemble a :class:`ViewRecognitionManifest` from assembled samples.

    ``schema_version`` defaults to the current schema; callers that build a
    corpus from v1 data keep the default and let the manifest report v2.
    """
    return ViewRecognitionManifest(
        samples=tuple(samples),
        schema_version=schema_version if schema_version is not None else MANIFEST_SCHEMA_VERSION,
        class_names=tuple(class_names),
    )


def validate_corpus(
    samples: Sequence[ViewRecognitionSample],
    *,
    class_names: Sequence[str] = KNOWN_VIEWS,
    require_train: bool = True,
) -> list[str]:
    """Return a list of human-readable problems with a corpus (empty = valid).

    Checks that matter for training a classifier: every sample has a
    non-empty id / path / view, views come from ``class_names`` or the
    reserved :data:`UNKNOWN_VIEW` fallback (kept for audit, ignored by
    per-class metrics), split assignments are in :data:`SPLIT_NAMES`, and —
    when ``require_train`` — the corpus actually has training samples (a
    corpus without training data is useless; a missing validation split is
    legitimate when ``val_ratio`` was 0).
    """
    problems: list[str] = []
    known = set(class_names) | {UNKNOWN_VIEW}
    for i, sample in enumerate(samples):
        if not sample.sample_id:
            problems.append(f"sample[{i}]: empty sample_id")
        if not sample.source_path:
            problems.append(f"sample[{i}]: empty source_path")
        if not sample.view:
            problems.append(f"sample[{i}]: empty view")
        elif sample.view not in known:
            problems.append(f"sample[{i}]: unknown view {sample.view!r}")
        if sample.split not in SPLIT_NAMES:
            problems.append(f"sample[{i}]: invalid split {sample.split!r}")
    if require_train and not any(s.split == "train" for s in samples):
        problems.append("corpus has no samples in split 'train'")
    return problems


def summarize_corpus(
    samples: Sequence[ViewRecognitionSample],
    *,
    class_names: Sequence[str] = KNOWN_VIEWS,
) -> dict[str, dict[str, int]]:
    """Per-view sample counts, broken down by split.

    The report shape is closed over ``class_names`` plus the
    :data:`UNKNOWN_VIEW` bucket so a dropped view stays visible in the summary
    instead of silently missing from the counts.
    """
    counts: dict[str, dict[str, int]] = {
        view: {split: 0 for split in SPLIT_NAMES} for view in (*class_names, UNKNOWN_VIEW)
    }
    for sample in samples:
        bucket = counts.setdefault(sample.view, {split: 0 for split in SPLIT_NAMES})
        bucket[sample.split] = bucket.get(sample.split, 0) + 1
    return counts


def iter_samples_in_split(
    samples: Iterable[ViewRecognitionSample],
    split: str,
) -> list[ViewRecognitionSample]:
    """Return the samples of ``samples`` assigned to ``split``, in input order."""
    return [s for s in samples if s.split == split]
