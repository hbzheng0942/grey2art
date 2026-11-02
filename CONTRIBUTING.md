# Contributing to Grey2Art

[English](CONTRIBUTING.md) · [简体中文](CONTRIBUTING.zh-CN.md)

Grey2Art turns one gameplay greybox into playable prototypes in multiple art styles. Its installed Skill identifier is `greybox-to-multistyle-art`.

## Ways to contribute

- **Fix a problem:** a reproducible bug, a workflow failure or unclear recovery instructions.
- **Improve an integration:** a host, engine or image/model provider route with a real user scenario and observed results.
- **Improve the docs:** installation, examples, troubleshooting or matched English/Chinese updates.
- **Share a case:** a playable greybox and its actual art variants, including author credit and limits.

Small fixes can go straight to a pull request. Discuss a new integration, large feature or change to CLI/task/recovery contracts in this repository's **Issues** first. English and Chinese reports are welcome.

## Make a focused change

1. Start from `main` and keep the change limited to the reported problem. Preserve unrelated edits, original task IDs, accepted decisions and valid recovery records.
2. Edit the canonical package at `skills/greybox-to-multistyle-art/`; installed host copies are consumers. Keep documentation and English/Chinese behavior descriptions consistent.
3. Run the checks that cover the change and include the actual command, result and untested scope.
4. Submit a concise merge request or pull request describing the problem, resulting behavior, validation and compatibility impact. A maintainer reviews and merges it. Release packaging is maintainer-owned.

For documentation or curated-media changes, run the package and local-link check from the repository root:

```sh
python3 scripts/check_release.py
```

For runtime or workflow changes, use an isolated Python 3.11+ environment and run relevant tests; run the full suite when the affected scope warrants it:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -v
```

On Windows use `py -3 -m venv .venv` and `.venv\Scripts\python.exe`. Offline checks do not need provider credentials. If package files change, the maintainer must refresh their manifest and assign a new distribution version before shipping; do not modify historical releases. Tests, native execution, visual review, performance and human acceptance are separate evidence. Review agent-generated edits before submission and name the tool/model when it matters to reproduction.

## Integrations and workflow changes

Describe the input and expected endpoint, tested host/OS/engine versions and behavior before/after the change. Explain affected existing entrypoints and who will maintain a new integration. Provider changes also need configuration, charging/authorization, unknown-submission and original-task recovery behavior. Use mocks or existing authorized evidence for checks; a contribution does not authorize paid generation.

## Showcase contributions

Include a real greybox and at least two implemented art styles to propose a complete multi-style homepage case. Single-style or unfinished work is welcome as a clearly labeled work in progress. Supply:

- Actual native screenshots with comparable views and clean gameplay footage where available; identify concept or process images separately.
- Game author, source/play/download links, relevant project revision and the Skill version actually used, if known. Unknown values stay unknown.
- What changed, what mechanics stayed shared, significant manual fixes and remaining defects.
- Capture method and any cuts, crops or overlays. Offline native rendering must be identified; output video frame rate is not real-time game performance.
- The media's copyright holder and permission/license for display and redistribution. Credit upstream assets separately and keep their notices.

Submit only the small media needed for review. Keep full games, large assets, private ledgers, credentials and signed URLs in their owning projects. [Media provenance](docs/demo/PROVENANCE.md) records the current curated images.

## Rights, credit and support

Original project contributions use [MIT](LICENSE); contributions must be yours to license, and [third-party notices](THIRD_PARTY_NOTICES.md) must remain intact. Game assets and showcase media keep their own rights. Code authorship follows Git history; case, media and translation acknowledgments are maintained in [credits](CREDITS.md).

For a bug include the version, host/OS/engine, stage, minimal reproduction and redacted actual error. [Support](docs/SUPPORT.md) · [Community](docs/COMMUNITY.md) · [Security reporting](SECURITY.md). Keep sensitive reports out of public issues and group chats.
