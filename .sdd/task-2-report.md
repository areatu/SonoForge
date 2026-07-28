# Task 2 Report: Translate Strain Window and Curves

**Status:** DONE  
**Commit:** `6fea2e7`

## Changes Made

### strain_curves_view.py
- Added `from echo_personal_tool.infrastructure.i18n import tr`
- Replaced `setLabel("bottom", "Время(ms)")` → `setLabel("bottom", tr("strain.time_axis"))`
- Replaced 6 hardcoded Russian values in `SEGMENT_NAMES_RU` dict with `tr()` calls

### strain_window.py
- Added `from echo_personal_tool.infrastructure.i18n import tr`
- Replaced 6 values in `AHA_SEGMENT_NAMES_RU` dict with `tr()` calls
- Replaced 16 values in `SEGMENT_LABELS_RU` dict with `tr()` calls
- Replaced 6 values in `outer_labels` dict with `tr()` calls
- Replaced summary table title and 9 row_defs entries with `tr()` calls
- Fixed `update_values()` unit comparisons to use `tr()` instead of hardcoded Russian
- Replaced 15 ControlPanel widget strings (group boxes, radio buttons, buttons) with `tr()` calls
- Replaced QC placeholder label with `tr()` call
- Replaced QC segment names and fallback in `_populate_qc_checkboxes()` with `tr()` calls
- Replaced 3 file dialog titles with `tr()` calls

## Verification
- `grep` for Russian characters: only comments remain (no string literals)
- Both files compile cleanly with `py_compile`
