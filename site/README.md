# Project website

Source for <https://areatu.github.io/SonoForge/>. The static EN/RU site uses no framework.
`index.html` is the landing page, `tour.html` describes the workspace, and `app.js`
provides the optional language switch, release lookup and screenshot lightbox.

## Build and test

```bash
bash site/build.sh                 # writes _site/; ImageMagick is optional
python3 -m http.server --bind 0.0.0.0 -d _site 8000
python3 -m unittest discover -s site/tests -v
node --check site/app.js
```

The site uses the screenshots in `docs/images/release-0.4/`; add files there and
update `SHOTS` in `build.sh` and the HTML together. Review all screenshots for
patient information before publication. The six feature GIFs and static posters
in `site/media/features/` are original schematic illustrations, not application
screenshots. Regenerate them with `python site/generate_feature_media.py` (Pillow
>= 10); the build simply copies the committed files. GitHub Pages builds on
relevant pushes to main or by manual dispatch. Downloads point to the latest published GitHub release;
release data is loaded dynamically, and no unreleased version is advertised as
published if the API is unavailable.

`CITATION.cff` uses the all-versions DOI `10.5281/zenodo.21463212`; the separate
version-specific DOI `10.5281/zenodo.23000446` refers only to 0.3.2. The release date in `CITATION.cff` and the changelog heading must be updated
if publication is delayed to another day.

### Feature animation variants

`python site/generate_feature_media.py` (authoring dependency: Pillow >= 10)
regenerates two patient-free schematic sets at 480 × 224:

- **A — dark technical:** `media/features/{theme}.gif`; used on the landing page.
- **B — light minimal:** `media/features/alternatives/{theme}.gif`; review only,
  not copied into the published site by `build.sh`.

Themes: `cardiac`, `doppler`, `calibration`, `segmentation`, `pacs`, `reports`.
Each has a static `-poster.jpg`. Values are illustrative, not clinical results;
these are not application recordings. Existing pause and reduced-motion behaviour
also applies to the new published animations. To select B for a theme, copy its
GIF and poster from `alternatives/` to the parent directory (the generator will
restore A on its next run).

### Clinical application-style previews (review only)

`python site/generate_clinical_media.py` (Pillow >= 10, NumPy) generates a third
set in `media/features/clinical/`: six 800 × 450 GIFs, posters and a review sheet
(`REVIEW.md`). The synthetic ultrasound texture, ECG, spectral waveform,
measurements and UI are illustrative, not patient data, application recordings,
model outputs or clinical validation. A persistent English demo label is baked
into every frame. No assets from this folder are published by `build.sh`.

The workflow scenes show caliper placement, Doppler tracing, calibration,
contour review, DICOM retrieval and report population. These review masters are
larger than the landing-page budget; final publication needs approval, smaller
web derivatives and updated bilingual alternative text.

Clinical preview revision: all frame labels are English. CW spectra point below
the baseline with the velocity ruler on the right. The frozen A4C illustration
uses tapered ventricles, offset AV valves and atria below the annulus. The open
LV path runs from the septal MV annulus via the apex to the lateral annulus;
segmentation does not animate the heart. The server loader follows the actual
study/series split, filter toolbar and bottom actions in
`docs/images/release-0.4/server-loader.png`, without copying patient data.
Optional authoring checks: `python -m unittest discover -s site/tests -v`
with Pillow and NumPy installed (otherwise the authoring checks are skipped).

A4C revision 4: the supplied reference is no longer embedded. Smooth Bezier
strokes redraw the epicardium, chamber boundaries, septa and AV valve leaflets.
`media/features/clinical/a4c-schematic.png` is the generated transparent RGBA
master: no chamber fill, anatomical labels, callouts or trabecular notches.
The same drawing is composited over the viewer background in cardiac,
segmentation and all PACS thumbnails. The LV contour uses the exact same path
as the redrawn LV boundary; the segmentation frame remains frozen.

A4C revision 5: reproducible speckle texture is restricted to myocardial bands;
chamber interiors remain transparent. Cardiac caliper endpoints are computed
from intersections of both LV boundaries with the same horizontal scanline.
The tour now lists all 11 calculator registry cards and explains layouts, tool
visibility, theme/accent choices and reference editing/import/export in EN/RU.
