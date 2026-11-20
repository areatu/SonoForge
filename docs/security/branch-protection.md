# Branch protection and required checks (QH-2a.2, issue #181)

**Snapshot:** 2026-11-20
**Status:** PROPOSED — applying rulesets/branch protection requires a repository
administrator; this document is the exact configuration to apply. Nothing here is
active until an admin saves it in **Settings → Rules → Rulesets**.

## Goal

`main` must not accept a merge unless every CI gate that can run on the PR is green,
and force-pushes / deletions of `main` are forbidden. This closes the "policy is
documented but not enforced" gap of QH-2a.2 (#181).

## Required status checks (from `.github/workflows/`)

CI (`ci.yml`, all run on `pull_request`):

- `lint`, `typecheck`, `security_audit`, `test_inventory`
- `test_logic`, `test_compat`, `test_regression`, `test_exploratory`
- `test_gui_smoke`, `test_gui` (shards), `test_bench`, `test_security`, `test_acceptance`
- `ui_colors`, `package_smoke`, `coverage`

Security workflows:

- `codeql.yml` → `analyze`
- `dependency-review.yml` → its single check run on `pull_request`
- `security-audit.yml` → its check run

Nightly suites (`nightly-suites.yml`) are **not** required checks — they are
advisory/report-only by design (mutation score is report-only until the baseline
is set, see issue #620).

## Proposed ruleset for `main`

- **Bypass permissions:** none (not even admins) for the enforcement rules below;
  admins may keep "include administrators" off so the policy cannot be silently
  bypassed during an incident.
- **Require status checks to pass** before merging: the list above, with
  "Require branches to be up to date before merging" enabled.
- **Require pull request reviews before merging:** ≥ 1 approving review
  (the repo is single-maintainer in practice; keep 1 so the rule is enforceable).
- **Restrict pushes / force pushes / deletions** on `main`: deny.
- **Require linear history** or squash-merging: repo convention is merge commits
  from Arena branches; do not require linear history.
- **Block secrets in push:** enable secret scanning push protection (already on
  repo level if enabled; verify).

## Verification after applying

1. Open a dummy PR that fails `lint` — merge must be blocked.
2. Confirm the ruleset shows all required checks as "expected" on a healthy PR.
3. Record the ruleset name and date in this file's snapshot line and in #181.
