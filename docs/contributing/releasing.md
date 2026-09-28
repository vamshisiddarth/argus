# Releasing

Every change goes through the same seven stages. Each stage has a gate; nothing moves forward until
the gate passes. The key rule: **nothing reaches PyPI until the exact files being published have been
live-tested on real cloud accounts.**

```
design → plan → build → test (CI) → release candidate → live test → publish
                                         (pre-release)     (real accounts)   (PyPI)
```

v0.6.0 was live-tested only after it had been published. A packaging bug (the `integrations/`
package missing from the wheel) reached PyPI and needed the 0.6.1 hotfix. This flow exists so that
can't happen again.

## 1. Design

For anything beyond a small fix, write a short issue or design note: what changes, why, and what
could break (including packaging, deploy templates, and upgrade behavior for existing users).

**Gate:** the approach is agreed before code is written.

## 2. Plan

The PR description lists how the change will be proven: the unit tests, and the **live-test cases**
to add to the live-testing plan for anything that touches cloud APIs, deploys, notifications, Jira,
or packaging.

**Gate:** every behavior change has a test that will fail on the old code.

## 3. Build

Code plus tests on a branch. Update `CHANGELOG.md` under the next version, and the docs pages the
change affects.

**Gate:** tests written first fail on the old code and pass on the new.

## 4. Test (CI)

Runs on every PR:

| Job | What it proves |
|-----|----------------|
| Tests (Python 3.11 / 3.12 / 3.13) | Unit and integration tests, all offline |
| Lint & Format | `ruff format --check`, `ruff check`, mypy |
| Build docs | `mkdocs build --strict` |
| **Package smoke test** | Builds the wheel, installs it in a clean venv, imports every shipped module, validates the bundled policies, and runs a stubbed `argus scan`. Tests what users install, not the source tree. |
| Trivy | No critical/high vulnerabilities with a fix available |

Run the package smoke test locally with:

```bash
python -m build
python scripts/package_smoke.py dist/argus_cloud_optimizer-*.whl
```

**Gate:** all green, then merge to `main`.

## 5. Release candidate

1. On `main`, set `core/__version__.py` to the new version and rename `## Unreleased` in
   `CHANGELOG.md` to `## vX.Y.Z (date)`. Merge that through a PR like any other change.
2. Run **Actions → Release candidate → Run workflow** with the version (no `v`).

The workflow checks the version matches the code and isn't already on PyPI, builds the wheel and
sdist **once**, runs the package smoke test, and attaches them to a GitHub **pre-release** `vX.Y.Z`.
Nothing is published.

**Gate:** the pre-release exists with both files attached.

## 6. Live test

In the live-testing repository, run the plan for this version against the real AWS, GCP, and Azure
accounts:

- Install the **exact wheel** from the pre-release:
  `pip install https://github.com/vamshisiddarth/argus/releases/download/vX.Y.Z/argus_cloud_optimizer-X.Y.Z-py3-none-any.whl`
- Deploy Lambda, Cloud Run, and Azure Function from the `vX.Y.Z` tag.
- Record results in that version's test report and commit it.

If a blocking case fails: fix it through stages 3 and 4, merge, then re-run the release-candidate
workflow for the **same version**. It replaces the pre-release, because nothing was published.

**Gate:** the test report for `vX.Y.Z` shows every blocking case passing.

## 7. Publish

On GitHub, edit the `vX.Y.Z` pre-release, untick **Set as a pre-release**, and save. That triggers
`publish.yml`, which:

1. downloads the files attached to the pre-release (the ones that were live-tested), with no rebuild
2. smoke-tests the wheel once more
3. uploads them to PyPI through the trusted publisher
4. retitles the release and removes the release-candidate banner

The docs workflow deploys the versioned docs for `vX.Y.Z` at the same time.

**Gate:** `pip install argus-cloud-optimizer==X.Y.Z` in a clean venv reports the right version.

## Hotfixes

Same path, shorter live test. Bump the patch version, fix with a regression test (stage 3), pass CI
(stage 4), cut a release candidate (stage 5), and in stage 6 run the smoke cases plus the cases
covering the bug. Then publish (stage 7).

If a published release is broken badly enough that users shouldn't install it, **yank** it on PyPI
(project settings → the version → Yank) after the fix is out. Yanked versions stay installable by
exact pin but aren't picked by default.
