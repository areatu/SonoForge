# Task 5 Report: Localizations for M-mode Banner

**Status:** DONE

## What was implemented

Added 4 new localization strings for the M-mode banner in both English and Russian locale files.

## Files changed

- `src/echo_personal_tool/infrastructure/locales/en.json` — added 4 English strings
- `src/echo_personal_tool/infrastructure/locales/ru.json` — added 4 Russian strings

## New keys

| Key | English | Russian |
|-----|---------|---------|
| `properties.calibration.mmode_depth` | `depth:` | `глубина:` |
| `properties.calibration.mmode_time` | `time:` | `время:` |
| `properties.calibration.mmode_partial_no_depth` | `no depth deltas` | `нет дельт глубины` |
| `properties.calibration.mmode_partial_no_time` | `no time deltas` | `нет дельт времени` |

## Verification

- Both JSON files validated as correct JSON (`json.load` succeeded)
- All 4 keys present in both locales with expected values

## Commit

- `e0d97f9` — `feat(i18n): add M-mode banner localizations for depth/time`
