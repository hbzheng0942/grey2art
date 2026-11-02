# Repository work

- Read `GIT_BOUNDARIES.md` before Git, cleanup or cross-project operations.
- Edit the canonical Skill in `skills/greybox-to-multistyle-art/`. Installed copies, downloaded packages and external game projects are separate inputs.
- Read the package version from `MANIFEST.json` and `runtime/greybox/__init__.py`; keep them consistent. Do not change published tags or reuse a version for different package bytes.
- Route requests by the user's intent, observed project state and requested endpoint. Preserve actual task decisions and distinguish implementation, native checks and human acceptance.
- Keep new AI mesh production image-conditioned and bind it to the approved reference. Honor the user's current provider/model policy; an available tool or account balance does not authorize paid production.
- Preserve valid task/recovery identities and completed resources. Work incrementally and avoid copying game projects, engines, dependencies or caches into checkpoints.
- Run `python3 scripts/check_release.py` and relevant tests before publication. Refresh manifest hashes only when installable Skill files change. Follow [maintenance](docs/MAINTAINERS.md) for distribution checks.
- Use `main` for completed development and delivery. Preserve collaborators' dirty work, use normal fast-forward pushes and keep published version checkpoints immutable.
- Keep public documentation useful to people and agents. Keep private notes, credentials, supplier recovery data and internal process records outside the public source tree.
- Preserve the vendored Lux license, pinned upstream hashes and compatible credential/cache namespace.
