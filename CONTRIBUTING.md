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

### Testing

- Add tests for new functionality
- Ensure all tests pass before submitting
- Test on both Linux and Windows if possible

### Test inventory baseline (required)

CI runs the `pytest counters gate` **before** any test job: it compares the
collected inventory against the `_BASELINE` audited snapshot in
`.github/scripts/verify_pytest_partition.py` and fails fast when they diverge.
Any change to the test set — adding, deleting or renaming test files, or
changing `gui` / `interactive` markers — must refresh the baseline **in the
same commit as the tests**:

```bash
uv run python .github/scripts/update_pytest_baseline.py --fix   # refresh _BASELINE
uv run python .github/scripts/update_pytest_baseline.py --check # verify before push
```

Commit `.github/scripts/verify_pytest_partition.py` together with the test
change. A separate follow-up commit with the counters does not unblock the
gate for the original change.

### A test must be able to fail (required)

A green test protects something only if a change in the code can turn it red.
The `lint` job therefore runs `scripts/check_test_signal.py` — the **test-signal
ratchet** (#327). Every new test needs a *verifying signal*: an `assert` that can
fail, `pytest.raises` / `warns` / `fail`, a mock or numpy `assert_*` call, a Qt
`waitSignal` / `waitUntil`, or `jsonschema.validate`. A test that only builds an
object and asserts nothing fails the check.

- Assert on the behaviour, not on existence: `assert widget is not None` passes
  the gate but protects nothing, and `assert True` is not a signal.
- If a test delegates its checks to a helper, name the helper `assert_*`
  (`_assert_valid(report)`); the scan is static and cannot see inside other names.
- A deliberate "must not raise" test is allowed only as an explicit exception:
  mark it `@pytest.mark.smoke` **and** add its node id with the reason under
  `"smoke"` in `scripts/test_signal_baseline.json`.
- Tests that take the `benchmark` fixture measure instead of verify and are not
  counted.
- The legacy debt (tests that had no signal before the gate) is listed by node
  id in the same JSON file and may only shrink. After you strengthen or delete
  such a test, run `python scripts/check_test_signal.py --fix` and commit the
  baseline with the change. `--fix` never adds an entry, so a renamed or moved
  legacy test needs its node id edited by hand.

The metrics (tests without a signal, with at most one `assert`, without any
`assert`) are on the run page: Checks → lint → Summary.

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
