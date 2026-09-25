# SonoForge — detailed user help

> This guide describes the **current implementation of SonoForge**, not a planned feature set. Button and tab names below use the English UI labels where they are available. See [`HELP_RU.md`](HELP_RU.md) for the Russian user guide and [`TECHNICAL_HELP_EN.md`](TECHNICAL_HELP_EN.md) / [`TECHNICAL_HELP_RU.md`](TECHNICAL_HELP_RU.md) for the calculation and integration details.

SonoForge is a desktop viewer for echocardiography data, measurements, derived calculations, and a text PDF report. It is intended for research and education. It is **not a medical device**, does not replace a clinician, a validated ultrasound system, or a clinical information system, and does not provide a diagnosis. Verify every image, contour, calibration, automated result, and reference range with a qualified professional.

## Contents

- [1. Purpose and quick start](#1-purpose-and-quick-start)
- [2. Main window](#2-main-window)
- [3. Local files and folders](#3-local-files-and-folders)
- [4. Measures menu and application state](#4-measures-menu-and-application-state)
- [5. General measurement workflow](#5-general-measurement-workflow)
- [6. Linear measurements](#6-linear-measurements)
- [7. Areas, contours, Simpson, and chamber calculations](#7-areas-contours-simpson-and-chamber-calculations)
- [8. M-Mode](#8-m-mode)
- [9. Doppler, VTI, and vessel measurements](#9-doppler-vti-and-vessel-measurements)
- [10. Calibration and manual correction](#10-calibration-and-manual-correction)
- [11. AI and experimental features](#11-ai-and-experimental-features)
- [12. Reference browser](#12-reference-browser)
- [13. Reference Constructor](#13-reference-constructor)
- [14. User `.md` and `.pdf` documents](#14-user-md-and-pdf-documents)
- [15. Settings](#15-settings)
- [16. Servers, DICOMweb, Orthanc, and PACS](#16-servers-dicomweb-orthanc-and-pacs)
- [17. Export, reports, and sending](#17-export-reports-and-sending)
- [18. Keyboard shortcuts](#18-keyboard-shortcuts)
- [19. Typical workflows](#19-typical-workflows)
- [20. Troubleshooting and limitations](#20-troubleshooting-and-limitations)

---

## 1. Purpose and quick start

### What the application does

SonoForge can:

- view DICOM, DICOM cine, MP4, JPEG, and PNG;
- scan local folders and query/retrieve selected series through DICOMweb or DIMSE;
- play cine, select a frame, and keep measurement inputs for the current study during the application session;
- perform linear, area, contour, M-Mode, Doppler, VTI, and vessel measurements;
- calculate volumes, EF, BSA-indexed values, gradients, ratios, and other derived fields when the required inputs and calibration exist;
- show results over the current frame and generate a separate text PDF report;
- expose AI segmentation and experimental strain/LA features when the required settings, dependencies, and data are available;
- open the built-in structured reference data and user reference documents.

### Starting the application

For an installed build use the SonoForge shortcut or `sonoforge`. From source:

```bash
uv run sonoforge
# or
python -m echo_personal_tool
```

`Settings → Interface → On startup` provides:

- `Empty window` (`empty`): do not open data automatically;
- `Last folder` (`last_folder`): reopen the last existing folder selected with `Open folder…` after startup.

Language and theme are set in `Settings → Interface`. The language change rebuilds the UI; an already open reference document may need to be opened again.

### Minimal workflow

1. Click `Open folder…` and choose one study root when possible.
2. Select a thumbnail. The selected instance and frame are loaded into the viewer.
3. Use `Space`, the frame slider, or viewer controls for cine.
4. Check spatial, time, and Doppler calibration before measuring.
5. Choose an action from the `Measures` tab, click the points, and correct them when needed.
6. Check the result overlay, patient metrics, phase, unit, and study/series identity.
7. Open `Measurement Results` and choose PDF export when a report is needed.
8. Use a separate command for an original DICOM copy, an MP4, a screenshot, or an annotated DICOM. These are not interchangeable exports.

---

## 2. Main window

### 2.1 System bar

The top system bar contains the main commands:

| Button | Current function |
|---|---|
| `Open folder…` | Select a local root and start the background media scan. The path is saved as `last_opened_folder`. |
| `Load from server…` | Search studies through DICOMweb/DIMSE and select series to load or save. |
| `Send to server…` | Send local DICOM objects through STOW-RS or DIMSE C-STORE when a target is configured. |
| `Calibration B-mode` | Start the manual spatial/depth calibration tool. An automatic attempt may happen separately when applicable. |
| `Calibration Doppler` | Start the Doppler calibration workflow. |
| `Caliper` | Linear caliper: while active it takes multiple measurements in a row (`Dist1`, `Dist2`, …); inside the Doppler ROI it measures Δt (ms) and velocity (cm/s or m/s) instead of distance. Shortcut `L`; pressing it again switches the tool off. |
| `M-Mode` | Show/hide the M-Mode panel and start the M-Mode line workflow. |
| `References` | Open the structured reference browser and reference documents. |
| `Settings` | Open Interface, Measurement, Other, Experimental, and Server settings. |
| `Reset` | Reset the current measurement tools and measurement session after confirmation, if enabled. It does not delete or rewrite the source file. |

The status bar shows startup, scan, loading, calibration, tool, and error messages, as well as the version. Some controls are temporarily disabled while data are loading.

### 2.2 Thumbnail gallery

The thumbnail gallery lists instances/series. `Settings → Interface → Thumbnail size` selects small, medium, or large thumbnails. `Up` and `Down` select the previous or next instance; the backtick key `` ` `` collapses or expands the gallery.

The thumbnail context menu includes:

- `Copy DICOM file…`: copy the original DICOM file;
- `Export to MP4…`: convert a cine source to MP4, or copy an existing MP4 according to the current media type.

Neither command exports the current measurements, and neither automatically inserts the current calipers or contours into the copied file.

#### Important multiple-study limitation

The internal data model carries study, series, and instance identifiers, but the **current visible thumbnail gallery is a single flat pool**. If the selected root contains several study folders, their files currently appear together in one thumbnail list; the gallery does not create separate visual groups per study. For reliable navigation:

- open one study root at a time when identity matters;
- check patient, date, series description, and DICOM tags;
- do not infer study membership from thumbnail position.

### 2.3 Viewer

The central viewer displays the current frame, calipers, contours, result overlay, and optional diagnostic labels. Depending on the source, it supports:

- cine playback and frame selection;
- W/L controls and presets in `Controls` or `Settings → Interface`;
- crosshair, panel frames, caliper labels, and inline labels;
- zoom levels `Fit`, `100%`, and `200%` with `0`, `+`/`=`, and `-`;
- a context menu with `Save as…`, properties, overlay/reset commands, and calibration actions;
- an optional DICOM tag inspector.

`Save as…` saves a screenshot of the viewer area as PNG or JPEG. It is not a PDF report and is not a reliable structured-measurement export.

### 2.4 Side panels and layout

The main right panel includes:

- `Measures`: measurement and calculation actions, patient `Height`/`Weight`, and the `Measurement Results` button;
- `Controls`: cine speed, W/L, thumbnail size, crosshair, panel frames, and display options;
- DICOM properties/tag inspection when enabled;
- a properties view for the current instance and calibration availability.

`Customize Layout` can change gallery position, activity bar, status bar, panel arrangement, and the optional second viewer. A second viewer can show the same current instance; it does **not** turn a flat multi-study gallery into separate study groups.

### 2.5 Selecting an instance or tool

Measurement inputs are associated with the current SOP Instance and frame where the tool supports that scope. When an instance changes, SonoForge refreshes the overlay and restores saved inputs for that instance. M-Mode and Doppler states may need to be re-established for a different source. A tool changes the status line and often shows a prompt over the frame. `Esc` cancels an active tool; `Enter`/`Return` finishes a supported contour or trace.

---

## 3. Local files and folders

### 3.1 Supported files

The local scanner recognizes:

- DICOM with `.dcm` or `.dicom` extensions;
- extensionless DICOM when the header is recognizable;
- `.mp4`;
- `.jpg`, `.jpeg`, and `.png`.

Extension case is accepted. Invalid or unreadable DICOM files are skipped and the reason is written to `scan_errors.log`.

### 3.2 Folder scanning

Scanning is recursive inside the selected local root. For example:

```text
Studies/
├── Study_2026_01/
│   ├── bmode_001.dcm
│   ├── doppler.mp4
│   └── images/still.jpg
└── Study_2026_02/cine.dcm
```

When the selected folder has no media directly in its root but has child folders containing media, the child folders are treated as separate local roots in the data model. When media are present directly in the selected root, that root is treated as one root and nested media are scanned below it. Do not mix unrelated direct files and study folders if identity is important.

DICOM is grouped from its UIDs. MP4/JPEG/PNG without DICOM metadata receive synthetic study/series identifiers associated with the local folder. The gallery can still display the complete selected root as one flat thumbnail pool.

### 3.3 Open and diagnose a scan

1. Click `Open folder…`.
2. Wait for the background scan to finish.
3. If a file is missing or rejected, inspect `<selected folder>/scan_errors.log`.
4. Check that the root contains supported media or a valid extensionless DICOM header.

The scanner skips service directories such as `.git`, `.idea`, `__pycache__`, `node_modules`, `.venv`, and `.svn`. A bad file should not prevent the remaining files from being scanned.

### 3.4 Local sources and server cache

A local DICOM is opened from its source path. Objects downloaded from a server are placed in SonoForge's temporary cache and then scanned as a local study. Use **`Save to Disk`** in the server dialog when the retrieved files must remain in a permanent user-selected directory; `Load` alone is a working-cache operation.

---

## 4. Measures menu and application state

The `Measures` tab is an accordion menu. Depending on language and experimental settings, the current groups include:

| Group | Examples |
|---|---|
| `General` | `Caliper`, `Heart rate`, area, volume, diameter comparison, and area comparison. |
| `LV` / `LV Auto` | LV dimensions, IVS/LVEDD/LVPW sequence, Simpson 4C/2C ED/ES, and LV automatic workflow. |
| `Aorta` | AV, Annulus, Ao Sinus, Ao Junction, Prox Ao. |
| `Left Atrium` | LA diameter, LAV 4C, LAV 4C AI+, LAV 4C Auto when enabled, and LAV biplane. |
| `Right Atrium` | RA diameter and RAV. |
| `Right Ventricle` | RVOT, RV basal/mid, TAPSE, RV s', and RV FAC. |
| `Diastolic`, `MV`, and `TV` | E/A, DT, IVRT, e' septal/lateral, peaks, TR, trace, and valve VTI actions. |
| `Vessels` | PSV/EDV, Auto-Trace up/down, averaging, diameter/area stenosis, `Clear`, and `Accept`. |
| `M-Mode` | Anatomic M-Mode, M-Mode caliper, time/heart rate, Teichholz ED/ES actions. |
| `Strain` | A4C/A2C/A3C positions and `Speckle Tracking`, only when enabled and supported. |

Most actions put the viewer into a click/trace mode. While the mode is active, clicks place measurement points rather than navigating. A completed result is stored in the current session and, where possible, in the overlay and report snapshot. `Esc` returns to the normal viewer.

Availability is data-dependent. Doppler time/VTI actions require time calibration; spatial volumes and areas require a usable scale; automatic actions require the right mode, source, and dependencies. A disabled button is not evidence that the corresponding calculation is broken.

---

## 5. General measurement workflow

### 5.1 Calibration before units

Before measuring, check:

- DICOM Pixel Spacing or another spatial scale;
- a visible depth scale for MP4/JPEG;
- Doppler time and velocity axes;
- the result unit: pixels, millimetres/centimetres, or a derived physical unit.

If spatial calibration is absent, geometry can still be stored in pixels. Areas/volumes are then shown as `px²`/`px³` rather than clinical units. Selecting `mm` in Settings does not invent a scale.

`Settings → Measurement → Length display unit` selects `mm` or `cm` for display. It changes formatting, not the stored calibration.

### 5.2 Height, Weight, BSA, and the session

The `Measures` panel contains `Height` and `Weight`. The fields are whole-number spin boxes: height `0–250 cm`, weight `0–300 kg`; zero is displayed as empty. A DICOM instance with both `PatientSize` and `PatientWeight` can populate them when it is loaded (`PatientSize` is converted from metres to centimetres). MP4/JPEG/PNG have no DICOM tags and normally leave them empty.

User edits are kept in the in-memory session for the current study while SonoForge is running. The application rounds values displayed in the spin boxes to whole cm/kg. BSA appears only when both values are positive. See the [technical help](TECHNICAL_HELP_EN.md) for the exact formula, source chain, and indexed fields.

Changing height or weight causes dependent indexed fields to be recomputed. It does not change the original DICOM tags or a source file. Verify the patient metrics before exporting.

### 5.3 Editing and magnetic snap

In supported tools you can select a caliper or contour, drag a node, delete it with `Delete`/`Backspace`, and use `R` for the available open-contour refinement. `Settings → Measurement → Magnetic snap` uses image edges/gradients to move points toward a boundary. It is a heuristic: noise, shadow, low contrast, and non-anatomical edges can attract it. Always inspect the final geometry, not only the number.

---

## 6. Linear measurements

### 6.1 General caliper

1. Click `Caliper` or press `L`.
2. Click the start point.
3. Click the end point — the measurement is committed (`Dist1`).
4. Read the line/overlay value. The tool stays armed: the next two clicks start `Dist2`, then `Dist3`, and so on — like on an ultrasound scanner you can take several measurements on one frame without pressing `Caliper` again.
5. To switch the caliper off, press `Caliper`/`L` again or `Esc`.
6. Use `Tab` only when the active linear-caliper workflow exposes a label list.
7. Select the line and press `Delete` to remove it.

Inside the calibrated Doppler ROI (the spectrogram zone) the caliper measures the time interval between the points, Δt (ms), and the velocity amplitude (cm/s, switching to m/s at ≥100 cm/s) instead of a distance — for example for AcT (AT) of the RVOT: the first point at the flow onset, the second at the peak. Moving the cursor back to the B-mode zone restores distance measuring (mm). Measurements belong to the file they were taken on and never migrate to other files.

A normal distance uses start/end clicks. Specialized menu actions preselect labels such as `LVEDD`, `LVESD`, `IVSd`, `LVPWd`, `TAPSE`, `RVOT`, `LA`, or a Doppler peak. Specialized (anatomic) calipers remain single-shot: the tool switches off after the measurement is committed.

### 6.2 LV measurement sequences

`IVS–LVEDD–LVPW (2D)` is a three-caliper sequence:

1. `IVSd`, the diastolic septal thickness;
2. `LVEDD`, the diastolic LV internal dimension;
3. `LVPWd`, the diastolic posterior wall thickness.

The workflow can then offer `LVESD` through the systolic LV action. Confirm the labels and phase against the protocol being used.

### 6.3 Diameter comparison and stenosis

`Diameter comparison` collects two diameters and reports their relative comparison. The vessel `Diameter stenosis` action uses a different formula and reports a percentage reduction based on the larger reference diameter. They are not the same action. Use the dedicated menu action and keep the two measurements in the intended frame.

---

## 7. Areas, contours, Simpson, and chamber calculations

### 7.1 Closed area or volume polygon

For `Area` or `Volume` in polygon mode:

1. choose the action;
2. click successive boundary points;
3. close the polygon with a double click or `Enter`/`Return` when prompted;
4. check that there are at least three points and no self-intersection.

`Settings → Measurement → Area tool mode` selects `Polygon (clicks)` or `Freehand drawing`. Freehand input is simplified to a finite set of points; magnetic snap can then change it further. `Area comparison` collects two valid closed areas before displaying the comparison.

### 7.2 Manual LV contour and Simpson

A manual LV contour is an open arc from one mitral-annulus edge through the apex to the other edge:

1. choose `Simpson 4C` or `Simpson 2C` for the ED/ES phase, or `Manual contour`/`C`;
2. click the septal mitral-annulus point;
3. click the lateral mitral-annulus point;
4. click the apex;
5. add arc points if needed and finish with a double click or `Enter`;
6. repeat on ES when ESV and EF are required.

Check view (A4C/A2C), ED/ES, both annulus points, apex, scale, and contour direction. A biplane result requires compatible A4C and A2C inputs. Without scale, the result can remain in pixel units. Formula and data-source details are in the technical help.

The three-point workflow provides an initial/preliminary boundary that can be dragged and refined. It is not a guarantee of correct anatomy or segmentation. Review the entire contour before accepting it.

### 7.3 LV automatic workflow

`LV Auto` starts an LV automatic session. Only then does `I` request automatic segmentation of the current frame. `I` outside that session, during a Doppler tool, or while playback is active does not start the calculation. The current workflow primarily starts with A4C; continuation for A2C is not a promise of an independent one-click result. `Enter` accepts a pending preliminary contour and `Esc` rejects it.

Automatic segmentation is dependency- and model-file-dependent. If it is unavailable, use `Manual contour`. Even an accepted result must be reviewed and corrected by the user.

### 7.4 Other chambers

LA, RA, and RV actions support the currently implemented contour, Simpson, area-length, and FAC workflows. Select the correct view and phase and verify that the boundary does not include a wall, valve, vessel, or neighbouring chamber. Node edits change the geometry and all dependent results. A frame index is part of the measurement state; changing the frame does not continue the same contour automatically.

### 7.5 Teichholz and LV mass

Teichholz is based on M-Mode calipers; see [M-Mode](#8-m-mode). LV mass, RWT, chamber volumes, EF, FAC, and indexed values appear only when their required inputs exist. Missing inputs are not filled with clinical averages.

---

## 8. M-Mode

### 8.1 Enable and create the strip

Click `M-Mode` on the system bar or choose `M-Mode → Anatomic M-Mode`. The M-Mode panel appears and the B-mode viewer asks for a line:

1. click the line start;
2. click the line end.

The strip is built from the selected line and current cine. On another instance the line may need to be selected again. Available sweep speeds are `25`, `37.5`, and `50 mm/s`.

Depending on the action, use a vertical, horizontal, or arbitrary M-Mode caliper for depth, time, or a supported distance. **`M` is not the M-Mode toggle**: it starts the three-point contour workflow or may select `Doppler peak` in a Doppler event path. Use the visible `M-Mode` button/menu.

### 8.2 M-Mode calibration and ROI

SonoForge first tries DICOM or inferred panel calibration. If depth or time is missing, the workflow can ask for:

1. two corners of the M-Mode region (unless the ROI came from DICOM);
2. two points on the depth scale and a known distance in cm;
3. two time points and a known duration in ms when the time scale is unavailable.

The M-Mode state is associated with the current instance and used by time/depth measurements, TAPSE, and Teichholz. Calibration of an external video strip does not write DICOM Pixel Spacing back into the video.

### 8.3 Teichholz ED/ES

Choose the M-Mode LV dimension/Teichholz actions and make the three ED measurements:

1. septal thickness (`IVS`/`IVSd`);
2. `LVIDd`/`LVEDD`;
3. posterior wall thickness (`LVPWd`).

Repeat the required systolic internal dimension (`LVIDs`/`LVESD`) for ESV and EF. A complete, valid spatial/time context and the required calipers are needed for a useful result.

---

## 9. Doppler, VTI, and vessel measurements

### 9.1 Prepare spectral Doppler

Verify that the frame contains a spectrum and not only a scale or ECG overlay. SonoForge attempts to find:

- the spectral ROI;
- the zero-velocity baseline;
- the vertical velocity scale;
- the time scale from DICOM data, grid lines, or tick spacing.

Time-dependent tools (`Interval`, VTI, DT, IVRT, AT, and parts of the vessel workflow) remain unavailable without a time calibration. This is an input limitation, not a zero clinical result.

### 9.2 Peaks and intervals

Examples:

- `Peak E`, `Peak A`, `e' Sept`, `e' Lat`, `TR peak`, and other peak actions: click the peak of the intended envelope;
- `DT`, `IVRT`, `AT`, and `Time / HR`: mark the start and end of an interval;
- `E/A`, `E/e'`, averaged e', and other derived fields appear after compatible raw markers are stored.

Check the baseline, direction, and velocity span. A reflected or reversed spectrum can make an otherwise accurate click clinically wrong.

### 9.3 Trace and VTI

For a Doppler trace:

1. choose `Trace MV`, `Trace AV`, `Trace MR`, `Trace AR`, `Trace TR`, `Trace PR`, or `Auto VTI`;
2. trace the envelope using the on-screen interaction;
3. finish with `Enter` or a double click;
4. verify the cycle, baseline side, and direction.

`V` starts a VTI workflow when time calibration is ready. `Auto VTI` is an automated estimate and requires visual review. The report may include VTI, Vpeak, Vmean, PGpeak, PGmean, and related indices, but a completed trace is not a quality guarantee.

### 9.4 Vessel measurements

The `Vessels` group requires an appropriate Doppler context and time scale.

- `PSV/EDV`: place/select the peak or envelope and use `Accept`.
- `Auto-Trace Up` / `Auto-Trace Down`: choose the expected envelope direction, review it, and accept it.
- `Average 3 cycles`: select a cycle; `Left`/`Right` move the selection and `Enter` accepts when the viewer receives the event.
- `Diameter stenosis (%)`: mark the reference and residual diameters.
- `Area stenosis (%)`: mark the total and lumen areas.
- `Clear` cancels/clears the current vessel workflow; `Accept` stores it in the snapshot.

The `Low noise`, `Normal`, and `High noise` presets change trace sensitivity. They do not replace manual review.

### 9.5 Correcting Doppler

Select and drag supported peaks, interval endpoints, and trace points. The derived metrics are recalculated. If a value is wrong because the velocity or time scale is wrong, correct calibration first rather than moving the trace to match an expected number.

---

## 10. Calibration and manual correction

### 10.1 B-mode automatic path

For DICOM, SonoForge first uses available spatial metadata. For MP4/JPEG without DICOM tags, it may attempt to find visible centimetre depth marks when the frame is loaded. If successful, an auto-calibration status/overlay is shown; if confidence is insufficient, the manual caliper is offered.

Automatic detection is an image heuristic. A missing error message is not proof that the scale is correct. `Settings → Measurement → Auto depth calibration` exists, but the current open/reset path can still call the controller's automatic attempt when calibration is needed; do not treat disabling this preference as a guaranteed suppression. For reproducible work, inspect the actual scale and use manual calibration.

### 10.2 B-mode manual calibration

1. Click `Calibration B-mode` or press `K`.
2. Mark two points on a known vertical depth interval, preferably on the same scale line.
3. If `Snap to calibration ticks` is enabled, points may snap to detected marks.
4. Enter the known distance in centimetres in the depth calibration dialog.
5. Confirm and verify the result in properties/overlay.

`Shift+K` clears the saved manual spatial calibration. A DICOM scale or a different instance can supply a different effective scale after navigation.

### 10.3 Doppler automatic sources

Doppler calibration may use, in the relevant source-specific order:

1. DICOM Doppler tags;
2. visible scale ticks and grid lines;
3. ROI/baseline/scale image heuristics;
4. a guarded fallback when the ROI passes validation.

Some vendor layouts provide a real ROI or time scale but not a reliable velocity span. The code can refine it from visible ticks or fall back to a manual baseline/velocity dialog. Treat an automatic value as a proposal and compare it with the displayed scale.

`Settings → Measurement → Doppler from DICOM/scale` controls the Doppler automatic path. Manual calibration has priority for the current workflow.

### 10.4 Doppler manual velocity calibration

1. Click `Calibration Doppler`.
2. Select/confirm the spectral ROI if prompted.
3. Click the zero-velocity baseline.
4. Mark a known vertical scale interval; tick snapping may adjust the point.
5. Enter the **full velocity span in cm/s**. For example, `200` represents `+100` to `-100 cm/s` around the baseline when the axis is symmetric.
6. Confirm and verify the resulting time/velocity mapping.

Time can come from DICOM or tick detection, but a missing time axis still prevents time-dependent actions. Calibration is kept for the current instance/session; the source MP4 is not rewritten.

### 10.5 M-Mode calibration

M-Mode uses separate depth and time calibration: two depth points plus a known cm distance, and two time points plus a known ms duration. DICOM `FrameTime`/panel metadata can provide time; otherwise use the manual dialog. Confirm that both needed axes are complete before TAPSE, time/HR, or Teichholz.

### 10.6 Contour correction

Drag nodes after manual or automatic creation. Magnetic snap and `R` refinement are heuristic operations. Inspect the annulus endpoints, apex, chamber wall, phase, and all intermediate points after every automatic correction.

---

## 11. AI and experimental features

### 11.1 AI segmentation

AI actions depend on the installed runtime, model files, supported input, and the build's optional dependencies. A button may be hidden or disabled when the relevant setting/dependency/data is absent.

Current behavior:

- `LV Auto` opens the LV automatic session;
- `I` requests automatic segmentation only in that context;
- `Enter` can accept a pending preliminary contour and `Esc` can reject it;
- `LAV 4C AI` is shown when `Show LA Auto` is enabled in `Settings → Experimental`; `LAV 4C AI+` is a separate AI-assisted action. Both workflows require suitable dependencies and manual review;
- a three-point preliminary contour is not a confirmed anatomical border;
- `R` requests the supported open-contour refinement.

If an AI dependency or model is unavailable, use the manual workflow. An AI failure is not evidence that an anatomical structure is absent.

### 11.2 Speckle Tracking / Strain

Enable `Show Strain` in `Settings → Experimental` to expose the `Strain` group with A4C/A2C/A3C positions and `Speckle Tracking`. The window can show curves, segment overview, QC, and study-level values.

This is an experimental, dependency-sensitive workflow. It depends on cine quality, ECG/AVC handling, correct contours, and valid views. Check QC and review/invalid status before using or averaging a value.

### 11.3 Gold annotations

`Settings → Other → Gold Annotation` can enable an experimental annotation mode and a dataset folder. It is for research/model evaluation and does not turn user measurements into a clinically validated dataset.

---

## 12. Reference browser

### 12.1 Open the browser

Click `References`. The structured browser normally opens first. If the web engine is unavailable, the application can use the native Qt view.

Built-in structured data cover chambers, valves, aorta, vessels, pathology, parameters, ranges, gradations, and images when present in the YAML.

### 12.2 Structured data

Typical use:

1. choose a topic in the left column;
2. choose a pathology/subtopic;
3. inspect the parameter table and images;
4. search by parameter name or ID;
5. select a row to see its source/description;
6. use thumbnails/lightbox for illustrations.

The table can show `Norm M`, `Norm F`, unit, full name, pathology description, source, and severity columns. The `Age` field in the web browser currently stores the entered age but does not automatically filter the rows by age. Do not treat it as a working age filter.

### 12.3 Editing structured references

In the web view use `Edit`, change supported cells, and press `Save`. The bridge validates numeric ranges and writes the current structured data YAML. Back up the YAML before bulk changes.

`Reload` reloads the active structured/document content. It does not discover new files in a reference directory; reopen the `References` dialog to rescan the selected user folder.

---

## 13. Reference Constructor

Open `References → File → Reference Constructor`. The Constructor edits a `topics → pathologies → parameters/gradations` structure and can validate it against its schema.

### 13.1 Menus and panels

Current commands include:

- `File → Save` (`Ctrl+S`);
- `File → Save as…`;
- `File → Import Excel…`;
- `File → Export PDF…` and `Export HTML…`;
- `Edit → Undo` (`Ctrl+Z`), `Find` (`Ctrl+F`), and `Delete selected` (`Delete`);
- `View → Preview` (`Ctrl+P`) and `Validate`.

The topic, pathology, parameter, metadata, and image panels expose the available add/edit/delete/duplicate/reorder operations. `*` marks unsaved changes.

### 13.2 YAML model and language files

Parameters can include `id`, `name`, `full_name`, `unit`, male/female ranges, `pathology_desc`, `source`, and gradations. Topics contain pathologies; pathologies can contain descriptions, parameters, gradations, and image paths. Use `Validate` before saving.

The Constructor defaults to:

```text
src/echo_personal_tool/resources/references/references_structured.yaml
```

The Russian structured browser uses `references_structured_ru.yaml` by default. Editing the base YAML in Constructor does not automatically mean that the Russian browser reads the changed file. Check the active language and file, and keep backups.

### 13.3 Excel limitation

`Import Excel…` parses supported `.xlsx`/`.xls` sheets and expected headers, but the merge of imported topics/pathologies into an existing model is not complete in the current implementation. Verify Preview, Validate, and the saved YAML. Do not assume a full import/merge without inspection.

### 13.4 Constructor exports

Constructor `Export PDF…` and `Export HTML…` export the reference structure. They are not echocardiographic measurement reports.

---

## 14. User `.md` and `.pdf` documents

This is a separate document path from structured YAML. It is intended for local protocols, manuals, and notes.

### 14.1 Select one folder

1. Open `Settings → Other`.
2. Find the `References` block and `References folder`.
3. Select or type the full directory path.
4. Press `OK`.

An empty field uses the bundled reference directory. A placeholder such as `~/SonoForge-references` is only a hint; the folder does not become active until you select/type it and save the settings.

### 14.2 What is scanned

When the `References` dialog is opened, SonoForge scans **only the directly selected folder**:

- ordinary files with `.md` and `.pdf` extensions are accepted, case-insensitively;
- the tab title is taken from the filename without its extension;
- scanning is **not recursive**; subdirectories are not traversed.

For example:

```text
~/SonoForge-references/
├── Local_protocol.md
├── Pediatric_norms.pdf
└── Doppler_notes.MD
```

`~/SonoForge-references/subfolder/hidden.pdf` will not appear automatically. Put it directly in the selected folder or use `References → File → Add document…`.

### 14.3 Open and reload

- Close and reopen `References` after changing the folder or adding a file so the folder is scanned again.
- `File → Reload` reloads the **active document**; it does not rescan the directory.
- `File → Add document…` opens a selected `.md` or `.pdf` from another location as a temporary document; it does not copy it into the configured folder.
- Markdown uses a limited renderer for headings, rules, tables, lists, quotes, and basic emphasis. Complex Markdown may not render fully.
- PDF display requires PyMuPDF (`fitz`) and supports page navigation, zoom, one/two-page, and continuous modes when the dependency is installed.

These documents are reading material. They do not modify structured YAML norms or automatically enter a calculation.

---

## 15. Settings

### 15.1 `Interface`

- color theme: Dark, Light, VS Code Dark/Light, System;
- language: Russian or English;
- UI font size;
- results-overlay font size and opacity;
- caliper line width;
- cine playback speed multiplier;
- W/L preset: Last used, Soft, Contrast;
- thumbnail size: Small, Medium, Large;
- crosshair;
- panel frames;
- caliper labels on frame and inline labels;
- Reduce motion.

Line width and overlay settings affect display. Playback speed and cache affect playback behavior, not the measurement formulas.

### 15.2 `Measurement`

- manual, AI, and Simpson contour pen widths;
- `Magnetic snap to wall`;
- magnetic threshold, release strength, and maximum release radius;
- `Doppler from DICOM/scale` automatic path;
- `Snap to calibration ticks`;
- `Auto depth calibration` (see the implementation caveat in [B-mode calibration](#101-b-mode-automatic-path));
- length display unit `mm`/`cm`;
- area tool mode `Polygon (clicks)`/`Freehand drawing`.

Contour pen widths change the rendered line, not its stored points. Magnetic settings can change points and therefore results. Tick snap can change the selected calibration positions.

### 15.3 `Other`

The main block contains reset confirmation, PDF font size, and startup mode. Other blocks contain:

- `Gold Annotation`: experimental flag and dataset folder;
- `DICOM`: tag inspector and comma-separated overlay tags such as `PatientName,StudyDate,HeartRate,FrameRate`;
- `References`: the one selected `.md`/`.pdf` folder described in [section 14](#14-user-md-and-pdf-documents).

`Reset defaults` restores application preferences and layout while retaining the last opened folder. It does not reset the server profile.

### 15.4 `Experimental`

- `Show Strain` makes the experimental speckle-tracking group visible;
- `Show LA Auto` exposes experimental LA automatic actions.

The flags control visibility. They do not install missing models, runtimes, or scientific dependencies.

### 15.5 `Server`

The Server tab contains DICOMweb, authentication, HTTP headers, DIMSE, retrieval, TLS, embedded Storage SCP, STOW-RS, and profiles. See [section 16](#16-servers-dicomweb-orthanc-and-pacs).

---

## 16. Servers, DICOMweb, Orthanc, and PACS

Configure these fields in `Settings → Server`. SonoForge supports DICOMweb/QIDO-WADO-STOW, Orthanc-like DICOMweb endpoints, and native DIMSE. The `Load from server…` dialog has its own query-source selector.

### 16.1 DICOMweb and HTTP fields

The form contains:

- `Description`;
- `DICOMweb URL`, for example `http://192.168.1.111:8042/dicom-web`; an Orthanc root can be normalized to `/dicom-web`;
- `Authentication`: `No authentication` or `Basic (username / password)`;
- `Username` and `Password`;
- multiline `HTTP headers`, one `Name: value` per line;
- `Mock (no server)` for tests only;
- `Verify SSL certificate`.

Passwords are stored through the system keyring rather than in clear text in QSettings. Do not commit credentials or unnecessary authorization headers.

### 16.2 Query and retrieval are separate

The `Load from server…` dialog provides:

- a patient/name search field;
- query source `DICOMweb`, `DIMSE`, or `Auto`;
- date filter `All`, `1 day`, `3 days`, or `30 days`;
- `Find`.

This is the **query protocol**: QIDO-RS for DICOMweb or C-FIND for DIMSE. The separate `Retrieval source` setting controls the actual object download:

- `WADO-RS`;
- `DIMSE (C-GET)`;
- `DIMSE (C-MOVE)`;
- `Auto`.

Selecting DIMSE for search does not mean that objects will be retrieved through DIMSE. The dialog reports the retrieval selection separately.

### 16.3 DIMSE fields

`DIMSE (Native DICOM)` contains:

- `Enable DIMSE`;
- local `AE Title` (default `ECHO2026`);
- server `Called AE` (default `ORTHANC`);
- host and port (default `4242`);
- `Retrieval source`;
- a `Test C-ECHO` button.

Ports are validated from 1 through 65535. The PACS must allow the calling AE title, called AE title, host, and port.

### 16.4 C-FIND, C-GET, and C-MOVE

- **C-FIND** queries study/series/instance metadata over a DIMSE association.
- **C-GET** asks the PACS to return objects over the SonoForge association and is often the simplest DIMSE retrieval when supported.
- **C-MOVE** asks the PACS to send objects to SonoForge's embedded Storage SCP.

For C-MOVE configure `SCP bind host`, `SCP port` (default `11112`), and optionally `SCP AE title`. The PACS must be able to reach that bind address, and the AE/host/port must be registered on the PACS. `127.0.0.1` works only when the PACS is on the same network namespace/machine. NAT, containers, firewalls, or a remote PACS usually require a reachable LAN address and an allowed inbound port.

### 16.5 TLS

Separate HTTP and DIMSE TLS settings exist. DIMSE has `Use TLS`, `Verify certificate`, a CA certificate path, and optional client certificate/key paths. Keep certificate verification enabled for production and supply the correct CA/hostname/certificate chain. Disabling verification is suitable only for a controlled test and carries interception risk.

### 16.6 STOW-RS and profiles

`STOW-RS URL (if different)` overrides the DICOMweb URL for sending. If empty, the profile URL is used when STOW is available. `Profiles…` saves named server configurations; profile passwords also use the system keyring. After loading a profile, verify URL, auth, AE titles, retrieval source, TLS, and C-ECHO.

### 16.7 Search, retrieve, and Save to Disk

1. Click `Load from server…`.
2. Enter a patient/name filter if needed.
3. Choose the query source and date filter.
4. Click `Find`.
5. Expand a study and series tree.
6. Select one or more series.
7. Choose:
   - `Load` to download to the working cache and open in SonoForge;
   - **`Save to Disk`** to select a permanent directory and save the retrieved DICOM files.
8. Watch progress and errors; cancel when needed.

`Save to Disk` is the persistent path for server-loaded source objects. The selected directory receives a UID-oriented study/series/instance tree with safe path components. Open that folder later with `Open folder…`. `Load` alone is not an archival copy.

---

## 17. Export, reports, and sending

### 17.1 Distinct outputs

| Operation | Output | Current measurements included? |
|---|---|---|
| `Copy DICOM file…` | copy of the original local DICOM | No, unless the original already contained them. |
| `Export to MP4…` | MP4 conversion or copy of an existing video | No structured report or measurement annotations. |
| Viewer `Save as…` | PNG/JPEG screenshot | Image of the viewer area; not a PDF or structured export. |
| `Measurement Results → Export PDF` | text PDF report | Current completed snapshot values when their inputs are valid. |
| `Send to server…` | STOW-RS or DIMSE C-STORE payload | May include Graphic Annotation Sequence for supported current calipers/contours. |

Copying the source DICOM or converting video to MP4 is not measurement export.

### 17.2 PDF measurement report

1. Open the `Measures` tab.
2. Click the bottom `Measurement Results` button.
3. Review the report dialog.
4. Choose `Export PDF` and a path.
5. The PDF font size comes from `Settings → Other → PDF font`.

The report is built from the current `MeasurementSnapshot`: Doppler, Simpson/LVEF, Teichholz, LA/RA/RV, LV mass/RWT, diastology, planimeter, linear, vessel, strain, and indexed fields when computed. Repeated linear labels are reduced to the last value in the text report. A PDF is not DICOM SR and does not contain the entire cine.

### 17.3 Sending an annotated DICOM payload

`Send to server…` collects local DICOM objects and offers STOW-RS or DIMSE C-STORE when available. For matching SOP Instance UIDs, saved current calipers and contours can be serialized into a **new payload** with DICOM `Graphic Annotation Sequence` data.

The original file on disk is not automatically modified. `Copy DICOM file…`, `Export to MP4…`, and the PDF remain separate artifacts. Whether another PACS/viewer renders the graphic annotations depends on its support for that DICOM content.

---

## 18. Keyboard shortcuts

Only bindings confirmed in the current code are listed below. Their scopes are different. Dialogs and text fields may consume a key themselves; use the visible button/menu for a critical operation.

### 18.1 Window-level shortcuts in the main window

These are registered as `WindowShortcut` bindings:

| Key | Actual action and limitation |
|---|---|
| `L` | toggle the linear `Caliper`; also has a viewer event path. |
| `C` | start `Manual contour`. |
| `M` | start the three-point contour workflow. It is **not** the M-Mode toggle. A viewer event path can map `M` to `Doppler peak` in active Doppler context; use the menu when deterministic behavior is needed. |
| `I` | request automatic segmentation only in an active LV Auto session and outside a Doppler tool. |
| `Enter` / `Return` | finish a supported contour/trace or accept a pending preliminary contour. Use vessel `Accept` if the key is handled by the main shortcut path. |
| `Esc` | cancel the active tool or preliminary contour. |
| `Delete` / `Backspace` | delete the selected caliper or current-phase contour. |
| `` ` `` | collapse/expand the thumbnail gallery. |
| `F11` | toggle fullscreen; the gallery and panels are hidden in fullscreen. |
| `Up` / `Down` | select the previous/next gallery instance, not the previous/next cine frame. |

### 18.2 Main/viewer event-handler keys

When a key event reaches the main viewer, `MainWindow` handles:

| Key | Actual action and condition |
|---|---|
| `Space` | play/pause cine; ignored while decoding. |
| `K` | toggle manual `Calibration B-mode`. |
| `Shift+K` | clear manual spatial calibration. |
| `Tab` | cycle the current linear-caliper label; normal Qt focus navigation can take precedence in controls. |
| `T` | activate Doppler interval only when time calibration is ready. |
| `V` | start VTI trace only when time calibration is ready. |
| `R` | apply the available refinement to an active open contour; otherwise no contour is changed. |
| `G` | toggle `Ghost` overlay. |
| `Shift+G` | select `Ghost: neighbor`. |
| `[` / `]` | move to the previous/next neighbour ghost. |

`L`, `C`, `M`, `I`, `Enter`/`Return`, `Esc`, and `Delete`/`Backspace` have both window-level and event-handler paths. The receiving object/state determines which path wins. Do not use `M` as a substitute for either the `Doppler peak` or `M-Mode` button.

### 18.3 Viewer-only handlers

These are handled by `ViewerWidget` and are not main-window shortcuts:

| Key | Actual action |
|---|---|
| `P` | start vessel `PSV` when the current vessel/Doppler state allows it and the viewer has focus. |
| `Enter` / `Return` | accept a completed vessel result or selected vessel cycle; also finish a freehand contour. |
| `Esc` | cancel vessel-cycle selection or clear the vessel workflow. |
| `Delete` | delete the selected caliper. |
| `Ctrl+Shift+D` | toggle the viewer diagnostic debug overlay. |
| `+` / `=` | next zoom level: `Fit` → `100%` → `200%`. |
| `-` | previous zoom level. |
| `0` | `Fit`. |
| `Left` / `Right` | move the selected vessel cycle only while vessel-cycle selection is active. |

### 18.4 Other windows

- In the PDF view of `References`, `Right`/`Down` and `Space` go to the next page; `Left`/`Up` go to the previous page. `F5` reloads the active web reference page. It does not rescan the user document folder.
- `Reference Constructor` assigns `Ctrl+S` (`Save`), `Ctrl+Q` (close), `Ctrl+Z` (`Undo`), `Ctrl+F` (find), `Ctrl+P` (`Preview`), and `Delete` (delete selected) in its menu. `Validate`, Excel import, and PDF/HTML export use visible controls/menu items without an additional confirmed shortcut.
- In the separate `Strain` window, `C` cycles the bull's-eye palette. It does not change the main-viewer meaning of `C`.

### 18.5 Actions available only through buttons/menus

There is no confirmed main-window shortcut for `M-Mode`, `Calibration Doppler`, `Load`, `Save to Disk`, `Copy DICOM file…`, `Export to MP4…`, viewer `Save as…`, `Send to server…`, `References`, `Settings`, `Measurement Results`, vessel `Accept`/`Clear`, or most `Measures` actions. Use their visible buttons, menu entries, or context menus.

---

## 19. Typical workflows

### 19.1 Local DICOM → measurement → PDF

1. Open the DICOM folder.
2. Select the correct instance and frame.
3. Check DICOM tags, Properties, phase, and calibration.
4. Run the required `Measures` action.
5. Place and correct the points.
6. Review the overlay and choose `Measurement Results → Export PDF`.
7. If needed, separately use `Copy DICOM file…` for the source.

### 19.2 MP4/JPEG without DICOM tags

1. Open the media folder.
2. Confirm a visible depth scale.
3. Wait for auto calibration or press `K`.
4. Enter a known distance in cm and verify the scale.
5. Only then make physical-unit measurements.
6. Export an MP4 separately if a video artifact is required; it will not contain the measurements.

### 19.3 Multiple studies

1. Prefer one study folder at a time.
2. If opening a common root, remember that the gallery is one flat thumbnail pool.
3. Use DICOM tags, dates, patient, and series description to confirm identity.
4. For separate delivery, save each server study through **`Save to Disk`** or open separate roots.

### 19.4 PACS → permanent local files

1. Configure DICOMweb or DIMSE.
2. Test `C-ECHO` when using DIMSE.
3. Click `Load from server…`, choose a query source, and click `Find`.
4. Expand the study/series tree and select the desired series.
5. Click **`Save to Disk`** and choose the destination.
6. Open the saved folder locally and perform measurements there.

### 19.5 Measurements → DICOM with annotations

1. Open local DICOM.
2. Complete and review calipers/contours.
3. Configure the STOW-RS URL or DIMSE C-STORE target.
4. Click `Send to server…`.
5. Select STOW-RS or DIMSE.
6. Check successful object counts.
7. Remember that the source file is unchanged and the server receives a separate payload when annotations can be matched to SOP UIDs.

### 19.6 Add a local manual/reference

1. Put `.md`/`.pdf` files directly in one folder, without relying on subfolders.
2. Select it in `Settings → Other → References folder`.
3. Save the settings.
4. Close and reopen `References` to rescan the folder.
5. Use `File → Reload` for the active document; use `Add document…` for a file from another location.

---

## 20. Troubleshooting and limitations

### No thumbnails after opening a folder

Check the supported extensions, extensionless DICOM headers, and `<folder>/scan_errors.log`. Confirm that the selected root is the intended root and that media are not only inside skipped service directories.

### Several studies appear mixed

This is the current flat-gallery limitation. A root with multiple study folders produces one thumbnail pool. Use DICOM tags and open studies separately; do not expect visual study sections solely because the metadata has different StudyInstanceUID values.

### Results are in pixels, `px²`, or `px³`

No usable spatial calibration was resolved. Check DICOM spacing/ultrasound regions, the visible depth scale, and manual B-mode calibration. Choosing `mm` in Settings cannot correct a missing scale. See the [technical help](TECHNICAL_HELP_EN.md) for the exact source priority.

### Doppler actions are disabled or VTI is empty

The time axis is not calibrated or the selected frame is not a valid spectrum. Check DICOM tags, visible time ticks, ROI, and baseline. Use `Calibration Doppler` and provide the velocity span; time-dependent actions may still require a separate time calibration.

### Automatic calibration disagrees with the scale

Image/tick detection is heuristic and can fail on vendor overlays, noise, ECG content, or a partially visible ruler. Clear manual calibration with `Shift+K`, use the manual wizard, and compare the result with the visible scale. For Doppler, verify baseline, ROI, and full velocity span.

### A contour looks plausible but the number is wrong

Check view, ED/ES phase, annulus endpoints, apex, scale, and magnetic snap. A preliminary/automatic contour is not a confirmed anatomical boundary. Correct nodes, delete the contour, and repeat if necessary.

### M-Mode is empty or has the wrong dimensions

Check the B-mode line, current frame, M-Mode ROI, depth and time calibration, and the availability of cine frames. Switching instance can reinitialize the M-Mode state.

### PACS retrieval or `Save to Disk` fails

Check the DICOMweb URL/path, authentication, headers, and TLS verification. For DIMSE check Enable DIMSE, AE titles, host/port, and `Test C-ECHO`. For C-MOVE ensure that the PACS can reach the embedded SCP bind host/port and that its AE configuration/firewall allow the association. Remember that query source and retrieval source are separate.

### A user Markdown/PDF document is missing

The file must be directly in the selected folder and have `.md` or `.pdf` extension. Reopen `References` after changing the folder or adding the file; `Reload` only reloads the active document. PDF needs PyMuPDF; complex Markdown is only partially supported.

### Constructor changes are not visible in Russian

Constructor defaults to `references_structured.yaml`, while the Russian browser reads `references_structured_ru.yaml`. Check the active language, file, validation result, and backups.

### Excel import did not add everything

The parser recognizes expected sheets/headers, but merge into an existing model is incomplete. Inspect Preview, Validate, and YAML; prepare critical data manually if necessary.

### AI or Strain is unavailable

Enable the corresponding Experimental setting and verify the dependencies, model files, supported format, and correct frame. These features are not guaranteed in every build and must not be the sole basis for a clinical decision.

### The PDF is missing an expected value

The report uses the current completed `MeasurementSnapshot`, not every visible line. Check that the measurement was accepted, belongs to the intended SOP Instance/frame, and has the required spatial/time calibration, phase, patient metrics, or Doppler inputs. Copy DICOM, MP4 export, and screenshots do not add values to the PDF.

---

## Medical warning

SonoForge is supplied for research, education, and prototype analysis. Automated segmentation, reference ranges, calibration, volume/gradient calculations, Doppler/VTI, strain, and PDF output can be wrong and are not independently clinically validated here. Before using any result:

1. review the source image and cine quality;
2. confirm patient, study, series, instance, frame, and phase;
3. confirm scale, units, and manual points;
4. compare automated output with an independent measurement;
5. have a qualified clinician confirm the interpretation under the local protocol.

Do not use this guide or the application as a replacement for the ultrasound system manual, PACS documentation, clinical validation, or medical advice.
