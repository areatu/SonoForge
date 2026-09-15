# SonoForge — technical help (current implementation)

This document describes the calculation pipeline, persisted inputs, calibration state, preferences, reference data, and server protocols in the current checkout. It is an implementation reference, not a clinical validation document. The formulas below explain what the application computes; they do not establish that an input contour, scale, or clinical interpretation is correct.

See [`HELP_EN.md`](HELP_EN.md) for the user workflow and [`TECHNICAL_HELP_RU.md`](TECHNICAL_HELP_RU.md) for the Russian version.

## 1. Processing model and scope

SonoForge keeps raw measurement inputs in an in-memory `StudyMeasurementSessionStore`, keyed by the resolved Study Instance UID. A measurement can also carry SOP Instance UID and frame index. On every relevant state change, the controller builds a `MeasurementSnapshot` from:

1. the current `ViewerState` and current frame/instance;
2. DICOM/media metadata;
3. study-session contours, calipers, Doppler markers, vessel records, M-Mode state, and patient metrics;
4. effective spatial/time/velocity calibration;
5. calculation modules and reference-data lookup;
6. display/report formatting.

The session is application-runtime state. It is not a promise of a persistent database or of a durable edit to the source DICOM. Reset clears measurement inputs and manual calibration for the current study while retaining the patient metrics in the current session data structure.

The visible thumbnail gallery is not a study-grouping view: opening a root that contains several study folders currently places all discovered files in one flat thumbnail pool. Study UIDs still matter internally for measurement-session lookup, but they do not create separate visible gallery sections.

## 2. Unit and calibration pipeline

### 2.1 DICOM spatial source priority

`map_instance_metadata()` resolves a positive `(row_spacing, column_spacing)` in millimetres per pixel using the following resolver order:

1. DICOM `PixelSpacing`;
2. `ImagerPixelSpacing`;
3. `NominalScannedPixelSpacing`;
4. `SequenceOfUltrasoundRegions` physical deltas, converted from cm or mm to mm and, for supported tissue 2D data, the applicable ultrasound units;
5. `SharedFunctionalGroupsSequence/PixelMeasuresSequence/PixelSpacing`;
6. `PerFrameFunctionalGroupsSequence/PixelMeasuresSequence/PixelSpacing`.

The first valid positive pair wins. The source name is kept in instance metadata and can be shown in properties. The pair is ordered as row/vertical spacing and column/horizontal spacing; swapping them can create directional measurement errors.

Manual B-mode calibration derives an isotropic spacing from a known line:

```text
spacing_mm_per_px = known_distance_mm / measured_line_length_px
manual_spacing = (spacing_mm_per_px, spacing_mm_per_px)
```

The effective spacing is:

```text
effective_spacing = manual_spacing if present else dicom_spacing
```

Manual spacing therefore overrides DICOM-derived spacing for the relevant study/session. A positive DICOM pair or positive manual pair sets `spacing_calibrated = true`.

### 2.2 Uncalibrated fallback and pixel units

When no valid spacing is available, the controller passes `(1.0, 1.0)` to geometry routines but marks the snapshot as `spacing_calibrated = false`. This allows the same pixel geometry code to run without pretending that one pixel is one millimetre.

Formatting uses the flag to distinguish physical and pixel output:

- length: `px` when `millimeter_length` is unavailable;
- area: `px²` when the polygon is geometrically measurable but not spatially calibrated;
- volume: `px³` when the Simpson/closed-polygon geometry can be evaluated without a physical scale;
- calibrated output: mm/cm, cm², or mL as applicable.

Selecting `mm` or `cm` in Settings only changes length formatting. It cannot create missing pixel spacing. A technically valid pixel result is not a clinically meaningful physical result until the scale is verified.

### 2.3 Pixel-to-length conversion

For a line with pixel length `p` and image angle `θ`, the code resolves horizontal/vertical pixel components and uses the anisotropic spacing:

```text
x_px = p cos(θ)
y_px = p sin(θ)
length_mm = sqrt((x_px × column_spacing)² + (y_px × row_spacing)²)
```

The generic caliper stores `pixel_length`, optional `millimeter_length`, start/end coordinates, frame, and SOP Instance UID. A missing spacing leaves `millimeter_length = None`.

### 2.4 Area

Closed polygons use the pixel-coordinate polygon geometry after each point is scaled by row/column spacing. In physical mode, the shoelace area in mm² is converted as:

```text
area_cm² = area_mm² / 100
```

A closed polygon needs at least three points and must not be self-intersecting for a reliable result. The area-comparison tool reports the relative overlap of two valid areas:

```text
area_comparison_percent = min(A1, A2) / max(A1, A2) × 100
```

That is different from vessel area stenosis:

```text
area_stenosis_percent = (A_total − A_lumen) / A_total × 100
```

### 2.5 Volume and Simpson

A contour is converted to mm coordinates and sampled as 20 equal-height disks. For a single view, each disk uses diameter `d_i` and height `h = long_axis / 20`:

```text
V_mm³ = Σ (π / 4) × d_i² × h
V_mL = V_mm³ / 1000
```

The long axis is derived from the annulus endpoints/apex when available; a fallback y-span is used when the contour has no annulus state. The two-view/biplane form uses corresponding diameters from the two views:

```text
V_mm³ = Σ (π / 4) × d_A,i × d_B,i × h
h = max(long_axis_A, long_axis_B) / 20
V_mL = V_mm³ / 1000
```

The application calculates:

```text
LVEF_percent = (EDV − ESV) / EDV × 100
```

A biplane LV result requires compatible A4C and A2C ED/ES contours. If a complete biplane result is not available, the implementation can expose a monoplanar result or per-view values. Chamber Simpson for LA/RA/RV uses the same 20-disk mechanics where the implemented action supplies the required contours. A chamber volume may be shown from the available phase according to that calculation module; do not infer a missing ED/ES phase.

### 2.6 Teichholz, LV mass, RWT, and fractional shortening

The Teichholz module converts diameter from mm to cm and evaluates:

```text
V_mL = 7 × L_cm³ / (2.4 + L_cm)
```

`LVEDD` provides EDV and `LVESD` provides ESV. When both are valid:

```text
LVEF_percent = (EDV − ESV) / EDV × 100
```

LV mass uses the implemented ASE cube form, with IVSd, LVEDD, and LVPWd converted to centimetres:

```text
LVM_g = 0.8 × 1.04 × ((IVSd + LVEDD + LVPWd)³ − LVEDD³) + 0.6
```

Relative wall thickness is:

```text
RWT = (2 × LVPWd) / LVEDD
```

Some linear workflows also calculate fractional-shortening-style percentage comparison from the stored diastolic and systolic dimensions. Check the label and report context; it is not interchangeable with EF.

### 2.7 LA area-length and RV FAC

When an LA contour supplies area and an `LAL` caliper supplies length:

```text
LAV_mL = (8 × A_cm² × A_cm²) / (3π × L_cm)
```

The implemented RV FAC calculation uses ED and ES cavity areas:

```text
FAC_percent = (Area_ED − Area_ES) / Area_ED × 100
```

Both formulas depend on the contour boundary and the spatial scale. If the scale is absent, RV FAC is withheld by the controller even though a pixel polygon may exist.

### 2.8 Diameter/area stenosis and vessel ratios

For the dedicated diameter stenosis tool:

```text
diameter_stenosis_percent = (1 − min(D1, D2) / max(D1, D2)) × 100
```

For area stenosis:

```text
area_stenosis_percent = (S_total − S_lumen) / S_total × 100
```

Vessel Doppler metrics are computed from positive PSV/EDV values when `EDV ≤ PSV`:

```text
RI = (PSV − EDV) / PSV
S_D = PSV / EDV
mean_velocity_approx = (PSV + 2 × EDV) / 3
```

The formulas are implemented surrogates and do not validate the clinical vessel protocol or the direction of the trace.

## 3. BSA and indexed values

### 3.1 Height and weight source chain

The source chain for the values used in BSA is:

1. a loaded DICOM instance is mapped from `PatientSize` (metres) and `PatientWeight` (kg);
2. when both are present, instance loading sends height in cm and weight in kg to the measurement session;
3. the `Measures` panel exposes `Height` and `Weight` as `QSpinBox` controls, ranges `0–250 cm` and `0–300 kg`, with zero rendered as empty;
4. user changes emit values in whole cm/kg (the displayed values are rounded) to `StudyMeasurementSessionStore.set_patient_metrics()`;
5. the controller places `session.height_cm` and `session.weight_kg` into the `MeasurementSnapshot`;
6. the BSA/indexed calculation runs only when both values are positive.

For MP4/JPEG/PNG there are no DICOM patient tags, so the fields normally stay empty until the user enters them. If only one DICOM value exists, the automatic fill condition is not satisfied. Patient tags shown in the properties extractor are metadata; the calculation snapshot uses the session values. Values are in memory for the application session and are not written back to DICOM.

### 3.2 Du Bois BSA

The exact code formula is:

```text
BSA_m² = 0.007184 × height_cm^0.725 × weight_kg^0.425
```

The panel displays BSA to two decimal places. A non-positive or missing height/weight returns no BSA.

### 3.3 Indexing

The implementation divides physical values by BSA when the corresponding absolute result exists:

```text
indexed_volume_mL_m² = volume_mL / BSA_m²
indexed_linear_mm_m² = length_mm / BSA_m²
LVMI_g_m² = LV mass_g / BSA_m²
```

It can index Simpson EDV/ESV per view and combined values, Teichholz EDV/ESV, LAV (4C, biplane, or area-length), RAV, LV mass, and selected linear labels. The overlay always exposes available LAVi/RAVi and may expose other indexed values according to the reference-range/abnormality formatter; the PDF includes calculated fields when present.

BSA indexing cannot repair a wrong contour, a wrong calibration, or an incorrect patient metric. A change in height/weight changes indexed values but not absolute geometry.

## 4. Doppler and time formulas

### 4.1 Axis mapping

The Doppler mapping stores an ROI, plot width/height, time origin/span, velocity span, and baseline. With a calibrated time span:

```text
time_ms(x) = time_origin_ms + (x − plot_origin_x) / plot_width × time_span_ms
```

With a baseline and full velocity span:

```text
velocity_cm_s(y) = −(y − baseline_y) / (plot_height / velocity_span_cm_s)
```

The y-axis fallback maps the plot bounds between `velocity_min_cm_s` and `velocity_max_cm_s`, normally based on a default full span of 200 cm/s (`−100…+100 cm/s`) when no better scale is available. A wrong ROI, baseline, or span changes every velocity and time marker derived from that frame.

### 4.2 Time, heart rate, intervals

For a measured duration `T_ms`:

```text
heart_rate_bpm = 60000 / T_ms
```

An interval stores its start/end times in milliseconds and duration is `end_ms − start_ms`. DT, IVRT, AT, and ET are displayed only when their interval markers and the relevant time calibration exist.

### 4.3 Peak, ratio, VTI, and gradients

Raw peak markers store velocity in cm/s. Ratios are direct divisions when the denominator is non-zero:

```text
E_A = E / A
E_e′ = E / mean(e′_septal, e′_lateral)   (when both/one supported e′ values exist)
e′_septal / a′_septal-or-lateral = e′ / a′
```

The VTI trace is integrated with a trapezoidal rule over trace points `(time_ms, velocity_cm_s)`. Because time is in milliseconds, the integral is divided by 1000:

```text
VTI_cm = abs( ∫ velocity_cm_s dt_ms / 1000 )
```

Multiple VTI traces are averaged. If ET is present:

```text
Vmean_cm_s = abs(VTI_cm) / (ET_ms / 1000)
```

Otherwise the trace duration is used when possible. Simplified Bernoulli peak gradient uses velocity converted to m/s:

```text
PGpeak_mmHg = 4 × (Vpeak_cm_s / 100)²
```

The implementation computes mean gradient from the velocity-squared integral, not from `4 × Vmean²`:

```text
PGmean = (1 / T) × ∫ 4 × (v_cm_s / 100)² dt
```

It averages the available trace values and uses the ET interval when it is fully covered by the trace; otherwise it uses the trace span.

### 4.4 Diastolic grade

The implemented simplified criteria use available values including `E/e′ > 14`, septal `e′ < 7 cm/s` or lateral `e′ < 10 cm/s`, LAVi `> 34 mL/m²`, and TR Vmax `> 280 cm/s`. At least three criteria are required; a majority produces `Abnormal` or `Normal`, a tie produces `Indeterminate`. This is a simplified application rule, not a complete clinical guideline implementation.

## 5. Where other values come from

### 5.1 Frame and DICOM metadata

DICOM metadata mapping reads, among other fields:

- SOP/Series/Study identifiers and modality;
- frame count;
- spatial spacing and the source used;
- `FrameTime`, with `CineRate` fallback;
- `FrameTimeVector` when present;
- series description;
- `PatientSize` and `PatientWeight`.

DICOM tag inspector values are not automatically measurement inputs unless a specific parser uses them. The interesting tag overlay is a display preference.

### 5.2 Measurement state

Contours, linear measurements, vessel records, Doppler markers/calibration, M-Mode calibration, cine ROI, patient metrics, and strain report are stored in study session records. Linear and vessel fields are filtered to the current SOP Instance for the current snapshot; Doppler can aggregate raw DTOs across instances/frames in the study. Simpson biplane may combine compatible views from more than one instance, while physical spacing is resolved in the current calculation context.

The display overlay can use a current-instance Doppler DTO for the visible frame and a study-aggregate DTO for derived report values. This is why a value can be present in the study report but not be visually appropriate for a different current instance. Always check study/instance context.

### 5.3 Reference YAML and norms

The structured reference store loads bundled YAML and, where configured, the language-specific file. Constructor defaults to `references_structured.yaml`; the Russian browser normally uses `references_structured_ru.yaml`. Reference entries carry parameter ID, unit, male/female norms, gradations, pathology, images, and source. The web `Age` field currently does not filter the rows. User `.md/.pdf` documents are read-only reference material and are not calculation inputs.

## 6. Settings and their technical effects

Values below are the current preference bounds/defaults where defined in code. A visual preference can be persisted even if it is not a calculation input.

### Interface/display

| Preference | Current behavior |
|---|---|
| UI font size | 9–18 pt, default 12; UI layout/readability only. |
| Results overlay font | 10–28 pt, default 20; text rendering only. |
| Results overlay opacity | 0.10–1.00, default 0.70; visibility only. |
| Caliper line width | 1–6 px, default 2; rendered caliper only. |
| Cine speed multiplier | 0.25–4.0×, default 1.0×; playback timing only. |
| Playback cache | 8–512 MB, default 64 MB; decode/cache behavior, not a measurement formula. |
| W/L | Soft `(70, 40, 35)`, Contrast `(140, 55, 65)`, or last-used values; image display only. |
| Thumbnail size | Small/Medium/Large; gallery layout only. |
| Crosshair, panel frames, frame/inline labels | display only; labels do not change stored geometry. |
| Reduce motion | animation/accessibility behavior. |

### Measurement preferences

| Preference | Current behavior |
|---|---|
| Manual/AI/Simpson contour pen width | 1–6 px, default 2 px for each; line rendering only. |
| Magnetic snap | Enabled by default. Edge-map adjustment can modify points and therefore measurements. |
| Magnetic weight threshold | 0.05–0.50, default 0.15; minimum edge weight for attraction. |
| Magnetic release strength | 0.50–1.00, default 0.90; strength of release/snap movement. |
| Magnetic release radius | 5–40 px, default 15 px; maximum radial search/movement. |
| Doppler from DICOM/scale | Enabled by default; allows automatic Doppler metadata/tick/ROI path. |
| Calibration tick snap | Enabled by default; calibration clicks can move to detected ticks/grid lines. |
| Auto depth calibration | Enabled by default in preferences, but the current open/reset controller path can still attempt automatic depth calibration when required. Verify the real result and use manual calibration when needed. |
| Length unit | `mm` or `cm` display choice only. |
| Area tool mode | `click` polygon or `freehand`; changes point collection, not the area formula. |
| Despeckle/grayscale | display processing; it can change visual edge quality, not the persisted raw DICOM. |

Thickness changes do not change coordinates. Magnetic snap and tick snap can change coordinates/scale and must be included in reproducibility notes.

### Other/experimental preferences

PDF font is clamped to 8–16 pt, default 10. Reset confirmation, startup mode, DICOM tag inspector/list, last folder, reference directory, Gold Annotation, `Show Strain`, and `Show LA Auto` control UI/state. Experimental visibility does not install dependencies or models.

### Patient metrics and preferences are different

Height/Weight are session inputs, not general QSettings preferences. Changing Settings does not change the patient metrics for the current study. Resetting measurement inputs retains the height/weight fields in the current study session, while closing/restarting the app should not be treated as a persistent patient-record store.

## 7. Calibration failure modes and fixes

### Wrong physical units or pixels

**Causes:** missing tags, invalid/non-positive spacing, wrong row/column order, a manual line on the wrong scale, or a video/image with no visible ruler.

**Fix:** inspect the spacing source in Properties/DICOM tags, verify the visible depth ruler, clear a bad manual calibration, calibrate on a known interval, and compare a second known distance. Do not use a Settings unit selector as a calibration substitute.

### Wrong area/volume

**Causes:** self-intersection, open/closed contour mismatch, wall or valve included, incorrect annulus endpoints/apex, foreshortened view, wrong ED/ES frame, or pixel spacing applied from a different instance.

**Fix:** select the correct instance/frame/view, remove and redraw the contour, check points before accepting automatic refinement, and verify `spacing_calibrated` and the output unit. For biplane Simpson check both views and phase labels.

The LV automatic geometry validator can reject contours with too-small annulus/axis/arc, a too-flat arc, implausible annulus slope, inverted A4C apex, centroid outside the active ROI, or self-intersection. Those rejections are safeguards, not anatomical conclusions.

### Wrong magnetic result

**Causes:** edge map follows speckle, a shadow, a border, or a strong non-anatomical line; radius/threshold/release values are too permissive.

**Fix:** disable magnetic snap for the measurement, lower the release radius/adjust threshold, manually drag pinned endpoints, and compare with a non-snapped contour.

### Wrong automatic depth calibration

**Causes:** scale marks are cropped, low contrast, overlaid by ECG/text, or not a real depth ruler. `auto_depth_calibration_enabled` is currently not a reliable hard gate for every controller call.

**Fix:** manually calibrate with `K`, verify the known distance, and record the manual calibration in the workflow.

### Wrong Doppler values

**Causes:** wrong spectral ROI, wrong baseline direction, a full span entered as a half span, false tick/grid detection, missing time span, or a trace from the wrong cycle/direction.

**Fix:** use `Calibration Doppler`, place baseline on the zero line, enter the full velocity span in cm/s, validate the time ruler, and redraw the trace. A default 200 cm/s mapping is a fallback, not evidence of a 200 cm/s scale.

### Wrong M-Mode values

**Causes:** line crosses the wrong structure, ROI is wrong, depth/time calibration is incomplete, `FrameTime` is missing or not representative, or the source is not a real M-Mode panel.

**Fix:** redraw the line/ROI, supply depth and time calibration, and verify the M-Mode strip before using TAPSE/Teichholz/time HR.

### AI/Strain unavailable or implausible

**Causes:** optional runtime/model missing, unsupported frame/view, poor cine, invalid contour, or QC failure.

**Fix:** enable the feature only after installing its dependencies, use a supported clip, inspect the preliminary contour/QC, and compare with a manual workflow. Automatic output is not a diagnosis.

## 8. Server protocols and safe configuration

### 8.1 Protocol matrix

| Task | DICOMweb | DIMSE |
|---|---|---|
| Query | QIDO-RS | C-FIND |
| Retrieve | WADO-RS | C-GET or C-MOVE |
| Store/send | STOW-RS | C-STORE |
| Connectivity test | HTTP request | C-ECHO |

The query source selected in `Load from server…` and retrieval source in `Settings → Server` are independent. `Auto` can fall back according to available clients/settings; it is not a guarantee that every PACS supports every protocol.

### 8.2 Factory defaults versus safe deployment defaults

The implementation defaults are convenient for a local Orthanc-style test node, not a production network profile:

| Setting | Factory value in the current code |
|---|---|
| DICOMweb URL | `http://127.0.0.1:8042/dicom-web` |
| HTTP authentication | `Basic (username / password)` mode, with empty credentials until configured |
| DIMSE | disabled; AE `ECHO2026`, called AE `ORTHANC`, host `127.0.0.1`, port `4242` |
| Retrieval | `Auto`; DIMSE retrieval mode `C-GET` |
| DIMSE TLS | off, certificate verification on when TLS is enabled |
| Embedded Storage SCP | bind `127.0.0.1`, port `11112`, AE defaults to the local AE when blank |
| Network timeout | 30 seconds |

For a remote or production deployment, replace the loopback/HTTP defaults and explicitly verify the PACS contract. Recommended safe settings are:

- use a real DICOMweb HTTPS URL or a real DIMSE endpoint; leave `Mock` off outside tests;
- keep HTTP and DIMSE certificate verification enabled;
- provide a trusted CA and client certificate/key only when the PACS requires them;
- use Basic auth only over trusted HTTPS and keep passwords in the keyring;
- add only required custom headers and never commit them;
- keep the default network timeout of 30 seconds unless the deployment has a documented reason to change it (the current form preserves this setting rather than exposing a dedicated timeout control);
- use unique, PACS-approved local and called AE titles;
- use `C-GET` when supported and simpler for the PACS; use `C-MOVE` when the PACS requires it or when its routing model is appropriate;
- bind the embedded SCP to a reachable interface, not `127.0.0.1`, when the PACS is remote;
- open only the required SCP port in the firewall and register AE title, host, and port on the PACS.

### 8.3 C-MOVE reachability checklist

A C-MOVE request contains a destination AE. For the transfer to succeed:

1. the PACS must know the destination AE title;
2. the destination host/IP must route from the PACS to the SonoForge machine/container;
3. the SCP port must be allowed inbound;
4. the configured bind host must actually listen on the reachable interface;
5. TLS settings/certificates must match when secure DIMSE is used;
6. the PACS must have permission to move the selected study/series.

A C-MOVE destination-unknown or timeout error is normally an AE/network/routing issue, not a measurement calculation issue. C-ECHO tests the DIMSE association, but a successful C-ECHO does not prove that a C-MOVE destination can connect back.

### 8.4 Retrieval, STOW, and annotated payloads

The server dialog separates `Load` (working cache) from **`Save to Disk`** (a persistent UID-oriented local DICOM tree). `Save to Disk` is retrieval, not a measurement export.

The upload dialog chooses STOW-RS or DIMSE C-STORE based on configured availability. The source DICOM is read and a payload can be built with graphic annotations. The source path is not rewritten. A receiving PACS/viewer may ignore `Graphic Annotation Sequence`; verify interoperability independently.

## 9. Diagnostic checklist

When a number is unexpected, record:

1. Study/Series/SOP Instance UID and frame index;
2. source media type and metadata spacing/time source;
3. manual calibration state and whether it overrides DICOM;
4. Height/Weight and BSA source;
5. contour phase/view/endpoints and magnetic/tick-snap settings;
6. Doppler ROI, baseline, velocity span, time span, trace label, and cycle;
7. Settings that affect geometry/display;
8. whether the value came from current-instance display data or study-aggregate report data.

Then repeat with manual calibration and magnetic snap disabled. If the result changes, compare the raw points and axis mapping rather than only the formatted number.

## 10. Medical and software limitations

The formulas implement the current SonoForge code, not a complete clinical guideline engine. Reference ranges, automatic segmentation, Doppler detection, M-Mode inference, contour refinement, derived gradients, indexing, and PDF serialization can contain bugs or unsupported edge cases. Use source images, a validated measurement protocol, independent review, and qualified clinical judgment.
