# Build and verify an offline Skill package

This maintainer operation packages the complete installable Skill, without game
projects, showcase media, engines, environments or caches. It does not publish,
create a tag, change a version, replace a host installation or submit generation.
Package verification and publication are separate operations.

From the repository root, using Python 3.10+:

```sh
python3 scripts/check_release.py
python3 scripts/build_release.py build --verify-install
```

When other work is modifying the checkout, select a frozen tag or commit instead:

```sh
python3 scripts/build_release.py build --ref v0.15.2 --verify-install
```

`--ref` resolves once to an immutable commit, reads its Skill manifest and only
the corresponding Git blobs, and rejects unlisted files or linked tree entries.
It never checks out or archives the repository tree. The returned `source_commit`
identifies that lookup; the archive receipt continues to identify the exact
package bytes, so identical packages can be reused across documentation commits.
`--repo PATH` selects a repository; `--ref` and `--source` are mutually exclusive.
The working directory and manifest are never reset or refreshed. Both build
routes execute the selected package's CLI version command; use a trusted source.

The builder reads only the files declared by the current Skill manifest, plus
that manifest. It checks each byte count and SHA-256, the manifest's own file-list
digest and the actual CLI version. Missing/unlisted source files, symlinks,
unsafe or case-colliding names and declared caches are rejected. Incidental
`__pycache__`, `.pyc`, `.pyo` and `.DS_Store` files are omitted. The source-size
limit is 32 MiB; this route cannot become a full-project archive.

The output directory defaults to ignored `dist/`. `--output-dir PATH` selects a
different directory outside the Skill source. A build produces exactly:

```text
greybox-to-multistyle-art-<version>.zip
greybox-to-multistyle-art-<version>.zip.sha256
greybox-to-multistyle-art-<version>.zip.release.json
```

The ZIP contains one `greybox-to-multistyle-art/` directory. The receipt records
version, archive/manifest hashes, byte counts and file count, with no local paths
or timestamps. ZIP entry ordering, time, file mode and compression settings are
fixed. Identical inputs produce identical bytes with the same Python/zlib
toolchain; qualify a changed toolchain rather than replacing a published archive.
An identical existing result is reused. A different existing artifact is preserved
and causes failure. No historical archive is deleted.

Verify a downloaded package against its release checksum, then optionally test an
isolated installation:

```sh
python3 scripts/build_release.py verify "dist/greybox-to-multistyle-art-<version>.zip" --sha256 "<release SHA-256>"
python3 scripts/build_release.py verify "dist/greybox-to-multistyle-art-<version>.zip" --sha256 "<release SHA-256>" --verify-install
```

Without `--sha256`, the verifier checks a matching adjacent `.zip.sha256` when
present. Otherwise it establishes internal consistency and reports the archive's
hash. A checksum obtained from a trusted release record binds the expected bytes;
an archive's self-contained manifest alone does not establish its publisher.

Normal verification reads the ZIP without extracting or executing it. It rejects
path traversal, duplicate names, links, extra/missing entries, oversized content
and mismatched hashes. `--verify-install` executes the packaged CLI version
command: use it only for a trusted archive. The roundtrip uses this checkout's
installer in a task-owned temporary directory, checks the installed manifest and
CLI version, repeats the installation to confirm zero copied bytes, then removes
its temporary source and host directories. It never selects a real host or
prepares provider dependencies.

For a release, bind this receipt to the reviewed source ref and actual CI result.
Run the package tests with:

```sh
python3 -m unittest discover -s tests -p test_release_package.py -v
```

The portable CI matrix exercises the committed source package and offline install.
After the GitHub portable and regression jobs pass, the package job builds from
the triggering commit, verifies an isolated installation and retains the ZIP,
checksum and receipt as a seven-day workflow artifact. It does not create a
GitHub Release or publish a new version.
Remote CI status is established by its actual run, not by this configuration.
See [maintenance and publication](MAINTAINERS.md).
