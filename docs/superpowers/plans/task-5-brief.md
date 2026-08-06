# Task 5: Localizations for M-mode Banner

**Files:**
- Modify: `src/echo_personal_tool/infrastructure/locales/en.json`
- Modify: `src/echo_personal_tool/infrastructure/locales/ru.json`

**Interfaces:**
- Consumes: (none)
- Produces: New localization strings for M-mode banner

## Steps

### Step 1: Add English localizations

Add to `src/echo_personal_tool/infrastructure/locales/en.json`:

```json
{
  "properties.calibration.mmode_depth": "depth:",
  "properties.calibration.mmode_time": "time:",
  "properties.calibration.mmode_partial_no_depth": "no depth deltas",
  "properties.calibration.mmode_partial_no_time": "no time deltas"
}
```

### Step 2: Add Russian localizations

Add to `src/echo_personal_tool/infrastructure/locales/ru.json`:

```json
{
  "properties.calibration.mmode_depth": "глубина:",
  "properties.calibration.mmode_time": "время:",
  "properties.calibration.mmode_partial_no_depth": "нет дельт глубины",
  "properties.calibration.mmode_partial_no_time": "нет дельт времени"
}
```

### Step 3: Commit

```bash
git add src/echo_personal_tool/infrastructure/locales/en.json src/echo_personal_tool/infrastructure/locales/ru.json
git commit -m "feat(i18n): add M-mode banner localizations for depth/time"
```

## Report

Write your report to `/home/areatu/ECHO2026/docs/superpowers/plans/task-5-report.md` with:
- Status: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, or BLOCKED
- Commits made
- Any concerns
