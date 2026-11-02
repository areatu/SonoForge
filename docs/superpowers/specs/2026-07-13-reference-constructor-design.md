# Reference Constructor — Design Spec

## Overview

Visual editor for building and maintaining the structured reference handbook (`references_structured.yaml`). Launched from the References panel menu: **Файл → Конструктор**.

---

## 1. Data Model

### 1.1 Storage Format: YAML + JSON Schema

**Primary file:** `references_structured.yaml` (unchanged format, backward-compatible)

**Schema file:** `references_schema.json` — JSON Schema Draft 2020-12 for validation on save.

The constructor reads/writes YAML. On save it validates against the JSON schema and blocks save if validation fails.

### 1.2 Data Classes (shared with existing `ReferenceDataStore`)

```
TopicRef
  ├── name: str
  ├── slug: str
  ├── pathologies: list[PathologyRef]

PathologyRef
  ├── name: str
  ├── slug: str
  ├── description: str | None
  ├── image_paths: list[str]
  ├── parameters: list[ParameterRef] | None
  └── gradations: list[GradationRef] | None

GradationRef
  ├── name: str                    # "Лёгкая", "Умеренная", "Тяжёлая"
  └── parameters: list[ParameterRef]

ParameterRef
  ├── id: str                      # unique snake_case key
  ├── name: str
  ├── unit: str
  ├── norm_male: NormRange | None
  ├── norm_female: NormRange | None
  ├── pathology_desc: str | None
  └── source: str | None

NormRange
  ├── low: float | None
  └── high: float | None
```

### 1.3 Constructor-Internal Model

The constructor maintains a **mutable working copy** of the data in memory. Changes are applied to this copy. On "Save", the copy is serialized to YAML + validated against schema + written to disk.

Undo = reload from last-saved file on disk.

---

## 2. Directory Layout

```
src/echo_personal_tool/
├── constructor/                        # NEW — reference constructor
│   ├── __init__.py
│   ├── constructor_dialog.py           # QDialog wrapper (title bar, menus, save/preview)
│   ├── constructor_widget.py           # Main 3-panel layout
│   ├── editors/
│   │   ├── __init__.py
│   │   ├── topic_editor.py             # Left panel: anatomy topics (drag-reorder)
│   │   ├── pathology_editor.py         # Right-top: pathology list per topic
│   │   ├── parameter_table_editor.py   # Center: parameter table (add/edit/delete rows)
│   │   ├── gradation_editor.py         # Gradation columns (add/remove severity levels)
│   │   ├── image_editor.py             # Right-bottom: image list (drag-drop, zoom, remove)
│   │   ├── metadata_editor.py          # Bottom bar: sex/age filter, source, description
│   │   └── base_editor.py              # Abstract base with undo/redo hooks
│   ├── preview/
│   │   ├── __init__.py
│   │   ├── reference_preview.py        # Renders StructuredReferenceWidget from working copy
│   │   └── overlay_preview.py          # Renders overlay HTML from working copy
│   ├── importers/
│   │   ├── __init__.py
│   │   └── excel_importer.py           # Import from .xlsx/.xls
│   ├── exporters/
│   │   ├── __init__.py
│   │   ├── pdf_exporter.py             # Export to PDF
│   │   └── html_exporter.py            # Export to standalone HTML
│   └── storage/
│       ├── __init__.py
│       ├── yaml_storage.py             # Load/save YAML, backup on save
│       ├── schema_validator.py         # JSON Schema validation
│       └── image_storage.py            # Copy/move/delete images in resources dir
│
├── resources/references/
│   ├── references_structured.yaml      # PRIMARY DATA (existing)
│   ├── references_schema.json          # NEW — JSON Schema for validation
│   └── images/                         # Reference images (existing)
│
└── domain/services/
    └── reference_data_store.py         # READ-ONLY consumer (no changes)
```

---

## 3. UI Layout

### 3.1 Constructor Dialog

Frameless, maximizable `QDialog` (same style as `AseReferenceDialog`).

```
┌─────────────────────────────────────────────────────────────────────┐
│ ≡ Reference Constructor                            [—] [□] [×]     │
├─────────────────────────────────────────────────────────────────────┤
│ [💾 Save] [👁 Preview] [↩ Undo] [↪ Redo] [📥 Import Excel]        │
│ [📤 Export PDF] [📤 Export HTML] [⚙ Settings]                      │
├───────────┬──────────────────────────────┬──────────────────────────┤
│           │                              │                          │
│  LEFT     │  CENTER                      │  RIGHT                   │
│  (20%)    │  (50%)                       │  (30%)                   │
│           │                              │                          │
│ Topics    │  Parameter Table             │  Pathologies (top)       │
│ (anatomy) │  (editable QTableWidget)     │  (editable list)         │
│           │                              │                          │
│  • ЛЖ     │  Param | Name | Unit |       │  • Diastolic func        │
│  • ЛП     │  Norm M | Norm F | Desc      │  • Systolic func         │
│  • ПЖ     │  Source                       │  • ...                   │
│  • ...    │                              │                          │
│           │                              ├──────────────────────────┤
│           │                              │  Images (bottom)         │
│           │                              │  [Drop zone]             │
│           │                              │  img1.png [×] [🔍]       │
│           │                              │  img2.jpg [×] [🔍]       │
│           │                              │  Scale: [Fit ▾]          │
├───────────┴──────────────────────────────┴──────────────────────────┤
│ Sex: [● M ○ F] │ Age: [___] │ Source: [_____________]              │
│ Description: [_______________________________________________]     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Left Panel — Topic Editor

- `QListWidget` with drag-reorder (`setDragDropMode(InternalMove)`)
- Double-click to rename
- Right-click context menu: Add Topic, Delete Topic, Duplicate Topic
- Selection populates center + right panels

### 3.3 Center Panel — Parameter Table Editor

- `QTableWidget` (or `QTableView` with custom model)
- Columns: `id | name | unit | norm_male_low | norm_male_high | norm_female_low | norm_female_high | pathology_desc | source`
- Editable cells (double-click)
- Add row button, delete row (select + Delete key)
- Row drag-reorder
- Validation badges: red border on invalid `id` (duplicate/empty), orange on missing norms

### 3.4 Right Panel — Pathology Editor (top)

- `QListWidget` with drag-reorder
- Add / Delete / Rename
- Selection loads pathology's parameters into center table + images into image editor
- Toggle: "Flat parameters" vs "Gradations" per pathology

### 3.5 Right Panel — Image Editor (bottom)

- `QListWidget` showing image thumbnails + filenames
- **Drag & drop zone**: drop images from file manager → copies to `resources/references/images/`, adds to pathology's `image_paths`
- Context menu: Remove, Rename, Open in External Viewer
- Zoom controls: Fit, 50%, 100%, 200%, 400%
- Preview pane: shows selected image at chosen zoom

### 3.6 Bottom Bar — Metadata Editor

- `QRadioButton` for Sex filter (M/F/Both)
- `QSpinBox` for Age (0-120, optional)
- `QLineEdit` for Source citation
- `QLineEdit` for Pathology description

---

## 4. Key Features

### 4.1 Undo/Redo

- On "Save": snapshot working copy to `_saved_state` (deep copy)
- "Undo" = restore `_saved_state` into working copy + refresh UI
- In-memory undo stack NOT needed (per spec: undo = revert to last save)

### 4.2 Preview

- "Preview" button opens a new window showing:
  - `StructuredReferenceWidget` rendered from current working copy (not disk)
  - `ResultsOverlayLabel` HTML rendered from current working copy
- Preview is read-only, non-modal (can edit + preview side by side)

### 4.3 Drag & Drop

- **Topics**: reorder via drag in QListWidget
- **Pathologies**: reorder via drag in QListWidget
- **Parameters**: reorder rows via drag in table
- **Images**: drag files from OS file manager → copy to images dir + add to pathology

### 4.4 Validation

JSON Schema validates on save. Checks:
- Unique `id` per ParameterRef (global uniqueness)
- Unique `slug` per TopicRef and PathologyRef
- Required fields present
- Norm ranges: low < high
- Image files exist on disk
- No orphaned images (in dir but not referenced)

### 4.5 Import from Excel

- Read `.xlsx` / `.xls` via `openpyxl` or `pandas`
- Expected format: one sheet per topic, rows = pathologies, columns = parameters
- Mapping dialog: map Excel columns to ParameterRef fields
- Preview before import (diff view)

### 4.6 Export to PDF

- Render `StructuredReferenceWidget` to PDF via `QPrinter`
- One section per topic, pathology tables, images inline
- Page numbers, headers, table of contents

### 4.7 Export to HTML

- Standalone HTML with embedded CSS + base64 images
- Interactive: collapsible sections, search (client-side JS)
- Same visual style as `StructuredReferenceWidget`

### 4.8 Dynamic Links from Overlay

- Overlay links use `param_id` as href
- Constructor preserves all `param_id` values
- If `param_id` changes (rename), overlay links update automatically
- Preview shows live overlay HTML to verify links work

---

## 5. Integration Points

### 5.1 Entry Point

Add menu item to `AseReferenceDialog` menu bar:

```python
# In ase_reference_dialog.py menu bar:
self._menu_bar.addMenu("Файл")
# ... existing items ...
constructor_action = file_menu.addAction("Конструктор")
constructor_action.triggered.connect(self._open_constructor)
```

### 5.2 Data Flow

```
references_structured.yaml (disk)
         │
         ▼ yaml_storage.load()
constructor working copy (mutable dataclasses)
         │
         ├── editor UI (topic/pathology/parameter/image editors)
         │
         ├── preview (StructuredReferenceWidget from working copy)
         │
         └── save → yaml_storage.save() → references_structured.yaml
                    schema_validator.validate() → block on error
```

### 5.3 No Changes to Existing Code

- `ReferenceDataStore` stays read-only consumer
- `StructuredReferenceWidget` stays read-only viewer
- `ResultsOverlayLabel` stays unchanged
- Constructor is purely additive

---

## 6. Files to Create

| File | Purpose |
|------|---------|
| `constructor/__init__.py` | Package init |
| `constructor/constructor_dialog.py` | Main dialog |
| `constructor/constructor_widget.py` | 3-panel layout |
| `constructor/editors/__init__.py` | Editors package |
| `constructor/editors/topic_editor.py` | Left panel |
| `constructor/editors/pathology_editor.py` | Right-top panel |
| `constructor/editors/parameter_table_editor.py` | Center table |
| `constructor/editors/gradation_editor.py` | Gradation columns |
| `constructor/editors/image_editor.py` | Image drag-drop |
| `constructor/editors/metadata_editor.py` | Bottom bar |
| `constructor/editors/base_editor.py` | Abstract base |
| `constructor/preview/__init__.py` | Preview package |
| `constructor/preview/reference_preview.py` | Reference preview |
| `constructor/preview/overlay_preview.py` | Overlay preview |
| `constructor/importers/__init__.py` | Importers package |
| `constructor/importers/excel_importer.py` | Excel import |
| `constructor/exporters/__init__.py` | Exporters package |
| `constructor/exporters/pdf_exporter.py` | PDF export |
| `constructor/exporters/html_exporter.py` | HTML export |
| `constructor/storage/__init__.py` | Storage package |
| `constructor/storage/yaml_storage.py` | YAML load/save |
| `constructor/storage/schema_validator.py` | JSON Schema validation |
| `constructor/storage/image_storage.py` | Image management |
| `resources/references/references_schema.json` | JSON Schema |

## 7. Files to Modify

| File | Change |
|------|--------|
| `presentation/ase_reference_dialog.py` | Add menu item "Конструктор" in Файл menu |

## 8. Dependencies

| Package | Purpose |
|---------|---------|
| `openpyxl` | Excel import |
| `weasyprint` or `QPrinter` | PDF export |
| `jsonschema` | JSON Schema validation |

---

## 9. Implementation Order

### Phase 1: Core (MVP)
1. Storage layer (YAML load/save + JSON Schema + validation)
2. Working copy model
3. Constructor dialog + 3-panel layout
4. Topic editor (left)
5. Parameter table editor (center)
6. Pathology editor (right-top)
7. Save + Undo (revert to save)

### Phase 2: Rich Editing
8. Gradation editor
9. Image editor (drag-drop, zoom)
10. Metadata editor (bottom bar)
11. Preview (reference + overlay)

### Phase 3: Import/Export
12. Excel importer
13. PDF exporter
14. HTML exporter

### Phase 4: Polish
15. Drag-reorder for topics/pathologies/parameters
16. Validation UI (inline badges)
17. Keyboard shortcuts
18. Tests

---

## 10. Decisions

1. **Theme**: Custom QSS theme (constructor-specific, not reusing existing).
2. **i18n**: Bilingual (Russian + English) via translation strings.
3. **Multi-select**: Yes — allow editing multiple pathologies at once (parameter table shows union of all selected pathologies' parameters).
4. **Search**: Yes — search bar in constructor filters topics/pathologies/parameters (same logic as StructuredReferenceWidget).
5. **Batch operations**: Yes — bulk rename/delete parameters across selected pathologies.

## 11. Additional Features

### 11.1 Search
- Search bar at top of constructor widget
- Filters: topics by name, pathologies by name, parameters by id/name
- Highlights matches in all panels

### 11.2 Batch Operations
- Select multiple pathologies (Ctrl+Click / Shift+Click)
- Batch delete: removes selected pathologies + their parameters
- Batch rename: rename parameter id/name across all selected pathologies
- Batch move: move parameters between pathologies

### 11.3 Multi-Select Pathology Editing
- When multiple pathologies selected, center table shows:
  - Union of all parameters (deduplicated by id)
  - Column per pathology showing which parameters belong to which
  - Editing a parameter applies to all pathologies that contain it
