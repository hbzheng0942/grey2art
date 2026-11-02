# Scoped WorkBuddy S7 hooks

Register the actual native project and WorkBuddy session **before** preparing
boards. Registration does not require `production.json` to exist: unprepared
ImageGen calls in the registered scope are blocked. The guard recognizes direct
`ImageGen` and `DeferExecuteTool` with `toolName=ImageGen`. Bash passes through
except for the exact no-provider carrier probe described below; other tools and
other projects pass through.

```sh
python3 "$SKILL/scripts/workbuddy_board_guard.py" activate \
  --project "$PROJECT" --workspace "$PRODUCTION_WORKSPACE" \
  --session-id "$ACTUAL_WORKBUDDY_SESSION_ID" \
  --scope "$PROJECT/.workbuddy/board-guard-scope.json" \
  --hooks-output "$PROJECT/.workbuddy/board-guard-proposed-settings.json"
```

This writes a registration and a **proposed** hooks configuration. It does not
edit user/project host settings or install itself. Keep the scope file outside
the production workspace's initially empty directory. Use the verified private
Python in place of `python3` where required.

The inspected WorkBuddy 5.9.2 desktop starts its embedded agent with
`--setting-sources user`. It reads top-level `hooks` from the resolved WorkBuddy
user settings file (normally `~/.workbuddy/settings.json`), then merges explicit
CLI settings and plugin/scoped hooks. A proposed JSON file under the project is
not automatically loaded. This is installed-build evidence; a real desktop
session must still demonstrate the actual hook events.

When the user has requested installation as part of the repair, select the actual
user settings path explicitly and install only this registration:

```sh
python3 "$SKILL/scripts/workbuddy_board_guard.py" install \
  --scope "$PROJECT/.workbuddy/board-guard-scope.json" \
  --settings "$ACTUAL_WORKBUDDY_USER_SETTINGS"
```

`--settings` is mandatory; the command does not guess a path. It merges standard
entries by event, deduplicates the exact scope command and preserves other
settings/hooks. A conflicting matcher/options for the same command is refused.
It checks the original file identity/hash again before atomic replacement and
preserves its mode; this detects visible concurrent edits, not an atomic lock
against an unrelated writer. A small scope-side receipt contains before/after
hashes and added/removed entries, never a copy of settings or credentials.
No app restart or global trust flag is performed. `installed=true` means only
that configuration was written; `host_hook_loading_verified` remains false.

The embedded settings reader caches user settings for 60 seconds. A new chat
alone does not guarantee a new agent process. After a normal desktop reload, or
after allowing this cache to expire, run the actual harmless carrier probe.
Official [hook documentation](https://www.workbuddy.cn/docs/cli/hooks) alone
does not prove desktop loading. Do not enable a global
`allowUntrustedFrontmatterHooks` flag to make a probe pass.

To remove only this registration's standard entries, including after
deactivation, use the same verified Python/script installation:

```sh
python3 "$SKILL/scripts/workbuddy_board_guard.py" uninstall \
  --scope "$PROJECT/.workbuddy/board-guard-scope.json" \
  --settings "$ACTUAL_WORKBUDDY_USER_SETTINGS"
```

Other scopes, other hooks, original calls and all production evidence remain.

The hook checks the existing production module's frozen dispatch and one-time
claim, then atomically consumes that claim at `PreToolUse`. Changed prompts,
missing/reordered images, unclaimed pages and repeated calls return exit 2.
`PostToolUse`/`PostToolUseFailure` retain the original call ID, arguments and raw
response in task-owned `host-guard/` sidecars. They do not mark production,
visual review or human acceptance complete. Unknown calls stay pending.

`Stop` asks for continuation at most once per host generation (or once per
registration when the host supplies no generation identity). Pending/unknown
calls allow an honest recovery handoff; the hook never requires resubmission.

## Free desktop carrier handshake

`activate` generates a registration-specific `probe_nonce`. For a new desktop
chat whose real host session ID is not yet known, use explicit discovery:

```sh
python3 "$SKILL/scripts/workbuddy_board_guard.py" activate \
  --project "$PROJECT" --workspace "$PRODUCTION_WORKSPACE" \
  --discover-session \
  --scope "$PROJECT/.workbuddy/board-guard-scope.json" \
  --hooks-output "$PROJECT/.workbuddy/board-guard-proposed-settings.json"
```

`--discover-session` and `--session-id` are mutually exclusive, and one is
required. Discovery writes `host_session_id: null` and
`session_binding: unbound-probe-only`; never invent a temporary host ID. The
registration is active for the project, so every ImageGen call there remains
blocked until binding. Unbound Stop permits ending the discovery step without
forcing production preparation. Install this scope using the explicit settings
path above, then obtain the exact probe command:

```sh
python3 "$SKILL/scripts/workbuddy_board_guard.py" probe-status \
  --scope "$PROJECT/.workbuddy/board-guard-scope.json"
```

Have the signed-in WorkBuddy desktop call its native **Bash** tool with the
returned `command` verbatim and the actual project as its cwd. Do not prepend
`cd`, wrap the command or append options. The registered PreToolUse hook checks
the exact command/nonce and project cwd, records the original host
`session_id`/`tool_use_id` beside the scope, then exits 2 to block that harmless
command. It does not require an already bound session. All other
Bash commands pass without logging. No provider or image service is involved.

Run `probe-status` again and compare its evidence against the actual native
tool call and blocking result. Its `host_session_id` is returned only when the
observed probe events identify one session. Bind that actual ID with the
`bind-session` command below; this changes `session_binding` to `bound` without
touching the still-empty production workspace. Only then prepare/map/claim the
agreed production pages. On a prepared production, session binding updates only
the operational session context and preserves all original pending calls.
The probe body should never execute: if it does, it records
`unexpected_execution` and returns failure even when a Pre event also exists.
All receipts live beside the scope and leave the production workspace empty.

This blocked probe demonstrates only the exact Bash Pre hook. It does not
establish PostToolUse, Stop or ImageGen interception; each needs its own actual
desktop event before those enforcement claims are made. Synthetic hook-input
tests and the installed-runtime class probe below are separate evidence.

## Changing chats and stages

An active registration belongs to an S7 task in one project. ImageGen in a new
chat under that same project is blocked with `guard_not_bound`, rather than
silently losing protection. Use the explicit session handoff command to resume
that task. Existing pending calls keep their original identity and may only be
reconciled; unclaimed pages may use the new operational session.

```sh
python3 "$SKILL/scripts/workbuddy_board_guard.py" bind-session \
  --scope "$PROJECT/.workbuddy/board-guard-scope.json" \
  --session-id "$ACTUAL_NEW_WORKBUDDY_SESSION_ID"
```

For unrelated concept work in the **same** project, explicitly leave/deactivate
the active S7 registration first. A chat in another project is unaffected.
Leaving S7 does not remove its assets, claims or recovery evidence:

```sh
python3 "$SKILL/scripts/workbuddy_board_guard.py" deactivate \
  --scope "$PROJECT/.workbuddy/board-guard-scope.json"
```

No activation is inferred from prompt words or `FOCUS.md`. Existing projects can
have several cases/stages and historical plans. The structured `boards workbuddy
start` operation below compiles the actual registry and installs its task scope;
prose alone does not activate a guard.

## Normal S7 entry

Use the installed package's CLI and the actual WorkBuddy workspace. Record each
asset once in the [registry](../../../references/board-registry.md), then:

```sh
python3 "$SKILL/scripts/greybox.py" boards workbuddy start --file "$REGISTRY" --project "$PROJECT" --workspace "$PRODUCTION" --max-calls "$CALL_CEILING" --max-credits "$CREDIT_CEILING" --quote-upper-credits "$CURRENT_QUOTE_UPPER" --limit-source-ref "$ACTUAL_SCOPE_SOURCE"
```

Start derives the page tasks and merges this scope's hooks into the selected
WorkBuddy settings, preserving other settings/hooks. It returns the exact
harmless native Bash probe. Allow settings to reload, run that command unchanged
as one native Bash call, then inspect `boards workbuddy probe-status`. Expected
Pre exit 2 proves only that probe. If the command body ran before hooks loaded,
retain the failure, `boards workbuddy renew-probe`, and run the new command after
reload; never delete its earlier evidence.

Capture the new session's actual ImageGen schema and save its native binding:

```sh
python3 "$SKILL/scripts/greybox.py" boards workbuddy bind --workspace "$PRODUCTION" --binding "$LIVE_BINDING"
python3 "$SKILL/scripts/greybox.py" boards workbuddy next --workspace "$PRODUCTION"
python3 "$SKILL/scripts/greybox.py" boards workbuddy claim --workspace "$PRODUCTION" --page "$PAGE"
```

Bind uses the current original probe's session ID and maps all unclaimed pages.
Claim emits `call-ready.json` and `actual-arguments.json`; invoke those arguments
once, with exactly one existing DeferExecuteTool envelope. Existing pending calls
are recovered, never submitted again. A repeated start renews only the free probe.
Call ceilings count pending/recorded claims conservatively; the native Pre guard
also checks this entry's frozen ceiling, including lower-level claims. Credit
reservation uses the current quoted upper cost, not a promise about a provider's
eventual billing. No configured ceiling creates paid-call authority.

Record the actual result and process crops/reviews through `boards production`.
When several views cannot fit together without losing required detail, the
registry compiler prepares the source view and independent assets first and
keeps the original remaining views deferred. After the source crop is technically
qualified and has a real bound visual pass, run `boards advance --workspace
"$PRODUCTION"`. It derives the child registry with that actual master and its
strict crop receipt; do not rewrite the remaining asset list by hand.

Enter the returned child with `boards workbuddy resume --workspace "$CHILD"`,
then run its fresh probe and bind the current schema. Resume inherits the
original workflow's call/credit ceiling and counts claims across every stage.
It switches only this workflow's active hooks; pending original calls must be
reconciled before a stage switch. After the images and local crop reviews are
ready, `boards compare --workspace "$PRODUCTION" --file "$OBSERVATIONS"` binds
the source master and all target views. Stage completion is not full completion.

Finish or stop with `boards workbuddy cleanup --workspace "$PRODUCTION"`; only
this entry's hooks are removed and its calls/assets remain. For a regression
alongside active production, select a separate actual WorkBuddy project directory;
an S7 scope intentionally covers other sessions in the same project.

## Carrier evidence

WorkBuddy 5.9.2's bundled CLI 2.165.0 contains settings/plugin/scoped hook loading,
`ToolHookManager`, command execution and actual `tool_use_id` propagation.
An isolated bundled CLI startup has executed a `SessionStart` command hook;
its unauthenticated text-tool attempt executed `Stop` but could not reach a
model/Bash call. The included runtime probe exercises the installed bundle's
actual `HookManager` and `HookExecutor` with isolated dependency inputs and
temporary scripts. It proves command-runner exit-2 handling, not desktop chat
registration or ImageGen interception.

The inspected desktop package ships only the `lite-wb` entry; its regular
`bin/codebuddy` wrapper cannot find the full interactive bundle. The isolated
CLI's authentication failure does not indicate that WorkBuddy desktop is logged
out. An error string mentioning `/login` does not prove that this embedded
entry can perform login. Desktop verification must use the already signed-in
WorkBuddy session; do not route it through a different CLI carrier or copy
desktop credentials into a diagnostic process.

```sh
node "$SKILL/connectors/workbuddy/board-guard/probe-runtime.mjs" \
  --bundle "$ACTUAL_WORKBUDDY_BUNDLE" --python "$PYTHON" \
  --output "$TASK_EVIDENCE/hook-runner.json"
```

The probe does not start a model, call a tool/provider, install settings or copy
the bundle. It loads the installed bundle in memory, bypasses its CLI entry and
exposes the two actual classes for this test. Its version-specific anchors fail
explicitly when the installed build differs. Full desktop enforcement remains
unverified until a real session's harmless Pre/Post/Stop events are observed.
