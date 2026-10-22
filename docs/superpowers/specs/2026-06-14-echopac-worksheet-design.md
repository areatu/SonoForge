# Clinical Worksheet + SystemBar (Phase 2 Sprint A)

## Goals

Replace flat measurement button panel with Clinical-style hierarchical worksheet and top system bar.

## SystemBar

- Study context: series description + modality (no PatientName)
- View toggle: 2D | Doppler
- Actions: Open folder, Caliper (L), Auto Segment (I), Reset
- Status slot mirrors `AppController.status_message`

## MeasurementWorksheet

- `QTreeWidget` with groups: Setup, LV Simpson, LV 2D, LA/RA, RV, Doppler, Indexed
- Row states: pending → in_progress (ES blink) → done (value column)
- Click emits `MeasurementAction` + view/phase → `MainWindow` routing

## MeasurementPanel (right column)

- Patient H/W + scrollable ASE summary only (no embedded tools)

## Migration

- `MeasurementToolsPanel` retained as module for signal compatibility in tests; UI wiring removed from main window.
