# Plan: Coveralls Integration for SonoForge

## Context
User wants to integrate Coveralls code coverage reporting with GitHub Actions. The repo is `areatu/SonoForge` on GitHub. Coveralls page shows the repo token and recommends `coveralls-python` or the Coveralls GitHub Action.

## Goal
- Run pytest with coverage collection (`--cov`)
- Upload coverage reports to Coveralls on every CI run
- Add coverage badge to README.md

## Approach
Use `coveralls-python` library (recommended by Coveralls) + `pytest-cov` for coverage collection.

### Changes

#### 1. Add dependencies to `pyproject.toml`
- Add `pytest-cov>=5.0` to `[project.optional-dependencies] dev`
- Add `coveralls>=4.0` to `[project.optional-dependencies] dev`

#### 2. Update `.github/workflows/ci.yml`
- Add `--cov=src/echo_personal_tool --cov-report=xml` to pytest commands
- Add Coveralls upload step after tests (only on ubuntu-latest for one upload)
- Use `coverallsapp/github-action@v2` action for upload
- Set `COVERALLS_REPO_TOKEN` as GitHub secret (token: `Ba75iHQupom69tmhpJyMWM06ZXmRHMkQV`)

#### 3. Add coverage badge to `README.md`
- Add Coveralls badge markdown

## Files to modify
- `pyproject.toml` — add pytest-cov and coveralls to dev deps
- `.github/workflows/ci.yml` — add coverage collection + Coveralls upload
- `README.md` — add coverage badge

## Verification
1. Commit and push to trigger CI
2. Check Coveralls page for first coverage report
3. Verify badge renders in README
