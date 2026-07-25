# CI Fix + Release Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the failing CI test job (exit code 134/SIGABRT) and implement a release workflow that builds a `.deb` package and publishes it as a GitHub Release artifact.

**Architecture:** The CI test failure is caused by Qt/xvfb crash on headless Ubuntu. Fix involves proper xvfb wrapper or offscreen platform configuration. The release workflow uses a standalone `release.yml` triggered by `v*` tags, building a `.deb` via PyInstaller + FPM, running smoke tests, and attaching the package to GitHub Releases.

**Tech Stack:** GitHub Actions, PySide6, xvfb, PyInstaller, FPM, Debian packaging

---

## Global Constraints

- Python `>=3.10,<3.12`
- PySide6 `>=6.6`
- Build system: hatchling
- License: GPL-3.0-only
- Author: Кувилкин Виталий, areatu@yandex.ru
- Package name: `sonoforge`, main package: `echo_personal_tool`
- Test marker: `gui` (skip with `-m "not gui"`)
- Default pytest addopts: `-q -m 'not interactive'`

---

## Task 1: Fix CI Test Job (SIGABRT / Exit Code 134)

**Root Cause:** The test job on `ubuntu-latest` crashes with SIGABRT. The current CI installs xvfb but doesn't use `xvfb-run` to wrap pytest. Instead, it relies on `QT_QPA_PLATFORM=offscreen`, which may not be set or may conflict with xvfb setup. The crash occurs during Qt initialization in headless mode.

**Current CI test steps:**
```yaml
- name: Run tests (Linux)
  if: runner.os == 'Linux'
  run: pytest tests/unit/ -q --tb=line -m "not gui" --no-header
```

**Fix approach:** Wrap pytest with `xvfb-run` and set `QT_QPA_PLATFORM=offscreen` explicitly.

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add `QT_QPA_PLATFORM` env and wrap pytest with `xvfb-run`**

Edit `.github/workflows/ci.yml`. In the `test` job, add an env block and modify the Linux test step:

```yaml
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-latest
            python-version: "3.11"
          - os: macos-latest
            python-version: "3.11"
          - os: windows-latest
            python-version: "3.11"
    env:
      QT_QPA_PLATFORM: offscreen
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      # Linux: install display server for headless Qt
      - name: Install system dependencies (Linux)
        if: runner.os == 'Linux'
        run: |
          sudo apt-get update
          sudo apt-get install -y xvfb libxkbcommon-x11-0 libxcb-xinerama0 libxcb-cursor0 libegl1

      - run: pip install -e ".[dev]"

      # Linux: run with xvfb-run
      - name: Run tests (Linux)
        if: runner.os == 'Linux'
        run: xvfb-run -a pytest tests/unit/ -q --tb=line -m "not gui" --no-header

      # macOS/Windows: run directly
      - name: Run tests (macOS/Windows)
        if: runner.os != 'Linux'
        run: pytest tests/unit/ -q --tb=line -m "not gui" --no-header
```

- [ ] **Step 2: Verify locally**

The fix cannot be fully verified locally (no xvfb), but verify the YAML syntax:
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "fix(ci): wrap pytest with xvfb-run to fix SIGABRT on headless Ubuntu"
```

---

## Task 2: Create Smoke Test Script

**Files:**
- Create: `scripts/smoke_test.sh`
- Create: `scripts/` (if not exists)

**Purpose:** Validate that the built Debian package is installable and the binary runs correctly.

- [ ] **Step 1: Create `scripts/smoke_test.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Smoke test for SonoForge .deb package
# Usage: ./scripts/smoke_test.sh <path-to-deb>

DEB_PATH="${1:?Usage: $0 <path-to-deb>}"

echo "=== Smoke Test: SonoForge ==="
echo "Package: $DEB_PATH"

# 1. Validate .deb file exists and is readable
if [[ ! -r "$DEB_PATH" ]]; then
    echo "FAIL: Cannot read $DEB_PATH"
    exit 1
fi
echo "PASS: .deb file exists and is readable"

# 2. Check file size (should be > 1MB for a real package)
SIZE=$(stat -c%s "$DEB_PATH" 2>/dev/null || stat -f%z "$DEB_PATH")
if (( SIZE < 1048576 )); then
    echo "FAIL: Package too small ($SIZE bytes), expected > 1MB"
    exit 1
fi
echo "PASS: Package size OK ($(( SIZE / 1048576 )) MB)"

# 3. Validate .deb structure (needs dpkg-deb)
if command -v dpkg-deb &>/dev/null; then
    if dpkg-deb --info "$DEB_PATH" >/dev/null 2>&1; then
        echo "PASS: .deb metadata is valid"
    else
        echo "FAIL: .deb metadata invalid"
        exit 1
    fi

    # Check it contains the binary
    CONTENTS=$(dpkg-deb -c "$DEB_PATH" 2>/dev/null || true)
    if echo "$CONTENTS" | grep -q "sonoforge"; then
        echo "PASS: Package contains sonoforge binary"
    else
        echo "WARN: sonoforge binary not found in package listing"
    fi
else
    echo "SKIP: dpkg-deb not available, skipping structural checks"
fi

echo ""
echo "=== All smoke tests passed ==="
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/smoke_test.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke_test.sh
git commit -m "ci: add smoke test script for .deb validation"
```

---

## Task 3: Create Release Workflow

**Files:**
- Create: `.github/workflows/release.yml`

**Trigger:** Push tag `v*`
**Pipeline:** Build tests → build `.deb` → smoke test → create GitHub Release with `.deb`

- [ ] **Step 1: Create `.github/workflows/release.yml`**

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: write
  id-token: write

jobs:
  test:
    uses: ./.github/workflows/ci.yml

  build-deb:
    needs: [test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install build dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y xvfb libxkbcommon-x11-0 libxcb-xinerama0 libxcb-cursor0 libegl1
          pip install pyinstaller fpm

      - name: Install project
        run: pip install -e .

      - name: Extract version from tag
        id: version
        run: echo "VERSION=${GITHUB_REF_NAME#v}" >> "$GITHUB_OUTPUT"

      - name: Build with PyInstaller
        run: |
          pyinstaller sonoforge.spec --noconfirm
          chmod +x dist/sonoforge/sonoforge 2>/dev/null || true

      - name: Validate build
        run: |
          ls -la dist/sonoforge/
          test -f dist/sonoforge/sonoforge || test -f dist/sonoforge/sonoforge.exe

      - name: Package as .deb
        run: |
          fpm -s dir -t deb \
            --name sonoforge \
            --version "${{ steps.version.outputs.VERSION }}" \
            --description "Personal desktop echocardiography analysis tool" \
            --license "GPL-3.0" \
            --url "https://github.com/areatu/SonoForge" \
            --maintainer "Кувилкин Виталий <areatu@yandex.ru>" \
            --depends "libxcb1" \
            --depends "libxcb-cursor0" \
            --depends "libxkbcommon-x11-0" \
            --deb-systemd-enable=false \
            -C dist/sonoforge \
            --prefix /opt/sonoforge \
            --package "../sonoforge_${{ steps.version.outputs.VERSION }}_amd64.deb" \
            .

      - name: Smoke test
        run: |
          chmod +x scripts/smoke_test.sh
          ./scripts/smoke_test.sh "../sonoforge_${{ steps.version.outputs.VERSION }}_amd64.deb"

      - name: Upload .deb artifact
        uses: actions/upload-artifact@v4
        with:
          name: sonoforge-deb
          path: sonoforge_${{ steps.version.outputs.VERSION }}_amd64.deb
          retention-days: 7

  github-release:
    needs: [build-deb]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Download .deb artifact
        uses: actions/download-artifact@v4
        with:
          name: sonoforge-deb
          path: .

      - name: Generate changelog
        id: changelog
        run: |
          # Get commits since last tag
          PREV_TAG=$(git describe --tags --abbrev=0 HEAD^ 2>/dev/null || echo "")
          if [[ -n "$PREV_TAG" ]]; then
            CHANGES=$(git log "$PREV_TAG..HEAD" --pretty=format:"- %s" --no-merges)
          else
            CHANGES=$(git log --pretty=format:"- %s" --no-merges -20)
          fi
          # Write to file (multiline output)
          echo "$CHANGES" > /tmp/changelog.md

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          name: "SonoForge ${{ github.ref_name }}"
          body_path: /tmp/changelog.md
          files: |
            sonoforge_*.deb
          draft: false
          prerelease: ${{ contains(github.ref_name, '-') }}
          generate_release_notes: false
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add release workflow for .deb + GitHub Releases"
```

---

## Task 4: Refactor CI into Reusable Workflow (Optional, recommended)

Currently `ci.yml` has both workflow triggers AND can be called as a reusable workflow. This needs a small adjustment so `release.yml` can reference it.

- [ ] **Step 1: Add `workflow_call` trigger to ci.yml**

Edit `.github/workflows/ci.yml` to add `workflow_call`:

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
  workflow_call:
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add workflow_call trigger for reuse in release workflow"
```

---

## Verification

After all tasks are complete:

1. **Syntax check:**
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); yaml.safe_load(open('.github/workflows/release.yml'))"
```

2. **Push and verify CI runs:**
```bash
git push origin main
```

3. **Create a test tag to verify release workflow:**
```bash
git tag v0.1.0-test
git push origin v0.1.0-test
```
(Cancel after verification or let it run to test the full pipeline)

---

## Open Questions for User

1. **CI SIGABRT root cause:** Do you have the CI log output showing the exit code 134? That would confirm whether it's xvfb-related or something else (e.g., a specific test crashing).

2. **Release workflow vs existing `release` job in ci.yml:** The current `ci.yml` already has a `release` job that publishes to PyPI. Do you want to:
   - Replace PyPI release with GitHub Release + .deb?
   - Keep both (PyPI for `pip install`, GitHub Release for .deb)?
   - Remove the PyPI release entirely?

3. **PyInstaller spec:** The `sonoforge.spec` file currently bundles models (40-200MB). Do you want to update it to exclude models (since they're downloaded separately)?

4. **Debian package name:** Currently `sonoforge`. Should it be `sonoforge-desktop` or `echo-personal-tool`?
