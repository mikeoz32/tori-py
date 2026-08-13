# Release Process

> **First-release prerequisites:** Before the first workflow run, reserve all 12
> project names on both PyPI and TestPyPI. Configure each project with the exact
> GitHub Actions trusted publisher for this repository, `.github/workflows/release.yml`,
> and environments `testpypi` or `pypi` as appropriate. Create both GitHub
> environments and configure `pypi` with required manual approval. Environment
> protection cannot be enforced by workflow YAML; do not run a release until an
> administrator has verified these settings.

The current tooling is intentionally scoped to the coordinated initial `0.1.0`
train. All 12 distributions must be version `0.1.0`, internal requirements use
`>=0.1.0,<0.2.0`, and the workflow accepts only the exact full tag `v0.1.0`.
The workflow fails closed if package versions differ.

Each distribution follows independent Semantic Versioning after the initial
train. Before the first divergent package version, release tooling must gain
selected-package manifests, per-package tags and version validation, and
dependency-aware publishing. The current workflow does not support divergence.

## Prepare

1. Confirm all external prerequisites above, package versions, internal ranges,
   changelog entries, and package README status statements.
2. Refresh `uv.lock` with `uv lock` and run `uv lock --check`.
3. Run release-script tests, the full feasible test suite, Ruff, formatting, type
   checks, and strict documentation builds through `uv`.
4. Run `uv run scripts/build_release.py --dist-dir dist --digest-manifest release-digests.json`.
5. Confirm exactly 24 artifacts were built and that wheel/sdist metadata,
   dependencies, README rendering, `LICENSE`, package-local `NOTICE`, isolated
   installs, and the generated SHA-256/size manifest all pass verification.

## Tag And Publish

1. Create the release commit only after preparation passes, then create the
   exact `v0.1.0` tag on that commit and push the tag. The tag starts the release;
   artifacts are never built from an untagged or ambiguously named branch.
2. The workflow resolves the exact tag to one immutable commit SHA, checks out
   all source jobs at that SHA, rebuilds and verifies the 24 artifacts, and
   uploads those artifacts with `release-digests.json` as one GitHub artifact.
3. The workflow attests only the 24 package files, publishes them to TestPyPI
   from the `testpypi` environment, and verifies TestPyPI filenames and SHA-256
   values against the digest manifest before isolated install smoke tests.
4. A required reviewer approves the protected `pypi` environment. The workflow
   downloads the original GitHub artifact, revalidates every file against the
   manifest, and publishes to PyPI without rebuilding.
5. If retrying through `workflow_dispatch`, enter the exact full tag `v0.1.0`.
   The workflow fetches `refs/tags/v0.1.0` and resolves it to its exact commit.

Never publish automatically based only on a branch update or TestPyPI success.
The RabbitMQ persistent-streams adapter additionally requires its documented
conditional operational gates; version `0.1.0` alone is not approval for an
unqualified production deployment.
