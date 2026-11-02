# Migrate from 0.3 to 0.4

Preserve the old installation identity and all project ledgers. Upgrade the small skill package with `scripts/install.py --host HOST --replace`; use the returned backup path for `--rollback`. Do not copy projects, assets, virtual environments or import caches into an installation backup. Reuse the external Python runtime on subsequent upgrades.

Historical Godot plans, `res://` paths and `--godot` arguments remain supported. They are not rewritten into Unity plans. Existing approvals keep their original input/artifact scope; a new runtime, importer, shader or rendering configuration requires affected native checks to run again. A technical upgrade does not invent a new creative decision or a spending grant.

For new Unity work, declare `engine: unity`, an `Assets/...unity` baseline, and Unity workspace roots under `Assets/`. Run explicit `engine configure` before intake to resolve the pinned packages and default URP resources. Keep the actual package lock. The adapter creates owned scene variants and leaves gameplay components and source scenes intact. An unchanged canonical model outside `Assets/` is admitted by the packaged Unity adapter using verified APFS cloning or a bounded, recorded small-file copy; larger unsupported transfers fail with a repair action.

Standalone image jobs do not require H3 or a mesh plan. Configure a non-secret image profile once, bind it with `host configure --image-profile NAME`, and use the same submit/status/fetch/resume operations from any host. Preserve the old profile and recovery IDs for running jobs. Changing profile names, credentials or hosts never permits resubmitting a task with an unknown outcome.

Use current invocation evidence to refresh only missing session capabilities. A native image generator, an external image API, model pixel understanding and user image presentation are independent. A host can use CLI without MCP or subagents. Long output belongs in local logs, with only status and repair actions returned to the model.

## Windows native execution

Install the same source package with Python 3.10+ or the WorkBuddy managed Python connector. Use the actual `.exe` engine paths discovered by `host discover`; configure missing paths explicitly. Import the generated connector in WorkBuddy and retain Flash 1017 as the main model. There is no requirement to install Node.

Use one copy of the case's required `Assets`, `Packages` and `ProjectSettings`, plus small plans and canonical-asset manifests. Exclude `Library`, logs and prior platform Players. An existing macOS receipt is reference material; assemble/capture/validate the scene locally and export a Windows Player with the installed Unity platform module. Run that Player locally and retain its own telemetry and native log. Do not claim Windows compatibility from macOS, simulated path tests or a successful compile alone.

Credentials, a host login/connector import, Unity licensing and access to the Windows machine require the user's own environment. Report exact missing actions together. Once supplied, continue the existing task and refresh only the affected capability/evidence.
