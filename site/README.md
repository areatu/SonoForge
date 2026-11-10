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
