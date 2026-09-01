# Release Process

The initial `0.1.0` train publishes all 13 distributions together. Every
distribution must be version `0.1.0`, and internal requirements must use
`>=0.1.0,<0.2.0`. Releases become independently versioned after this train.
The local publisher invokes exact `uv 0.11.28` through `uvx` and exits before
publication if that isolated command resolves another version.

## Prepare

1. Start from a clean release commit that has passed GitHub CI.
2. Run `uv lock --check`, the full feasible tests, Ruff, formatting, Ty, and the
   strict documentation build.
3. Build and verify the family without a broker:

   ```text
   uv run scripts/build_release.py --dist-dir dist --digest-manifest release-digests.json
   ```

4. Confirm exactly 26 artifacts pass metadata, dependency, README, legal-file,
   isolated wheel/sdist install, CLI, digest, and package-family checks.
5. Run the RabbitMQ artifact smoke through the green GitHub CI artifact job.

Never rebuild after uploading any artifact. PyPI filenames and release contents
are immutable. Retry with the exact same 26 files and digest manifest.

## Local Initial Release

The sole-maintainer initial release uses separate account-wide TestPyPI and
PyPI API tokens. Tokens must never enter this repository, command arguments,
shell history, logs, or agent messages. Store each token through the hidden
password prompt before release:

```text
uvx --from uv==0.11.28 uv auth login https://test.pypi.org/legacy/ --username __token__
uvx --from uv==0.11.28 uv auth login https://upload.pypi.org/legacy/ --username __token__
```

The default uv credential backend stores these credentials as plaintext outside
the repository. Remove the local credentials and revoke both temporary tokens
in the registry account pages immediately after publication.

1. Validate every TestPyPI upload command without publishing:

   ```text
   uv run scripts/publish_release.py testpypi --dist-dir dist --digest-manifest release-digests.json
   ```

2. Upload one verified wheel/sdist pair at a time in dependency order:

   ```text
   uv run scripts/publish_release.py testpypi --dist-dir dist --digest-manifest release-digests.json --execute
   ```

3. Validate exact TestPyPI filenames and SHA-256 values, then perform isolated
   installation smoke tests using direct TestPyPI artifact URLs:

   ```text
   uv run --no-project scripts/testpypi_smoke.py --digest-manifest release-digests.json
   ```

4. Create the annotated `v0.1.0` tag on the exact tested commit. Do not move or
   recreate the tag.
5. Dry-run and then publish the unchanged artifacts to PyPI:

   ```text
   uv run scripts/publish_release.py pypi --dist-dir dist --digest-manifest release-digests.json
   uv run scripts/publish_release.py pypi --dist-dir dist --digest-manifest release-digests.json --execute
   ```

6. Verify all 26 PyPI hashes against `release-digests.json`, perform a clean
   PyPI-only consumer install, push the tag, and remove local credentials:

   ```text
   uv run --no-project scripts/testpypi_smoke.py --registry pypi --digest-manifest release-digests.json
   uvx --from uv==0.11.28 uv auth logout https://test.pypi.org/legacy/ --username __token__
   uvx --from uv==0.11.28 uv auth logout https://upload.pypi.org/legacy/ --username __token__
   ```

The publisher checks the digest manifest before every dry run or upload. It
uses each registry's simple index as `--check-url`, so rerunning after a partial
failure skips byte-identical files and rejects mismatched artifacts.

Before the first divergent package version, release tooling must gain
selected-package manifests, per-package tags and version validation, and
dependency-aware publishing. The RabbitMQ persistent-streams adapter remains
conditional on its documented operational gates; version `0.1.0` alone is not
approval for an unqualified production deployment.
