# Task 5 Report: «3 Point Contour» Overview Screen (§5.3 п.2, P1)

**Status:** DONE
**Estimate:** 3–5 days; core implementation delivered in this session.

## Acceptance criteria (from plan §5.3)

| Criterion | Status |
|---|---|
| Three panels (frame + contour + ECG strip) for A4C/A2C/A3C | ✅ `_ViewCard` per view, ED frame background, ED (red) + ES (green dashed) contours, endo kernel scatter, mini ECG strip with ED/ES markers |
| Bull's-eye (18-segment) | ✅ shared `BullseyeWidget` driven by **`StrainStudy.bullseye_segments()`** (same merge the protocol report uses), so UI and report can never disagree |
| Summary ribbon (GLS_AV large, per-view GLS chips) | ✅ large GLS_AV top-left, per-view chips with QC-coloured left border + status mark |
| Per-view status list in one screen | ✅ three-line rich-text list at the bottom: mark, view, GLS, status, AVC source, ED/ES, QC coverage |
| Offscreen render testable | ✅ 8 tests in `tests/unit/test_ste_overview_screen.py` run on `QT_QPA_PLATFORM=offscreen`, end-to-end render-to-pixmap included |
| All data from `StrainStudy`, no recomputation | ✅ `OverviewScreen.set_study()` reads analyses only; no strain math lives in the widget |

## Files added/changed

**New:**
- `src/echo_personal_tool/ui/ste/__init__.py` — new subpackage (plan §6.3)
- `src/echo_personal_tool/ui/ste/overview_screen.py` — `OverviewScreen` widget, `ViewSnapshot` dataclass, `_ViewCard` (per-view thumbnail)
- `tests/unit/test_ste_overview_screen.py` — 8 tests: construction, empty state, per-view numbers from study, 18-segment bull's-eye merge, snapshot contour/kernel/ECG rendering, missing-ECG honesty, QC marks, offscreen pixmap render

**Changed:**
- `src/echo_personal_tool/ui/strain_window.py` — added `_overview` stacked page (index 2), radio mode "3 views (overview)" wired to `display_mode_changed`, `show_overview()`, `_refresh_overview()`, `_capture_view_snapshot()` that stores per-view ED frame/contours/kernels/ECG into `ViewSnapshot`; palette cycle (`C`) and palette/ttp selectors also drive the overview bull's-eye; palette kept in sync between the contour-page bull's-eye and the overview bull's-eye; study adoption refreshes the overview
- `src/echo_personal_tool/ui/control_panel.py` — added radio `_mode_overview` labeled `strain.mode_overview`
- `src/echo_personal_tool/infrastructure/locales/{ru,en}.json` — three new keys: `strain.mode_overview`, `strain.overview_views_measured`, `strain.overview_segments_missing`
- `tools/qtstub/mkstub.py` — bug fix: empty-stub path (for NSS/SMIME/Xtst etc.) was returning before writing the `.so`, which made headless WebEngine imports fail locally. Now emits a real empty shared object with version script when there are no undefined symbols (see ELF note in plan §5.4).
- `docs/screenshots/ste-overview-3views.png` — reference offscreen render of the new screen (three synthetic views + bullseye)

## Design notes (aligned with plan §6)

1. **One source of numbers.** `OverviewScreen` only reads from `StrainStudy`; the per-view GLS on a card is `analysis.gls`, the ribbon GLS_AV is `study.gls_average()`, the bull's-eye is `study.bullseye_segments()` merged through `study.segment_sources()`. There is no second strain computation anywhere in the UI.
2. **No fabricated data.** Views that were never analysed keep a "No data" placeholder and their chip says `A3C --`; missing ECG → ECG strip hidden entirely (the synthetic-ECG rule from §6.5 is honoured).
3. **Status marks.** Same glyphs (`●/⚠/■`) and colours (`#4caf50 / #ffb300 / #ef5350`) as the meta bar and the summary table — so the mark on a card is identical to the mark next to its number.
4. **Visual layer borrows frame memory.** `ViewSnapshot` keeps a *reference* (not a copy) to the ED frame, contours and endo positions captured at `show_result()` time — the overview card draws them on demand without re-running the tracker.
5. **Dark theme, large numbers, minimum chrome.** Background `#0d1318`, cards `#0a0f14` with `#263238` border, GLS value `#ffd54f` bold 22pt, green/amber/red QC accents — matches the §6.1 principle "large numbers, minimum borders" shared by GE / Philips / Samsung.
6. **Palette/TTP controls wired through.** The same `palette_changed` and `ttp_mode_toggled` signals from the control panel drive both the old contour-page bull's-eye and the overview bull's-eye, so cycling palettes with `C` updates both and they can never disagree.

## Tests

```
tests/unit/test_ste_overview_screen.py ........ (8 passed)
```

Plus regression sweep on strain-window / ui / entry-flow / report / phantom / QC / segment-map tests — ~320 tests, all green.

## Caveats / follow-up (not in this task)

- The existing `_panel_a2c` / `_panel_dao` placeholders in the contour (2×2) page still show "No data" until multi-view contour animation is implemented — that's §5.3 п.5/п.8 (queue / headless), not this task. The new overview screen is additive: it reads data the study already accumulates, independent of the 2×2 grid.
- Hover/click cross-link (bullseye ↔ curve ↔ card) is listed as §5.3 п.9 (UI remainder, P2) and is not wired yet.
- Strain band and displacement vectors are also §5.3 п.9.
