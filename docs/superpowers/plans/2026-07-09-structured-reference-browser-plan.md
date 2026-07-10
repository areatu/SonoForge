# Structured Reference Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structured reference browser as the first tab in AseReferenceDialog — topic → pathology → parameter table with sex-specific norms + images. Gradations are flattened into a single table with prefixes.

**Architecture:** ReferenceDataStore (dataclasses + YAML) loads structured data from `references_structured.yaml`. A new `StructuredReferenceWidget` provides the interactive UI. Integrated into `AseReferenceDialog` as Tab 1 (non-closable). Full YAML data populated from existing `References ASE+.md`.

**Tech Stack:** Python 3.10+, PySide6, PyYAML, pytest

## Global Constraints

- No new external dependencies beyond PyYAML (already installed transitively, added to pyproject.toml)
- Follow existing Qt patterns (programmatic layout, no .ui files)
- Use existing theme palette via `get_theme_palette()`
- Existing markdown reference tabs remain unchanged
- Phase 2 (overlay links) explicitly excluded from this plan

## Status: IMPLEMENTED

All tasks completed. See `CHANGELOG_SESSION.md` for details.

---

### Task 1: ReferenceDataStore (data model + YAML loader)

**Files:**
- Created: `src/echo_personal_tool/domain/services/reference_data_store.py`
- Modified: `pyproject.toml` (added PyYAML)
- Created: `tests/unit/test_reference_data_store.py`

- [x] **Step 1:** Write failing tests
- [x] **Step 2:** Run tests to verify they fail
- [x] **Step 3:** Add PyYAML to pyproject.toml
- [x] **Step 4:** Write implementation of reference_data_store.py
- [x] **Step 5:** Run tests to verify they pass
- [x] **Step 6:** Commit

---

### Task 2: Full YAML data file (all 11 topics)

**Files:**
- Created: `src/echo_personal_tool/resources/references/references_structured.yaml`
- Created: `src/echo_personal_tool/resources/references/images/` (7 assets)

- [x] **Step 1:** Create `references_structured.yaml` (11 topics, ~100 parameters)
- [x] **Step 2:** Verify YAML is valid
- [x] **Step 3:** Verify ReferenceDataStore loads it
- [x] **Step 4:** Commit

---

### Task 3: StructuredReferenceWidget (UI)

**Files:**
- Created: `src/echo_personal_tool/presentation/structured_reference_widget.py`
- Created: `tests/unit/test_structured_reference_widget.py`

- [x] **Step 1:** Write failing tests
- [x] **Step 2:** Run test to verify it fails
- [x] **Step 3:** Write implementation of StructuredReferenceWidget
- [x] **Step 4:** Run tests to verify they pass
- [x] **Step 5:** Commit

---

### Task 4: Integration into AseReferenceDialog

**Files:**
- Modified: `src/echo_personal_tool/presentation/ase_reference_dialog.py`

- [x] **Step 1:** Add "Справочник" tab (first, non-closable)
- [x] **Step 2:** Create `StructuredReferenceWidget` in dialog constructor
- [x] **Step 3:** Add `navigate_to_param()` method
- [x] **Step 4:** Handle maximize/restore mode
- [x] **Step 5:** Commit

---

### Post-implementation changes

- [x] **Fix:** `_close_doc_tab` — correct `_active_doc_index` after tab removal
- [x] **Fix:** Remove dead `_active` attribute from `_DocTab`
- [x] **Fix:** CSS newline in `_apply_close_style` hover
- [x] **Fix:** Chinese character in YAML (`准确` → `точное`)
- [x] **Change:** Remove gradation panel (QGroupBox + radio buttons)
- [x] **Change:** Flatten gradation parameters into single table with prefixes
- [x] **Change:** Fix image panel — fixed max-width 320px to prevent layout inflation
- [x] **Docs:** Update design spec and implementation plan
