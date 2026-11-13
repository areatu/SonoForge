# Contributing to SonoForge

Thank you for your interest in contributing to SonoForge! This document provides guidelines for contributing to the project.

## How to Contribute

### Reporting Issues

If you find a bug or have a feature request, please [open an issue](https://github.com/areatu/SonoForge/issues) with:

- A clear description of the problem or suggestion
- Steps to reproduce (for bugs)
- Your environment: OS, Python version, SonoForge version

### Submitting Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests: `python -m pytest tests/ -x`
5. Commit with a clear message
6. Push to your fork and open a Pull Request

### Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) conventions
- Use type hints where practical
- Keep functions focused and concise
- Write docstrings for public APIs
- Say *why* in a sentence instead of naming a spec. `# QH-1b.2 slice 2` is readable
  only next to the spec that issued the number. `scripts/check_id_references.py` (the
  `lint` job) counts such IDs (`QH-`, `TP-`, `UI-`, `UD-`, `UQ-`, `UA-`, `S-nn`, `A-nn`,
  `D-nn`) in `src`: the count may only go down, so a new reference needs an older one
  turned into a reason. `--fix` records a cleanup, `--list` prints the worklist.
- Documents may not point at things a clone does not have. `scripts/check_doc_links.py`
  (the `lint` job) fails on a relative Markdown link to a missing file and on any
  mention of a documentation directory that `.gitignore` excludes (the local
  implementation plans are such files): name a plan by its file name and say that it
  is not kept in the repository.

### Testing

- Add tests for new functionality
- Ensure all tests pass before submitting
- Test on both Linux and Windows if possible

### Test inventory gate (required)

CI runs the `pytest counters gate` **before** any test job. It collects
`tests/unit/` on your change and on its base commit (the merge-base with
`main`) and compares four counters: `total`, `gui`, `not_gui`, `gui_files`.

* **Adding tests needs no bookkeeping** — there is no committed baseline to
  refresh, so parallel PRs no longer conflict on it (issue #473).
* **A counter that goes down fails** — deleting tests, merging test files or
  dropping `gui` markers. If that is intended, add a trailer to any commit of
  the change, with a reason of at least ten characters:

  ```text
  Test-Inventory-Decrease: test_old_parser.py merged into test_parser.py
  ```

  The gate lists the vanished node ids either way, so the reviewer sees which
  tests went.

Check locally before pushing (needs `origin/main` fetched):

```bash
uv run python .github/scripts/check_test_inventory.py            # base = merge-base with origin/main
uv run python .github/scripts/check_test_inventory.py --base HEAD~3
```

### A test must be able to fail (required)

A green test protects something only if a change in the code can turn it red.
The `lint` job therefore runs `scripts/check_test_signal.py` — the **test-signal
ratchet** (#327). Every new test needs a *verifying signal*: an `assert` that can
fail, `pytest.raises` / `warns` / `fail`, a mock or numpy `assert_*` call, a Qt
`waitSignal` / `waitUntil`, or `jsonschema.validate`. A test that only builds an
object and asserts nothing fails the check.

- Assert on the behaviour, not on existence: `assert widget is not None` passes
  the gate but protects nothing, and neither `assert True` nor `assert x or True`
  is a signal.
- If a test delegates its checks to a helper, name the helper `assert_*`
  (`_assert_valid(report)`); the scan is static and cannot see inside other names.
- A deliberate "must not raise" test is allowed only as an explicit exception:
  mark it `@pytest.mark.smoke` **and** add its node id with the reason under
  `"smoke"` in `scripts/test_signal_baseline.json`.
- Tests that take the `benchmark` fixture measure instead of verify and are not
  counted; neither are manual diagnostics marked `@pytest.mark.interactive`,
  which `addopts` keeps out of every default and CI run.
- The legacy debt (tests that had no signal before the gate) is listed by node
  id in the same JSON file and may only shrink. After you strengthen or delete
  such a test, run `python scripts/check_test_signal.py --fix` and commit the
  baseline with the change. `--fix` never adds an entry, so a renamed or moved
  legacy test needs its node id edited by hand.

The metrics (tests without a signal, with at most one `assert`, without any
`assert`) are on the run page: Checks → lint → Summary.

### Viewer tests and private state (required, #327, #536)

`ViewerWidget` is being decomposed (#305, #307), and a test that reads
`w._contour_stage` or calls `w._apply_caliper_node_drag(...)` pins how the
widget works instead of what it promises. `scripts/check_test_private_access.py`
counts such references in `tests/unit/test_*viewer*.py`; the count may only go
down, and a new test file with `viewer` in its name starts with no allowance.

The viewer debt is not only in viewer-named files: the contour, caliper and zoom
suites (`test_caliper_*`, `test_lv_trace_contour.py`, `test_spline_editor.py`,
`test_area_*`) build the same widget. A `ViewerWidget` group in the baseline
selects every test file that mentions `ViewerWidget` / `make_viewer` / `viewer`
and counts references rooted at `viewer`, `w`, `widget` and `viewer_widget`, so a
new `viewer._private` there fails the gate too.

- Prefer the public API (`w.ghost_mode`, `w.refresh_dicom_tags_overlay()`). When
  the behaviour you need to check has no public handle, give the widget a small
  public accessor instead of adding a private reference.
- After replacing private access, run `python scripts/check_test_private_access.py --fix`
  and commit the baseline with the change: a lower count that is not recorded
  fails the check, so an improvement cannot be spent again later. `--fix` never
  raises the baseline.
- `python scripts/check_test_private_access.py --list` shows where the
  references live and which private names are used most.

### MainWindow / AppController / Orthanc tests and god-object ratchets (required, #474, #536)

The same private-access ratchet holds the tests that build the real window,
controller or Orthanc dialog: a test file that mentions `MainWindow` /
`make_main_window` (or `AppController`, `OrthancStudyDialog`) may not add
references like `window._tabs`, `controller._state` or `dialog._downloading` —
the `groups` section of `scripts/test_private_access_baseline.json` records the
current numbers, and the same `--fix` rule applies.

Two more `lint` ratchets keep the large classes from growing back:

- `python scripts/check_class_size.py` — classes above 1 500 lines (lines and
  number of methods), modules above 2 000 lines, and the number of `self.*`
  attributes of `ViewerWidget`, `MainWindow`, `AppController` are ceilings in
  `scripts/class_size_baseline.json`. Adding a method to `MainWindow` without
  removing another fails; put new behaviour into a collaborator. After a
  refactoring, `--fix` lowers the ceilings (it never raises one).
- `python scripts/check_broad_excepts.py` — the number of broad handlers
  (`except Exception`, bare `except:`) and of *silent* ones (the body only
  passes, continues or returns a constant) per layer may only go down. Log the
  failure (`log_boundary_failure` outside `domain`, the module logger inside
  it) or catch the specific exception. `--list` prints the silent handlers.

### Defects and the tests that prove them (required)

A fix for a P0/P1 defect comes with a **negative test**: one that fails on the
code before the fix and passes after it. A test that only describes the
behaviour after the fix cannot tell whether the defect ever existed (#323 sat
behind 8 836 green tests for that reason). Say in the PR how you verified that
the test fails without the fix.

New tests have to earn their place in the inventory baseline: each addition is a
new verifiable behaviour, not a copy of an existing check.

### Changelog (required)

`CHANGELOG.md` keeps only an **index** of the changes that are not released yet. Add your
entry as a fragment `changelog.d/NNN-type-scope-ref.md` (the next free number; the format
and the release procedure are in `changelog.d/README.md`) and put one summary line with a
link to it at the top of the `Unreleased` index. `tests/unit/test_docs_links.py` checks that
every fragment has exactly one index line and the other way round, that the index is ordered
newest first, and that every review in `docs/reviews/` carries its snapshot header.

### Commit Messages

Use clear, descriptive commit messages:

```
feat(doppler): add spectral Doppler envelope tracing

fix(scroll): prevent frame decode race on fast scroll

docs(readme): update installation instructions
```

## Development Setup

```bash
# Clone and install in development mode
git clone https://github.com/areatu/SonoForge.git
cd SonoForge
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
python -m pytest tests/
```

## License

By contributing, you agree that your contributions will be licensed under the GPL-3.0 License.
