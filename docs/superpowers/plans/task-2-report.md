# Task 2 Report: Add area tool mode selector to preferences dialog

## What was implemented

Added a QComboBox (`_area_tool_mode_combo`) to the Measurement tab of `UserPreferencesDialog` allowing users to select between "click" (polygon) and "freehand" drawing modes for the area tool.

### Changes:
1. **`user_preferences_dialog.py`** — Added `_area_tool_mode_combo` QComboBox with two items ("click"/"freehand"), initialized from `current.area_tool_mode`. Added `addRow` to the Measurement form layout. Wired `area_tool_mode=str(self._area_tool_mode_combo.currentData())` into `_on_accept`.
2. **`ru.json`** — Added 3 i18n keys: `preferences.area_tool_mode`, `preferences.area_mode_click`, `preferences.area_mode_freehand`.
3. **`en.json`** — Added same 3 i18n keys in English.
4. **`test_presentation_user_preferences_dialog.py`** — Added `TestAreaToolModeCombo` class with 5 tests.

## Test results

All 5 new tests passed (GREEN):
- `test_combo_exists` — verifies `_area_tool_mode_combo` attribute exists
- `test_combo_has_two_items` — verifies combo has exactly 2 items
- `test_combo_defaults_to_click` — verifies default selection is "click"
- `test_combo_selects_freehand_when_prefs_set` — verifies combo reflects prefs with `area_tool_mode="freehand"`
- `test_on_accept_saves_area_tool_mode` — verifies `_on_accept` saves the selected mode

All 20 tests in the dialog test file passed. Lint clean. JSON valid.

## TDD evidence
- **RED**: 5 tests failed with `AssertionError: assert False` / `AttributeError: 'UserPreferencesDialog' has no attribute '_area_tool_mode_combo'`
- **GREEN**: All 5 tests passed after implementation

## Files changed
- `src/echo_personal_tool/presentation/user_preferences_dialog.py`
- `src/echo_personal_tool/infrastructure/locales/ru.json`
- `src/echo_personal_tool/infrastructure/locales/en.json`
- `tests/unit/test_presentation_user_preferences_dialog.py`

## Self-review findings
None — implementation follows the plan exactly, matches existing dialog patterns.

## Commit
`f0553c9` — `feat: add area tool mode selector to preferences dialog`
