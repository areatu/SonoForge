"""Verify that Linux logic and GUI jobs form a lossless marker partition."""

from __future__ import annotations

import argparse
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
_BASELINE = {"total": 8005, "gui": 3464, "not_gui": 4541, "gui_files": 176}


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read pytest inventory {path}: {exc}") from exc


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"pytest marker partition is incomplete: {message}")


def _summed(section: str, inventories: list[dict[str, Any]]) -> dict[str, int]:
    """Sum one inventory section over GUI shards.

    Shards hold disjoint file sets, so file counts sum exactly like test counts.
    """
    keys = ("total", "gui", "not_gui", "interactive", "gui_files", "not_gui_files")
    return {key: sum(inv[section][key] for inv in inventories) for key in keys}


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
        "review the test-set change and update this baseline deliberately",
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
    _check(gui_selected["total"] == expected_gui, "GUI shards did not select every eligible GUI test")
    _check(gui_selected["gui"] == expected_gui, "GUI shards selected a non-GUI test")
    _check(
        logic_selected["total"] + gui_selected["total"] == eligible["total"],
        "the partition dropped or duplicated tests",
    )

    sys.stdout.write(
        "Verified lossless pytest partition: "
        f"{eligible['total']} eligible tests = {expected_logic} logic + {expected_gui} GUI "
        f"across {len(shards)} GUI shards; "
        f"{eligible['interactive']} interactive tests remain excluded by the repository default.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
