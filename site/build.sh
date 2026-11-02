#!/usr/bin/env bash
# Assemble the GitHub Pages site into a single static directory.
#
#   bash site/build.sh [OUT_DIR]        # default: ./_site
#
# What goes in:
#   site/*.html, styles.css, app.js, favicon.svg      the landing page itself
#   assets/*.gif                                       → media/*.mp4 (needs ffmpeg) + JPEG posters;
#                                                        without ffmpeg the GIFs are copied and the
#                                                        page falls back to them automatically
#   site/media/features/*                             → media/features/ (prebuilt GIFs + posters)
#   assets/presenter.png                               → media/presenter.png
#   docs/screenshots/*.png (selected)                  → screenshots/ + screenshots/thumbs/*.jpg
#   branch github-repo-stats:<owner>/<repo>/latest-report  → same path on the site (traffic report)
#
# Used by .github/workflows/pages.yml; safe to run locally (python3 -m http.server -d _site).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="$ROOT/site"
OUT="${1:-$ROOT/_site}"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
STATS_REPO="${STATS_REPO:-areatu/SonoForge}"      # path prefix used by github-repo-stats inside its data branch
STATS_BRANCH="${STATS_BRANCH:-github-repo-stats}"

have() { command -v "$1" >/dev/null 2>&1; }
log()  { printf '\033[1;36m▸\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*" >&2; }

rm -rf "$OUT"
mkdir -p "$OUT/media" "$OUT/screenshots/thumbs" "$OUT/stats"

# ---------------------------------------------------------------- static files
log "static files"
cp "$SITE/index.html" "$SITE/tour.html" "$SITE/404.html" "$SITE/styles.css" "$SITE/app.js" "$SITE/favicon.svg" "$OUT/"
: > "$OUT/.nojekyll"

# Small, prebuilt card animations; no image-generation dependency in the Pages build.
cp -R "$SITE/media/features" "$OUT/media/features"

# Feature-tour GIFs recorded by hand from the real UI (see site/README.md, "Feature tour").
cp -R "$SITE/media/tour" "$OUT/media/tour"

# ---------------------------------------------------------------- demo media
# name | source GIF | poster frame index (ImageMagick) | poster time offset in s (ffmpeg)
MEDIA=(
  "preview|$ROOT/assets/sonoforge_preview.gif|170|11.9"
  "presenter|$ROOT/assets/presenter_demo.gif|5|5"
)

poster() { # <gif> <frame-index> <seconds> <out.jpg>
  local gif="$1" idx="$2" sec="$3" out="$4"
  if have convert; then
    # Coalesce so that delta-encoded GIF frames are rendered as full images before picking one.
    convert "${gif}[0-${idx}]" -coalesce -delete "0-$((idx - 1))" -strip -quality 84 "$out"
  elif have ffmpeg; then
    ffmpeg -y -loglevel error -ss "$sec" -i "$gif" -frames:v 1 -q:v 3 "$out"
  else
    return 1
  fi
}

for entry in "${MEDIA[@]}"; do
  IFS='|' read -r name gif idx sec <<< "$entry"
  if [ ! -f "$gif" ]; then warn "missing $gif — skipping $name"; continue; fi
  log "media: $name"
  poster "$gif" "$idx" "$sec" "$OUT/media/${name}-poster.jpg" || warn "no ImageMagick/ffmpeg — poster for $name not generated"
  if have ffmpeg; then
    # H.264, even dimensions (yuv420p requirement), web-optimised. ~1-3 MB instead of tens of MB of GIF.
    ffmpeg -y -loglevel error -i "$gif" \
      -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p" \
      -c:v libx264 -preset slow -crf 28 -movflags +faststart -an \
      "$OUT/media/${name}.mp4"
  else
    warn "ffmpeg not found — copying the GIF for $name (the page falls back to it automatically)"
    cp "$gif" "$OUT/media/${name}.gif"
  fi
done
cp "$ROOT/assets/presenter.png" "$OUT/media/presenter.png"

# ---------------------------------------------------------------- screenshots
SHOTS=(lv-linear-measurements mmode-measurements la-segmentation lv-auto-segmentation)
for s in "${SHOTS[@]}"; do
  src="$ROOT/docs/screenshots/$s.png"
  if [ ! -f "$src" ]; then warn "missing $src"; continue; fi
  log "screenshot: $s"
  cp "$src" "$OUT/screenshots/$s.png"
  if have convert; then
    convert "$src" -resize 1200x -strip -interlace Plane -quality 80 "$OUT/screenshots/thumbs/$s.jpg"
  else
    warn "no ImageMagick — using the full PNG as thumbnail for $s"
    cp "$src" "$OUT/screenshots/thumbs/$s.jpg"
  fi
done

# ---------------------------------------------------------------- traffic report (github-repo-stats data branch)
log "traffic report from branch $STATS_BRANCH"
if git -C "$ROOT" fetch -q --depth=1 origin "+refs/heads/$STATS_BRANCH:refs/remotes/origin/$STATS_BRANCH" 2>/dev/null \
   && git -C "$ROOT" ls-tree -d "origin/$STATS_BRANCH" "$STATS_REPO/latest-report" 2>/dev/null | grep -q .; then
  git -C "$ROOT" archive --format=tar "origin/$STATS_BRANCH" "$STATS_REPO/latest-report" | tar -x -C "$OUT"
else
  warn "branch $STATS_BRANCH (or $STATS_REPO/latest-report in it) not available — site is built without the report"
fi
# Short, memorable URL: /stats/ → the report.
cat > "$OUT/stats/index.html" <<EOF
<!doctype html><meta charset="utf-8"><title>SonoForge — traffic report</title>
<meta http-equiv="refresh" content="0; url=../$STATS_REPO/latest-report/report.html">
<link rel="canonical" href="../$STATS_REPO/latest-report/report.html">
<p>Redirecting to the <a href="../$STATS_REPO/latest-report/report.html">traffic report</a>…</p>
EOF

# ---------------------------------------------------------------- summary
log "done → $OUT"
if have du; then du -sh "$OUT" | sed 's/^/  total: /'; fi
find "$OUT" -type f | sort | sed "s|^$OUT/|  |"