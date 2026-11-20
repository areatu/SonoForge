"""Gradation of a report value against the handbook (issue 277, spec §4.7).

The report rows carry their gradation as data (``ReportValue.norm_grade``) so
the PDF sheet can paint the norm dot next to the value and the preview card
can repeat it — the same handbook scale the panel rows and the S2 card show.
The lookup reuses the report's own label table, so the dot always agrees with
the norm column next to it.

Kept in its own module (not in :mod:`report_builder`) because the builder sits
at the module-size ceiling of ``scripts/check_class_size.py``.  The two modules
reference each other, so the builder's lookup table is imported lazily inside
the function to keep the import graph acyclic.
"""

from __future__ import annotations

def norm_grade_for(
    label: str,
    value: float | None,
    sex: str = "",
    *,
    norm_label: str | None = None,
    scale: float | None = None,
) -> str:
    """Gradation name of a value («Норма», «Лёгкое» …); ``""`` when unbound.

    The same handbook lookup the norm text uses (the report's label table +
    the gradation cuts of the parameter).  Empty when the label has no
    handbook binding, the value is missing, or the value falls outside every
    cut — the dot then stays off, exactly as on the panel rows.
    """
    # Lazy: this module and report_builder reference each other, so the
    # builder's lookup table is imported here at call time, not at import.
    from echo_personal_tool.domain.services.report_builder import (
        _LABEL_TO_PARAM_ID,
        _reference_store,
        _scale_for,
        is_female,
    )

    if value is None:
        return ""
    key = norm_label or label
    param_id = _LABEL_TO_PARAM_ID.get(key.casefold().strip())
    if param_id is None:
        return ""
    store = _reference_store()
    if store is None:
        return ""
    resolved_scale = _scale_for(key) if scale is None else scale
    ref_value = value * resolved_scale
    female = is_female(sex)
    for _topic, _pathology, _gradation, param in store.search(param_id):
        if param.id != param_id:
            continue
        for gradation in param.gradations:
            rng = (gradation.range_female if female else gradation.range_male) or gradation.range_male
            if rng is None:
                continue
            low_ok = rng.low is None or ref_value >= rng.low
            high_ok = rng.high is None or ref_value <= rng.high
            if low_ok and high_ok:
                return gradation.name
        return ""
    return ""
