"""Verify that Linux logic and GUI jobs form a lossless marker partition."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

# QH-1e: 111 synthetic cases; QH-4a: 4 crash-diagnostic cases;
# QH-1b.2 slice 1: 20 BSA-freshness cases (tests/unit/test_bsa_freshness.py);
# QH-1b.2 slice 2: 53 cases for the single manual BSA and the persisted BSA
# provenance (tests/unit/test_bsa_provenance.py plus controller/panel/report/PDF
# and persistence additions). No file changed its gui marker.
# QH-1c/QH-1d: 12 manual-input persistence cases (6 gui: storage-dialog import
# preview x2, persistence-disk preview/barrier x4; 6 not-gui: repository codec
# and migration x5, calculator-input restore x1). test_current_schema_matches_codec
# was added independently on both sides and merged into one; no new test files.
# Tracker: 23 logic cases for the plan-driven Projects sync engine
# (tests/unit/test_project_sync.py) — gui counts unchanged.
# Tracker fix: 8 more logic cases for the owner-type-tolerant project lookup
# (tests/unit/test_project_sync.py) — gui counts unchanged.
# Tracker fix 2: 5 logic cases pinning every GraphQL operation's variable types to the
# Projects v2 schema (the `$option: ID!` mismatch that killed the first board sync), same
# file — gui counts unchanged.
# Manual Doppler HR: 18 logic + 10 GUI cases in existing test files.
# QH-4a ER-07 / QH-1d: 7 not-gui cases in existing files: PDF failures
# (2 exporters x 3 failure stages) and restored manual RAP recomputation (1).
# No GUI markers or test-file membership changed.
# QH-1d: 1 not-gui case proving the restored manual RAP survives a restart
# from disk (tests/unit/test_measurement_repository.py).
# QH-1b.2 slice 3a: 10 not-gui Simpson-freshness cases
# (tests/unit/test_simpson_freshness.py). No GUI markers changed.
# UI-0 PR-1 (design tokens): 63 not-gui cases in four new files (token
# vocabulary and palettes, system colour scheme, colour ratchet, contrast
# check) + 2 GUI cases in tests/unit/test_presentation_dark_theme.py (the
# system theme of Windows, mocked registry). No existing file changed its
# marker; gui_files stays 168.
# QH-4a ER-09a: 4 not-gui retrieval code cases
# (tests/unit/test_dicom_retrieve_service.py). Heart-rate static message
# (ER-09b) only reworded an assertion — no new tests, no marker changes.
# QH-1b.2 slices 3b/3c: 15 not-gui freshness cases
# (tests/unit/test_doppler_freshness.py x9, tests/unit/test_derived_freshness.py
# x6). No GUI markers or test-file membership changed.
# UI-0 PR-1 (design tokens): 73 not-gui cases in four new files (token
# vocabulary and palettes, the compatibility facade of the former flat token
# module, system colour scheme, colour ratchet, contrast check) and 9 GUI
# cases in the existing gui file tests/unit/test_presentation_dark_theme.py
# (the system theme of Windows with a mocked registry, the stylesheet pins
# against the sheet of the previous release). TP-0 PR-1: 52 not-gui catalog
# cases (tests/unit/test_measurement_catalog.py). No GUI file added.
# TP-0 PR-2 (tool layout v3): 21 not-gui cases in the new file
# tests/unit/test_tool_layout_v3.py and 3 GUI cases in the existing gui files
# (the migration of the layout in the measures menu and in the preferences).
# TP-0 PR-3 (ASE 2025 Table 6): 226 not-gui cases in the new file
# tests/unit/test_ase_table6.py — the measurement table is checked row by row.
# UI-0 PR-2 (the Graphite theme): 40 not-gui cases in the new file
# tests/unit/test_theme_graphite.py (the theme is selectable, its contrast is
# enforced) and 26 GUI cases in the new file tests/unit/test_ui_screenshot_base.py
# (the screenshot base and the fringes of the subpixel antialiasing) — one GUI
# file added.
# UI-0 PR-3 (the shell on tokens): 13 GUI cases in the new file
# tests/unit/test_shell_tokens.py (no colour literal in the shell stylesheets,
# the glyphs of the bar/tabs/rail take text.1 and follow a theme switch, the
# status-bar labels take state.warn/text.3), 6 GUI cases in the existing
# tests/unit/test_presentation_dark_theme.py (TestGetThemeTokens) and 2 GUI
# cases in the existing tests/unit/test_presentation_main_window.py
# (TestStatusBarTokens) — one GUI file added.
# UI-0 PR-4 (panels and menus): 4 GUI cases in existing test files
# (calculator provenance, the next-step marker in the tools panel and menu,
# and worksheet paper states) plus 3 non-GUI cases (fixed semantic colors and
# cross-theme marker contrast). No test-file membership or GUI-file count changed.
# UI-0 PR-5 (the reference on tokens): 6 GUI cases in the new file
# tests/unit/test_reference_tokens.py (the reference stylesheets paint only
# the token values of the active theme and follow a theme switch, the close
# glyph takes text.1, the clinical gradation colours stay pinned) — one GUI
# file added.
# UI-0 PR-6 (Orthanc views on tokens): 4 GUI cases in the new file
# tests/unit/test_orthanc_tokens.py (loader/stylesheet token audit, fixed
# palette delegate colours, server-settings warning styles) — one GUI file
# added.
# UI-5 PR-0: 11 logic cases for LVM reference ranges, method round-trip and UA-14.
# QH-1c remap: 14 logic + 6 GUI cases; existing GUI files only.
# QH-1c faults: 8 logic (repository + harness guards), 4 GUI (retry).
# UI-1 PR-1 (window chrome hit-test, Win32 & fallback native frame): 63 not-gui
# cases in tests/unit/test_window_chrome_hit_test.py (all 13 Zone values,
# maximized vs normal, interactive caption widgets, 100/150/200% scaling,
# Win32 HT* mapping, WM_NCCALCSIZE, WM_NCHITTEST Snap Layouts HTMAXBUTTON,
# non-client hover/press/release/leave, and DWM attributes) plus 11 GUI cases
# across existing GUI files (test_user_preferences.py x3,
# test_presentation_user_preferences_dialog.py x2, test_system_bar.py x4,
# test_main_window_layout.py x2). No new GUI file added; gui_files stays 172.
# UI-1 PR-2 (the window title bar: the study tabs, the «+», the Ctrl+K command
# field, the app menu and the 46 px window controls): 8 not-gui cases in the new
# file tests/unit/test_command_catalog.py, 22 GUI cases in the new file
# tests/unit/test_title_bar.py and 8 GUI cases in existing GUI files — the command
# handlers, Ctrl+K, the submitted query, the unknown query, the window controls, the
# app menu, the fullscreen kiosk and the zones of the new row
# (test_main_window_layout.py x7) and the «+» opening a tab
# (test_main_window_tabs.py x1). No existing file changed its marker;
# gui_files 172 -> 173.
# QH-1c CI portability: 1 logic case for unsupported mount probes (fail closed).
# QH-4b: 1 logic case for the exact domain -> infrastructure import-edge ratchet.
# TP-2 PR-1 (measurement panel 2.0 framework): 19 not-gui cases in the new
# tests/unit/test_tool_panel_view.py, 13 GUI cases in the new
# tests/unit/test_tool_panel_v2.py — one GUI file added.
#
# UI-1 PR-3 + UI-2 PR-1 (patient row and button split, LayoutConfig v2): 60 not-gui
# cases in the new file tests/unit/test_layout_presets.py (the 16 migration
# combinations, the v2 document, the slot table invariants) and 16 GUI cases — 13 in
# the new file tests/unit/test_layout_v2_window.py, 2 in test_main_window_extended.py
# (slot assembly), 1 in test_system_bar.py (42 px row). gui_files 173 -> 174.
# UI-2 PR-2 (settings section, presets, layout menu): 5 not-gui cases in
# tests/unit/test_layout_presets.py (resolve_document; the flags_for projection
# test died with the v1 flags, -1/+6) and 8 GUI cases net — the new file
# tests/unit/test_layout_settings.py x10 (preset tiles, tool-buttons/labels
# combos, status-bar/focus flags, dialog round-trip), test_layout_v2_window.py
# +6 (preset radios, tools submenu, the interim row/panel, the 300 ms switch
# gate), test_main_window_extended.py -5 and test_presentation_main_window.py -3
# (the v1 TestLayoutConfig classes died with the flags). gui_files 175 -> 176.
# UI-0 PR-7b (overlay tail): 34 not-gui cases in the new file
# tests/unit/test_overlay_tokens.py — the pinned colours of the `overlay.*`
# group, its marker cycle and the "no raw literal left" gate over the nine
# migrated painters. The migrated files were already GUI files or pure-Qt
# widgets whose tests live in existing modules; test_multiview_widgets.py now
# reads the cycle from the palette instead of a local copy. gui_files 176 (no
# new GUI file), total 7853 -> 7887, not_gui 4380 -> 4414.
# UI-2 PR-3 (the tool row over the snapshot and the catalog-driven rail rebase):
# test_layout_presets.py gained 77 and dropped 27 not-gui cases (net +50: the
# slot/preset inversions for the row/rail); test_layout_v2_window.py +5 GUI
# (the row wiring over the snapshot), test_main_window_layout.py -1,
# test_presenter_view.py -2 and test_shell_tokens.py -1 GUI (the retargets).
# The deleted activity bar removed the TestActivityBarFontMetrics class
# (test_presentation_extended.py -8, then -2 more on the CI fix) and the
# _on_activity_action cases became _on_tool_button_requested one-for-one
# (test_presentation_main_window.py, no change). gui_files 176 (no changes),
# gui 3473 -> 3464, not_gui 4380 -> 4464, total 7853 -> 7928. The 7887 audit
# above counted only the overlay tail and missed these rebase effects.
# TP-1 (нomenklatura RU xor EN + mm/cm D-12 + EN-голдены + flow_label text/PDF):
# not-gui goldens and contract tests grew across the nine commits — the new
# test_tp1_en_goldens.py (4 cases), the D-12/length_decimals contract block in
# test_nomenclature.py, the report/PDF/overlay label goldens in
# test_measurement_report_formatter/v2, test_report_builder, test_qh1e_formulas
# and test_measurement_panel. No new GUI file and no gui-marker change, so gui
# and gui_files are unchanged; not_gui 4464 -> 4541, total 7928 -> 8005.
# TP-3 PR-1 (protocol domain): 34 not-gui cases in two new files
# (11 in test_protocols.py — model, progress(), lock reasons, aggregate; 23 in
# test_protocol_definitions.py — the six protocols against the catalog and the
# A-04/A-07/A-08/Q-05 acceptance scenarios). No GUI markers changed, so gui
# and gui_files are unchanged; not_gui 4541 -> 4575, total 8005 -> 8039.
# TP-2 gate (panel 2.0 default-on): 6 GUI cases in test_tool_panel_v2.py
# (default-on, A-03 favourites, A-13 arrows, section progress, A-16 widths).
# No new GUI file and no marker flip, so not_gui and gui_files stay as above;
# gui 3464 -> 3470, total 8039 -> 8045.
# TP-3 PR-2 (protocol runner and row status): 19 not-gui cases in two new files
# (7 in tests/unit/test_tool_status.py — value formatting, stale/locked/QC
# states; 12 in tests/unit/test_protocol_runner.py — the automaton: start, arm,
# auto-advance, two-stage Esc, skip, repeat, shared, stale, study change,
# finish). No GUI markers changed, so gui and gui_files are unchanged;
# not_gui 4575 -> 4594, total 8045 -> 8064.
# UI-5 PR-1 (the S2 norm card without images): 50 not-gui cases in the new
# tests/unit/test_reference_card_model.py (UA-13, the gradations by sex, the
# LVM boundaries of PR-0, the app/reference unit table, the honest empty
# answers, the language, the value formatting and GradeCut) and 20 GUI cases in
# the new tests/unit/test_reference_card.py (no image in the widget tree nor in
# the module source, the card of UA-13, the marker of the scale, the
# «open in reference» signal, the empty states, token-only colours, the repaint
# on a theme switch and the placement) — one GUI file added.
# not_gui 4594 -> 4644, gui 3470 -> 3490, gui_files 176 -> 177,
# total 8064 -> 8134.
# TP-3 PR-2b (study projection): 10 not-gui cases in the new file
# tests/unit/test_study_projection.py (caliper/volume/derived mapping, protocol
# key coverage against MAPPED/UNMAPPED, unmet from calibration), 1 not-gui case
# in tests/unit/test_protocol_runner.py (authored keys on completion) and 1 GUI
# case in tests/unit/test_playback_state.py (the projection debounce emits
# once). No GUI-file membership changed; not_gui 4644 -> 4655, gui 3490 -> 3491,
# total 8134 -> 8146.
# TP-3 PR-3 (protocol UI): 16 not-gui cases in the new files
# tests/unit/test_protocol_session.py (clip context and authored keys reach
# study_projection, statuses re-emit, auto-advance, escape and study change)
# and tests/unit/test_viewer_clip_context.py (the thin viewer adapter: 2d/m/
# doppler contexts, unknown Doppler blocks nothing, clip_view normalisation),
# plus 15 GUI cases in the new files tests/unit/test_protocol_step_bar.py (the
# strip under the snapshot, the RAP chips of Q-04, the >=2 s notification of
# Q-07) and tests/unit/test_protocol_card.py (chooser, step glyphs, lock
# reasons, step activation), plus 5 GUI cases in the existing
# tests/unit/test_presentation_main_window.py (TestProtocolUi: the step bar in
# the column's bottom slot, Esc without a protocol, S skips the armed step, a
# reset ends the protocol). Two GUI files added; not_gui 4655 -> 4671,
# gui 3491 -> 3511, total 8146 -> 8182.
# TP-6 PR-1 (command palette and Alt hints): 5 GUI tests in the new
# tests/unit/test_command_palette.py and 2 cross-platform shortcut tests in
# tests/unit/test_keyboard_shortcuts.py. No marker flips; gui 3491 -> 3496,
# not_gui 4655 -> 4657, gui_files 177 -> 178, total 8146 -> 8153.
# UI-5 PR-3 (bilingual how-to editor): 3 GUI tests in the new
# tests/unit/test_constructor_how_to_dialog.py and 3 in the existing
# tests/unit/test_constructor_metadata_editor.py. The model (3), schema (6),
# reference-data store (1) and card-flow (1) add 11 not-GUI tests. One GUI file
# added; gui 3496 -> 3502, not_gui 4657 -> 4668, gui_files 178 -> 179,
# total 8153 -> 8170.
# UI-5 PR-2 (the handbook window S1): 35 not-GUI cases in the new
# tests/unit/test_reference_topics.py (the view model, the projection mapping and
# the palette entries) and 32 GUI cases in the new
# tests/unit/test_reference_window.py (the window itself and its entry points of
# the main window). One GUI file added; gui 3502 -> 3534,
# not_gui 4668 -> 4703, gui_files 179 -> 180, total 8170 -> 8237.
# TP-3 PR-3 (protocol UI) on top of UI-5 PR-2: the 36 cases described above
# (16 not-GUI in test_protocol_session.py / test_viewer_clip_context.py, 20 GUI
# in test_protocol_step_bar.py / test_protocol_card.py plus TestProtocolUi).
# Two GUI files added; not_gui 4703 -> 4719, gui 3534 -> 3554,
# gui_files 180 -> 182, total 8237 -> 8273.
# UA-07/UA-08 (step-bar acceptance): 3 GUI cases in the existing
# tests/unit/test_presentation_main_window.py (TestUaProtocolAcceptance: the
# auto-advance notification ≥ 2 s in the bar, the bar under the snapshot with
# nothing over the image, and the image regaining the bar height on stop).
# No new GUI file and no marker flip; gui 3554 -> 3557, total 8273 -> 8276.
# TP-4 (post-measurement label picker): 6 not-GUI cases and 14 GUI cases in the
# new tests/unit/test_label_picker.py, plus 3 GUI cases in
# tests/unit/test_user_preferences.py and 1 GUI case in
# tests/unit/test_presentation_user_preferences_dialog.py. One GUI file added;
# gui 3554 -> 3572, not_gui 4719 -> 4725, gui_files 182 -> 183,
# total 8273 -> 8297.
# UI-4.0 report-preview spike on top of TP-4: 10 logic cases in the new
# tests/unit/test_report_render.py (the render_report contract with anchors)
# and 2 GUI regression cases for label-picker placement in
# tests/unit/test_label_picker.py (containment on small bounds / big fonts).
# No files added beyond the TP-4 ones; not_gui 4725 -> 4735,
# gui 3572 -> 3574, gui_files 183, total 8297 -> 8309.
# UI-4 PR-1 (report mode: the switch, the per-tab mode, the A4 preview):
# 23 logic cases — tests/unit/test_report_view_map.py x18 (the pure QPdfView
# layout model moved from the spike), tests/unit/test_tab_session.py x4 (the
# tab's report_mode and its resets), tests/unit/test_keyboard_shortcuts.py x1
# (Ctrl+R) — and 25 GUI cases: the new tests/unit/test_report_preview.py x12
# (the sheet, the debounce, zoom, failures, the QtPdf-missing fallback, the
# cell hit test), tests/unit/test_system_bar.py x6 (TestModeSwitch) and
# tests/unit/test_presentation_main_window.py x7 (TestReportMode, UA-09).
# One GUI file added; not_gui 4735 -> 4758, gui 3574 -> 3599,
# gui_files 183 -> 184, total 8309 -> 8357.
# UI-3 PR-2 (UA-07/UA-08 acceptance, полоса шага): 3 GUI cases in the existing
# gui file tests/unit/test_presentation_main_window.py (the auto-advance
# notification lives in the bar >= 2 s, the bar sits under the snapshot,
# stopping the protocol returns its height to the image).
# No new GUI file and no marker flip; gui 3599 -> 3602, total 8357 -> 8360.
# UI-5 PR-4 (S2 card at the panel rows + norm dots): 5 logic cases
# (3 unit-pair conversion cases in tests/unit/test_reference_card_model.py,
# 2 projection-translation cases in tests/unit/test_reference_topics.py — the
# key->handbook table grew past the LV family, one scope pin was rewritten into
# two pairing invariants) and 12 GUI cases (9 in tests/unit/test_tool_panel_v2.py
# for the hover/key card, the «Нормы» switch and the norm dots — UA-15;
# 3 in tests/unit/test_user_preferences.py for the reference_norm_dots key).
# On top of the merged main (UI-4 PR-1 + UI-3 PR-2 at 8360); no test file
# added; not_gui 4758 -> 4763, gui 3602 -> 3614, gui_files 184,
# total 8360 -> 8377.
# UI-2 PR-4 responsive follow-up (#250): 9 GUI cases (the 7 cases already
# added by the PR plus the narrow classic-gallery and panel-control regressions)
# and 6 non-GUI cases (the 5 cases already added by the PR plus the
# gallery-policy threshold test). All GUI cases stay in existing GUI files; gui_files remains
# 184. The workflow's offscreen GUI shards select and count these tests, and the
# lossless-partition check below rejects collection-only or unexecuted GUI cases.
# On top of UI-5 PR-4: gui 3614 -> 3623, not_gui 4763 -> 4769,
# total 8377 -> 8392.
# UI-4 PR-2 (report sections + «не заполнено»): 7 logic cases in the new
# tests/unit/test_report_sections.py (the union of non-optional protocol
# steps, section status/order/counters, skips the optional IVRT, localized
# labels) and 4 GUI cases in the new
# tests/unit/test_report_sections_panel.py (glyphs/counter, the «измерить»
# signal, the reversible «не оценивалось» mark, no missing rows when done),
# plus 1 GUI case in tests/unit/test_presentation_main_window.py (UA-12:
# «измерить» switches to images and arms the protocol step).
# One GUI file added; not_gui 4769 -> 4776, gui 3623 -> 3628,
# gui_files 184 -> 185, total 8392 -> 8404.
# UI-6 (single-file focus view, §4.8, UQ-02, UD-04, S-02): 28 logic cases in the
# new tests/unit/test_focus_mode.py (what counts as one file, the automatic
# entry, the slot plan of F1, the header facts, the card rows, the floating
# plates, the pointer-driven fade and «Копировать») and 19 GUI cases in the new
# tests/unit/test_focus_view.py (the automatic entry, the F toggle, the layout
# and the hidden panels, the strip and the plates, the fade wiring, the per-tab
# state, the decision with tabs switched off).
# One GUI file added; not_gui 4769 -> 4797, gui 3623 -> 3642,
# gui_files 184 -> 185, total 8392 -> 8439.
# TP-3 projection contract (chambers, Doppler flows, calculator-derived keys):
# 3 non-GUI cases in tests/unit/test_study_projection.py (Simpson area-length
# chambers with indexes, Doppler flows/indices, calculator outputs plus the RAP
# input). No new file and no marker flip; gui_files remains 184 and the GUI
# inventory is untouched, so gui stays 3623 and not_gui 4769 -> 4772,
# total 8392 -> 8395.
# UI-4 PR-2 (report sections + the «не заполнено» column): 7 logic cases in the
# new tests/unit/test_report_sections.py (the union of non-optional protocol
# steps, section status/order/counters, the skipped optional IVRT, localized
# labels) and 5 GUI cases — 4 in the new tests/unit/test_report_sections_panel.py
# (glyphs and counter, the «измерить» signal, the reversible «не оценивалось»
# mark, no missing rows when done) and 1 in the existing
# tests/unit/test_presentation_main_window.py (UA-12: «измерить» switches to
# images and arms the protocol step). One GUI file added.
# Rebased on the merged main (TP-3 at 8395, not on the 8392 audit above):
# not_gui 4772 -> 4779, gui 3623 -> 3628, gui_files 184 -> 185,
# total 8395 -> 8407. Keep this the LAST assignment in the file — Python keeps
# only the final binding, so an update inserted above it is dead code.

# Merge of UI-6 (single-file focus view) onto main with UI-4 PR-2: the branch
# adds 28 logic cases in tests/unit/test_focus_mode.py and 19 GUI cases in the
# new tests/unit/test_focus_view.py on top of the 8407 inventory, so both GUI
# files (the report-sections panel of main and the focus view) count:
# not_gui 4779 -> 4807, gui 3628 -> 3647, gui_files 185 -> 186,
# total 8407 -> 8454.

# UI-7 (A2 study browser on the start page): 20 logic cases in the new
# tests/unit/test_study_browser.py (period matching, status, display title,
# text query, combined filters, sidebar counters) and 8 GUI cases in existing
# files — 7 in tests/unit/test_presentation_start_page.py (table columns and
# detail panel, search/period/source/draft filters, no-results reset,
# select-vs-open, unavailable rows, folder drop, search focus; two older
# cases rewritten to the table contract) and 1 in
# tests/unit/test_start_page_recents.py (saved measurements turn the run row
# into a draft). No new GUI file; not_gui 4807 -> 4827, gui 3647 -> 3655,
# gui_files stays 186, total 8454 -> 8482.

# UI-4 PR-3 («Фразы»: the phrase column of report mode, UQ-08): 43 logic cases —
# the new tests/unit/test_report_phrases.py x27 (the starter set, search,
# insertion at the cursor, the inserted marks, user phrases, document I/O), the
# new tests/unit/test_report_phrase_store.py x14 (empty store, persistence,
# idempotent save, the 200-phrase limit, removal, a corrupt file, import and
# export, the default path, human-readable JSON) and 2 in the existing
# tests/unit/test_tab_session.py (a new tab starts with an empty conclusion,
# a fresh source drops it) — and 18 GUI cases: the new
# tests/unit/test_report_phrases_panel.py x15 (the 336 px column, insertion into
# the conclusion, the user library, language/theme, the editor dialog) and 3 in
# the existing tests/unit/test_presentation_main_window.py (TestReportPhrases:
# a phrase reaches the document the sheet renders, the draft belongs to its tab,
# the window owns the phrase store). One GUI file added; not_gui 4827 -> 4870,
# gui 3655 -> 3673, gui_files 186 -> 187, total 8482 -> 8543.
# Keep this the LAST assignment in the file — Python keeps only the final
# binding, so an update inserted above it is dead code.
# QH-1b.2 slice 3c (PR #259): 5 not-gui provenance cases in the new
# tests/unit/test_provenance_notes.py. No GUI markers or test-file membership
# changed; not_gui 4870 -> 4875, gui 3673 stays, gui_files 187 stays,
# total 8543 -> 8548.

# TP-5 tool settings 2.0 UI: 10 GUI cases — the new
# tests/unit/test_tool_settings_ui.py x7 (read-only builtin, duplicate/undo,
# conflict without force, invalid import, import/export, reset, custom
# section), 2 in tests/unit/test_tool_panel_v2.py (pencil on the built-in,
# ★/👁 in-place editing) and 1 in
# tests/unit/test_presentation_user_preferences_dialog.py (the Tools tab is
# selected on open). One GUI file added; gui 3673 -> 3683, gui_files
# 187 -> 188, not_gui stays 4903, total 8576 -> 8586.

# TP-6 PR-2 (radial menu, A-14): 10 GUI cases in the new
# tests/unit/test_radial_menu.py (clock-face sector math, the 250 ms hold,
# the 24 px jerk, the quick-click fallback, «Ещё…», the centre dismiss, the
# viewer forwarding an idle press and keeping the legacy menu while drawing)
# and 2 logic cases in tests/unit/test_tool_panel_view.py (DEFAULT_RADIAL per
# context, the unknown-context fallback). One GUI file added; not_gui
# 4903 -> 4905, gui 3683 -> 3693, gui_files 188 -> 189, total 8586 -> 8598.
# Keep this the LAST assignment in the file — Python keeps only the final
# binding, so an update inserted above it is dead code.
# TP-6 PR-1 (palette «Протоколы» + A-17 budgets): 2 logic cases in
# tests/unit/test_command_catalog.py (the six protocol entries, the bilingual
# query) and 1 in the new tests/unit/test_palette_perf.py (the 16 ms filter
# budget) — plus 4 GUI cases: 2 in tests/unit/test_command_palette.py
# (protocols first, the «Симпсон» search), 1 in the new
# tests/unit/test_palette_perf.py (the 50 ms p95 panel update) and 1 in
# tests/unit/test_presentation_main_window.py (TestProtocolUi: the palette
# action starts the session). One GUI file added. The refresh also absorbs the
# 5 logic cases of #259 that landed on main without a baseline bump
# (audited 8543 -> main 8548): not_gui 4875 -> 4878, gui 3673 -> 3677,
# gui_files 187 -> 188, total 8548 -> 8555.
# Keep this the LAST assignment in the file — Python keeps only the final
# binding, so an update inserted above it is dead code.
# auto-refresh 2026-10-20 (update_pytest_baseline.py --fix): total 8555 -> 8593, gui 3677 -> 3687, not_gui 4878 -> 4906, gui_files 188 -> 189.
# auto-refresh 2026-10-20 (update_pytest_baseline.py --fix): total 8593 -> 8605, gui 3687 -> 3697, not_gui 4906 -> 4908, gui_files 189 -> 190.
# auto-refresh 2026-10-20 (update_pytest_baseline.py --fix): total 8605 -> 8614, gui 3697 -> 3700, not_gui 4908 -> 4914.
# auto-refresh 2026-10-20 (update_pytest_baseline.py --fix): total 8605 -> 8647, gui 3697 -> 3708, not_gui 4908 -> 4939, gui_files 190 -> 192.
# auto-refresh 2026-10-20 (update_pytest_baseline.py --fix): total 8647 -> 8692, gui 3708 -> 3737, not_gui 4939 -> 4955, gui_files 192 -> 194.
# auto-refresh 2026-10-20 (update_pytest_baseline.py --fix): total 8692 -> 8708, gui 3737 -> 3747, not_gui 4955 -> 4961, gui_files 194 -> 195.
# auto-refresh 2026-10-20 (update_pytest_baseline.py --fix): total 8647 -> 8656, gui 3708 -> 3711, not_gui 4939 -> 4945.
# auto-refresh 2026-10-21 (update_pytest_baseline.py --fix): total 8656 -> 8717, gui 3711 -> 3750, not_gui 4945 -> 4967, gui_files 192 -> 195.
# auto-refresh 2026-10-21 (update_pytest_baseline.py --fix): total 8717 -> 8721, gui 3750 -> 3751, not_gui 4967 -> 4970.
# auto-refresh 2026-10-21 (update_pytest_baseline.py --fix): total 8721 -> 8736, gui 3751 -> 3763, not_gui 4970 -> 4973.
# auto-refresh 2026-10-21 (update_pytest_baseline.py --fix): total 8736 -> 8737, not_gui 4973 -> 4974.
# auto-refresh 2026-10-21 (update_pytest_baseline.py --fix): total 8737 -> 8740, gui 3763 -> 3764, not_gui 4974 -> 4976.
# QH-5a (locked package matrix and clean-machine evidence): 131 not-gui cases in
# three new files — tests/unit/test_release_package_matrix.py (68: the shipped
# matrix, its validation, the Presenter pins against uv.lock, and the workflow
# lock policy), tests/unit/test_release_evidence.py (40: build records and the
# verification of the published bytes, SBOMs and latest.json) and
# tests/unit/test_package_smoke.py (23: the save -> restart -> export scenario
# and its runner, including the artifact that the OS refuses to start). No GUI
# marker or GUI test-file membership changed, so gui_files stays 195;
# not_gui 4976 -> 5107, total 8740 -> 8871.
# auto-refresh 2026-10-23 (update_pytest_baseline.py --fix): total 8871 -> 8875, gui 3764 -> 3765, not_gui 5107 -> 5110.
# auto-refresh 2026-10-23 (update_pytest_baseline.py --fix): total 8875 -> 8877, not_gui 5110 -> 5112.
# UI (Win10/Linux shell visuals): 12 new cases, no new GUI file (gui_files stays
# 195). Nine not-gui ones in the new tests/unit/test_ui_icon_metrics.py — every
# tool button names an existing glyph, the icon edges fit the fixed cell, the
# tool-row cell is padding-free, the PACS QToolButton matches its neighbours, the
# action row is flat with group separators, the action glyph carries a gap before
# its caption, no shell module rasterises SVG through the image-format plugin, an
# icon-less button falls back to a letter, the widget style is pinned to Fusion.
# One more not-gui case in tests/unit/test_theme_graphite.py (the muted
# destructive fill keeps its label readable in every theme) and two GUI cases in
# tests/unit/test_system_bar.py (the action groups are separated by hairlines; a
# hairline disappears with the group it belongs to).
# not_gui 5112 -> 5122, gui 3765 -> 3767, total 8877 -> 8889.
# UI acceptance round 2 (ТЗ 2026-10-23): 71 new cases.
# Not-gui (48): tests/unit/test_cardiac_study.py (the «is this an echo study»
# rule that keeps the caliper-naming window out of general ultrasound: cardiac
# preset names, Russian spellings, body parts, the negative cases and the
# study-level combination).
# GUI (23, gui_files 195 -> 196 — the new tests/unit/test_paired_tools.py is a
# GUI file): tests/unit/test_paired_tools.py (7 — the armed second half of
# «МЖП · КДР ЛЖ · ЗСЛЖ»/«КДО · 4-кам.» survives scrolling, starts on the next
# click, and is dropped by Esc/another tool/another clip),
# tests/unit/test_presentation_main_window.py (2 — the window arms LVIDs after
# the diastole sequence and the ES contour after the ED one),
# tests/unit/test_label_picker.py (3 — a general-ultrasound study and an
# unknown study type never open the naming window, and the host can override
# the study type), tests/unit/test_tool_panel_v2.py (3 — the row tooltip
# carries the name only, goes silent while the reference card is up, and never
# shows a «req:» key) and tests/unit/test_user_preferences.py (8 — the concept
# palette becomes the default and the old default is migrated once, while a
# deliberate choice of it sticks; the file is GUI-marked, so these are GUI).
# not_gui 5122 -> 5170, gui 3767 -> 3790, total 8889 -> 8960.
# auto-refresh 2026-10-23 (update_pytest_baseline.py --fix): total 8960 -> 8976, gui 3790 -> 3806, gui_files 196 -> 198.
# auto-refresh 2026-10-23 (update_pytest_baseline.py --fix): total 8976 -> 8990, gui 3806 -> 3814, not_gui 5170 -> 5176, gui_files 198 -> 199.
# auto-refresh 2026-10-23 (update_pytest_baseline.py --fix): total 8990 -> 8991, gui 3814 -> 3815.
# auto-refresh 2026-10-24 (update_pytest_baseline.py --fix): total 8991 -> 8992, gui 3815 -> 3816.
# auto-refresh 2026-10-24 (update_pytest_baseline.py --fix): total 8976 -> 8982, not_gui 5170 -> 5176.
# auto-refresh 2026-10-24 (update_pytest_baseline.py --fix): total 8982 -> 9003, not_gui 5176 -> 5197.
# auto-refresh 2026-10-24 (update_pytest_baseline.py --fix): total 9003 -> 9017, not_gui 5197 -> 5211.
# auto-refresh 2026-10-24 (update_pytest_baseline.py --fix): total 9017 -> 9003, not_gui 5211 -> 5197.
# auto-refresh 2026-10-24 (update_pytest_baseline.py --fix): total 9003 -> 9017, not_gui 5197 -> 5211.
# auto-refresh 2026-10-24 (update_pytest_baseline.py --fix): total 9017 -> 9033, gui 3806 -> 3816, not_gui 5211 -> 5217, gui_files 198 -> 199.
# auto-refresh 2026-10-24 (update_pytest_baseline.py --fix): total 9033 -> 9047, not_gui 5217 -> 5231.
# auto-refresh 2026-10-24 (update_pytest_baseline.py --fix): total 9047 -> 9061, gui 3816 -> 3822, not_gui 5231 -> 5239.
# S1-04 (audit 2026-10-22 §13): new tests/unit/test_xfail_strict_ratchet.py with 4
# logic cases — the xfail-strict ratchet: the pytest configuration flag, the
# whole-repository marker inventory, and two detector self-tests. No GUI marker
# and no new GUI file, so gui and gui_files stay; not_gui 5239 -> 5243,
# total 9061 -> 9065.
# auto-refresh 2026-10-25 (update_pytest_baseline.py --fix): total 9065 -> 9081, gui 3822 -> 3838.
# auto-refresh 2026-10-25 (update_pytest_baseline.py --fix): total 9081 -> 9082, gui 3838 -> 3839.
# S1-03/S1-01 (distribution pins + pending-contour safety): 9 logic cases in
# test_runtime_setup.py (4 online/offline fail-closed checks),
# test_models_release_integrity.py (published sums manifest pin),
# test_deb_first_run_pins.py (Windows build/launcher pins),
# test_la_area_length.py and test_rv_fac.py (pending contours cannot affect
# LA area-length or RV FAC). GUI markers and GUI-file inventory unchanged.
# not_gui 5243 -> 5252, total 9065 -> 9074.
# auto-refresh 2026-10-25 (update_pytest_baseline.py --fix): total 9065 -> 9074, not_gui 5243 -> 5252.
# auto-refresh 2026-10-25 (update_pytest_baseline.py --fix): total 9065 -> 8833, gui 3822 -> 3686, not_gui 5243 -> 5147, gui_files 199 -> 190.
# auto-refresh 2026-10-25 (update_pytest_baseline.py --fix): total 8833 -> 8834, not_gui 5147 -> 5148.
# auto-refresh 2026-10-25 (update_pytest_baseline.py --fix): total 8834 -> 8843, not_gui 5148 -> 5157.
# auto-refresh 2026-10-25 (update_pytest_baseline.py --fix): total 8843 -> 8860, gui 3686 -> 3703.
# #323/#324/#326 (audit batch 2026-10-25): 3 GUI cases in
# test_measurement_persistence_disk.py (runtime-enable data loss without
# further edits, empty-session guard, conflict adopted only after the user's
# resolution) and 12 logic cases in test_runtime_setup.py (download-URL
# validation, post-install venv verification, required modules pinned
# against uv.lock). No marker or GUI-file membership changed.
# auto-refresh 2026-10-25 (update_pytest_baseline.py --fix): total 8860 -> 8875, gui 3703 -> 3706, not_gui 5157 -> 5169.
# auto-refresh 2026-10-25 (function-length ratchet tests): total 8875 -> 8878, not_gui 5169 -> 5172.
# auto-refresh 2026-10-25 (function-length ratchet tests after main merge): total 8876 -> 8879, not_gui 5169 -> 5172.
# S2-03 report-PDF application facade + presentation/infrastructure ratchet:
# 5 logic cases in test_application_report_export.py and 2 architecture cases
# (the application facade stays Qt-free; only reviewed presentation edges pass).
# No GUI marker or GUI-file membership changed; total 8879 -> 8886,
# not_gui 5172 -> 5179.
# auto-refresh 2026-10-25 (update_pytest_baseline.py --fix): total 8879 -> 8886, not_gui 5172 -> 5179.
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 8886 -> 8891, gui 3707 -> 3710, not_gui 5179 -> 5181.
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 8891 -> 8895, gui 3710 -> 3713, not_gui 5181 -> 5182.
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 8886 -> 8888, not_gui 5179 -> 5181.
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 8891 -> 8893, not_gui 5181 -> 5183.
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 8893 -> 8897, gui 3710 -> 3713, not_gui 5183 -> 5184.
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 8897 -> 8898, gui 3713 -> 3714.
# Quick-access follow-up: 12 additional cases. The new five-case Qt module
# is explicitly GUI-marked; relative to the CI-collected inventory in run
# 40377412082, those five cases move from not_gui to gui (+1 GUI file).
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 8910 -> 8947, gui 3723 -> 3732, not_gui 5187 -> 5215, gui_files 191 -> 192.
# Compact controls/accent palettes: 4 pure palette tests, 4 GUI checks in existing GUI files.
# Tools editor: one bilingual narrow-viewport GUI regression test.
# Preset-switch fast path: two GUI regression cases in the existing layout module.
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 8921 -> 8958, gui 3730 -> 3739, not_gui 5191 -> 5219, gui_files 191 -> 192.
# Dependabot lock-policy regression: one new not-gui test in
# test_release_package_matrix.py. Inventory collected by CI run 40449819706.
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 8958 -> 9019, gui 3739 -> 3758, not_gui 5219 -> 5261, gui_files 192 -> 193.
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 9019 -> 9127, gui 3758 -> 3802, not_gui 5261 -> 5325, gui_files 193 -> 195.
# Keep one active baseline: merging main must not shadow branch-local test additions.
# CI run 40457930155 collected the merged suite, including the Dependabot policy test.
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 9020 -> 9152, gui 3758 -> 3811, not_gui 5262 -> 5341, gui_files 193 -> 195.
# auto-refresh 2026-10-27 (update_pytest_baseline.py --fix): total 9152 -> 9224, gui 3811 -> 3823, not_gui 5341 -> 5401, gui_files 195 -> 198.
# auto-refresh 2026-10-28 (update_pytest_baseline.py --fix): total 9224 -> 9229, not_gui 5401 -> 5406.
# auto-refresh 2026-10-28 (update_pytest_baseline.py --fix): total 9229 -> 9235, gui 3823 -> 3824, not_gui 5406 -> 5411.
# auto-refresh 2026-10-28 (update_pytest_baseline.py --fix): total 9235 -> 9280, gui 3824 -> 3837, not_gui 5411 -> 5443.
_BASELINE = {"total": 9280, "gui": 3837, "not_gui": 5443, "gui_files": 198}
# auto-refresh 2026-10-28 (update_pytest_baseline.py --fix): total 9235 -> 9237, gui 3824 -> 3826.
# auto-refresh 2026-10-28 (Orthanc loader enrichment test inventory): total 9237 -> 9282, gui 3826 -> 3839, not_gui 5411 -> 5443.
_BASELINE = {"total": 9282, "gui": 3839, "not_gui": 5443, "gui_files": 198}
# auto-refresh 2026-10-28 (update_pytest_baseline.py --fix): total 9235 -> 9246, gui 3824 -> 3828, not_gui 5411 -> 5418, gui_files 198 -> 199.
_BASELINE = {"total": 9246, "gui": 3828, "not_gui": 5418, "gui_files": 199}
# auto-refresh 2026-10-28 (update_pytest_baseline.py --fix): total 9235 -> 9237, gui 3824 -> 3826.
# auto-refresh 2026-10-28 (update_pytest_baseline.py --fix): total 9237 -> 9248, gui 3826 -> 3830, not_gui 5411 -> 5418, gui_files 198 -> 199.
_BASELINE = {"total": 9248, "gui": 3830, "not_gui": 5418, "gui_files": 199}
# auto-refresh 2026-10-28 (Orthanc pytest inventory per CI run 40763807047): total 9248 -> 9293, gui 3830 -> 3843, not_gui 5418 -> 5450.
# auto-refresh 2026-10-29 (update_pytest_baseline.py --fix): total 9293 -> 9278, gui 3843 -> 3828, gui_files 199 -> 197.
_BASELINE = {"total": 9278, "gui": 3828, "not_gui": 5450, "gui_files": 197}
# auto-refresh 2026-10-29 (update_pytest_baseline.py --fix): total 9293 -> 9297, gui 3843 -> 3847.
# auto-refresh 2026-10-29 (update_pytest_baseline.py --fix): total 9297 -> 9282, gui 3847 -> 3832, gui_files 199 -> 197.
_BASELINE = {"total": 9282, "gui": 3832, "not_gui": 5450, "gui_files": 197}
# auto-refresh 2026-10-29 (update_pytest_baseline.py --fix): total 9297 -> 9298, not_gui 5450 -> 5451.
# auto-refresh 2026-10-29 (update_pytest_baseline.py --fix): total 9298 -> 9313, gui 3847 -> 3861, not_gui 5451 -> 5452, gui_files 199 -> 202.
_BASELINE = {"total": 9313, "gui": 3861, "not_gui": 5452, "gui_files": 202}
# auto-refresh 2026-10-29 (update_pytest_baseline.py --fix): total 9298 -> 9283, gui 3847 -> 3832, gui_files 199 -> 197.
_BASELINE = {"total": 9283, "gui": 3832, "not_gui": 5451, "gui_files": 197}
# Reconcile the branch tests with main after the report-dialog tests were removed.
# Counts collected on Linux/Python 3.11 by CI run 40957489622 at merge 16faf1b.
_BASELINE = {"total": 9298, "gui": 3846, "not_gui": 5452, "gui_files": 200}
# Include the two GUI diagnostics tests collected in CI run 40998300677.
# Four GUI tests for completion markers and background downloads in existing files.
# auto-refresh 2026-10-30 (update_pytest_baseline.py --fix): total 9304 -> 9314, gui 3852 -> 3862.
# GUI cases of fix/unsaved-measurements-save-prompt (PR #390) land on top of this baseline.
# auto-refresh 2026-10-30 (update_pytest_baseline.py --fix): total 9314 -> 9325, gui 3862 -> 3873, gui_files 201 -> 202.
# The sixth GUI case of tests/unit/test_en_ui_localisation.py (the strain window
# is rebuilt on a language switch) arrived after that refresh: the gate in CI run
# 41117075254 collected 9326/3874, i.e. exactly one more GUI test, same file.
# Report conclusion autofill adds 103 logic cases in test_report_conclusion.py,
# 1 tab-session logic case, 6 GUI cases in test_report_phrases_panel.py and
# 3 GUI cases in test_presentation_main_window.py (existing GUI files only).
# Keep the merged inventory in the LAST assignment: CI run 41211891606 collected
# 9439/3883/5556 after main was merged; the previous main-only binding shadowed
# the branch baseline and stopped the test jobs before they could run.
# S2-02 (#306) adds 3 GUI cases in tests/unit/test_viewer_safe_diagnostics.py
# (existing GUI file): total 9439 -> 9442, gui 3883 -> 3886.
# auto-refresh 2026-10-31 (update_pytest_baseline.py --fix): total 9442 -> 9449, gui 3886 -> 3893.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9449 -> 9451, not_gui 5556 -> 5558.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9451 -> 9463, not_gui 5558 -> 5570.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9463 -> 9512, gui 3893 -> 3919, not_gui 5570 -> 5593, gui_files 202 -> 205.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9512 -> 9522, not_gui 5593 -> 5603.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9522 -> 9546, not_gui 5603 -> 5627.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9546 -> 9559, not_gui 5627 -> 5640.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9559 -> 9560, not_gui 5640 -> 5641.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9560 -> 9562, not_gui 5641 -> 5643.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9562 -> 9568, not_gui 5643 -> 5649.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9568 -> 9641, not_gui 5649 -> 5722.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9641 -> 9647, not_gui 5722 -> 5728.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9647 -> 9652, not_gui 5728 -> 5733.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9652 -> 9714, not_gui 5733 -> 5795.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9714 -> 9731, gui 3919 -> 3923, not_gui 5795 -> 5808.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9731 -> 9838, not_gui 5808 -> 5915.
# auto-refresh 2026-11-01 (update_pytest_baseline.py --fix): total 9838 -> 9839, not_gui 5915 -> 5916.
# auto-refresh 2026-11-02 (update_pytest_baseline.py --fix): total 9839 -> 9846, gui 3923 -> 3930.
# auto-refresh 2026-11-02 (update_pytest_baseline.py --fix): total 9846 -> 9847, gui 3930 -> 3931.
# auto-refresh 2026-11-02 (update_pytest_baseline.py --fix): total 9847 -> 9859, gui 3931 -> 3932, not_gui 5916 -> 5927.
_BASELINE = {"total": 9859, "gui": 3932, "not_gui": 5927, "gui_files": 205}


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read pytest inventory {path}: {exc}") from exc


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"pytest marker partition is incomplete: {message}")


def _baseline_assignment_lines() -> list[int]:
    """Line numbers of every module-level ``_BASELINE`` assignment, in file order.

    Only the final binding survives, so an update inserted above the audited
    line is dead code: the inventory check keeps comparing against the old
    numbers and the run fails with a mismatch that the author already "fixed".
    Naming the effective line turns that trap into an actionable message.
    """
    try:
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    lines: list[int] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_BASELINE" for target in node.targets
        ):
            lines.append(node.lineno)
    return lines


def _shadowed_baseline_hint() -> str:
    lines = _baseline_assignment_lines()
    if not lines:
        return ""
    return (
        f"; the audited baseline is the LAST of the {len(lines)} module-level _BASELINE "
        f"assignments (line {lines[-1]}): a new assignment inserted above it is shadowed "
        "and never takes effect"
    )


def _summed(section: str, inventories: list[dict[str, Any]]) -> dict[str, int]:
    """Sum one inventory section over GUI shards.

    Shards hold disjoint file sets, so file counts sum exactly like test counts.
    """
    keys = ("total", "gui", "not_gui", "interactive", "gui_files", "not_gui_files")
    return {key: sum(inv[section][key] for inv in inventories) for key in keys}


# The timing-budget test is run once, in isolation on GUI shard 0, and is
# intentionally excluded from the sharded pytest selection. Keep this explicit:
# the isolated run is a required CI step, while all other GUI tests must be
# selected by the six shards.
_ISOLATED_GUI_TESTS = 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logic", required=True, type=Path)
    parser.add_argument("--gui", required=True, type=Path, nargs="+", help="one metrics JSON per GUI shard")
    args = parser.parse_args()

    logic = _read(args.logic)
    shards = [_read(path) for path in args.gui]
    _check(shards, "no GUI shard inventories provided")
    gui_collected = _summed("collected", shards)
    gui_eligible = _summed("eligible_not_interactive", shards)
    gui_selected = _summed("selected", shards)

    logic_collected = logic["collected"]
    _check(gui_collected == logic_collected, "the GUI shards collected a different test inventory than logic")
    _check(logic_collected["interactive"] == 0, "the unit inventory gained interactive tests excluded by CI")

    eligible = logic["eligible_not_interactive"]
    for index, shard in enumerate(shards):
        _check(
            shard["eligible_not_interactive"] == shard["collected"],
            f"GUI shard {index} disagrees with the default interactive-test filter",
        )
    _check(gui_eligible == eligible, "the GUI shards disagree with the default interactive-test filter")
    missing_fields = _BASELINE.keys() - eligible.keys()
    _check(
        not missing_fields,
        f"inventory is missing baseline fields {sorted(missing_fields)}; refresh pytest_ci_metrics.py output",
    )
    baseline = {key: eligible[key] for key in _BASELINE}
    _check(
        baseline == _BASELINE,
        f"eligible suite inventory changed from the audited baseline {_BASELINE} to {baseline}; "
        "review the test-set change and update this baseline deliberately "
        "(uv run python .github/scripts/update_pytest_baseline.py --fix)" + _shadowed_baseline_hint(),
    )
    expected_logic = eligible["not_gui"]
    expected_gui = eligible["gui"]
    _check(expected_logic + expected_gui == eligible["total"], "GUI and non-GUI counts do not sum to the suite")

    logic_selected = logic["selected"]
    _check(logic_selected["total"] == expected_logic, "logic job did not select every eligible non-GUI test")
    _check(logic_selected["not_gui"] == expected_logic, "logic job selected a GUI test")
    _check(logic_selected["gui"] == 0, "logic job selected a GUI test")
    _check(logic_selected["interactive"] == 0, "logic job selected an interactive test")

    for index, shard in enumerate(shards):
        selected = shard["selected"]
        _check(selected["interactive"] == 0, f"GUI shard {index} selected an interactive test")
        _check(selected["not_gui"] == 0, f"GUI shard {index} selected a non-GUI test")
    sharded_gui = expected_gui - _ISOLATED_GUI_TESTS
    _check(
        gui_selected["total"] == sharded_gui,
        f"GUI shards selected {gui_selected['total']} tests; expected {sharded_gui} "
        f"because {_ISOLATED_GUI_TESTS} timing-budget test runs separately",
    )
    _check(gui_selected["gui"] == sharded_gui, "GUI shards selected a non-GUI test")
    _check(
        logic_selected["total"] + gui_selected["total"] + _ISOLATED_GUI_TESTS == eligible["total"],
        "the partition dropped or duplicated tests",
    )

    sys.stdout.write(
        "Verified pytest partition: "
        f"{eligible['total']} eligible tests = {expected_logic} logic + {sharded_gui} GUI-sharded "
        f"+ {_ISOLATED_GUI_TESTS} isolated timing-budget test across {len(shards)} GUI shards; "
        f"{eligible['interactive']} interactive tests remain excluded by the repository default.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
