## Summary

<!-- Briefly describe what this PR does. -->

## Changes

<!-- List the main changes made in this PR. -->

-

## Related issues

<!-- Link to related issues: Fixes #123, Closes #456 -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Refactor (no functional changes)
- [ ] Documentation update
- [ ] CI/CD change

## Checklist

- [ ] My code follows the project's coding style
- [ ] I have performed a self-review of my code
- [ ] I have added tests that prove my fix/feature works
- [ ] New and existing tests pass locally
- [ ] If the test set or `gui` markers changed, I ran `uv run python .github/scripts/update_pytest_baseline.py --fix` and committed `.github/scripts/verify_pytest_partition.py` with the tests
- [ ] Every new test can fail: it asserts on behaviour (a deliberate "must not raise" test is marked `smoke` with a reason in `scripts/test_signal_baseline.json`); after strengthening or deleting a legacy test I ran `python scripts/check_test_signal.py --fix` and committed the baseline
- [ ] If this fixes a P0/P1 defect, there is a negative test that fails without the fix (say how I checked)
- [ ] If I touched the viewer tests (`tests/unit/test_*viewer*.py`), the number of private-name references went down or stayed the same (`python scripts/check_test_private_access.py --fix`)
- [ ] I added a changelog fragment in `changelog.d/` and its summary line at the top of the `Unreleased` index in `CHANGELOG.md`
- [ ] I have updated the documentation if needed

## Screenshots (if applicable)

<!-- Add screenshots to demonstrate visual changes. -->
