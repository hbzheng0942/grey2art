# Maintaining Grey2Art

[Contribution guide](../CONTRIBUTING.md) · [Release notes](../CHANGELOG.md) · [Package tools](RELEASE-PACKAGING.md)

## Source and versions

Edit `skills/greybox-to-multistyle-art/`, not a host's installed copy. Keep the package version in `runtime/greybox/__init__.py` and `MANIFEST.json` consistent. When installable files change, choose a new version and regenerate the file manifest:

```sh
python3 scripts/refresh_manifest.py
python3 scripts/check_release.py
```

Published tags and package bytes are immutable. Documentation-only changes do not require a package version. Keep the installed identifier `greybox-to-multistyle-art` stable; Grey2Art is its display name.

## Verification

Use an isolated Python 3.11+ environment for the image-dependent tests:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python scripts/check_release.py
.venv/bin/python -m unittest discover -s tests -v
```

On Windows, use `py -3` and `.venv\Scripts\python.exe`. The source check verifies the package manifest, pinned vendor files and local documentation resources. Run the relevant tests for each change, and the complete suite before publishing a changed package. Report optional skips and actual CI results separately.

For engine integration changes, use the relevant native checks and inspect the captured result. An optional Godot technical fixture is available at `tests/acceptance/native_smoke.py`; it uses an existing engine and synthetic inputs. Passing it does not establish art quality, target-device performance or real host production.

## Source review and packaging

Review the intended source revision and any history being published. The inventory reports candidate locations and categories without printing matched secret values:

```sh
python3 scripts/audit_public_release.py --ref HEAD --output evidence/source-review.json
python3 scripts/audit_public_release.py --ref HEAD --history --output evidence/history-review.json
python3 scripts/build_release.py build --ref HEAD --verify-install
```

Each audit output path must be new. Review findings in context; a source inventory does not establish media rights or comprehensive privacy clearance. Keep credentials, private conversations and game assets outside the public tree. Curated media must retain its source and permission scope in [provenance](demo/PROVENANCE.md).

The package builder includes only manifest-listed Skill files, verifies their bytes and tests installation in a disposable location. It excludes games, showcase media, repository history and caches. See [packaging](RELEASE-PACKAGING.md) for checksum verification and reproducible output behavior.

## Publishing

Publish the reviewed commit using the repository's normal branch protections. Keep source, package manifest, archive checksum and any release tag bound to the same revision. Check the actual target CI run, downloadable package, installation instructions, language navigation, media and feedback routes. A configured workflow is not a completed CI run.

Record user-facing changes in [release notes](../CHANGELOG.md). Keep private development notes and operational receipts outside the public source tree. Publishing source or a technical fixture does not grant paid-generation authority or replace a project's user acceptance.
