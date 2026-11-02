#!/usr/bin/env node
// Optional installed-runtime probe. No model, provider, settings mutation or
// installed source changes; input events/dependencies are explicit fixtures.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";

function option(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error("Required option: " + name);
  return process.argv[index + 1];
}

let scratch;
try {
  const bundle = path.resolve(option("--bundle"));
  const python = option("--python");
  const output = path.resolve(option("--output"));
  if (fs.existsSync(output)) throw new Error("Output already exists; choose a new explicit path");
  const original = fs.readFileSync(bundle);
  const bundleURL = JSON.stringify(pathToFileURL(bundle).href);
  let source = original.toString("utf8");
  const anchor = "kw=hook_manager_decorate([(0,po.Component)(gh.bl)],kw);";
  const entry = "__webpack_require__(__webpack_require__.s=75374);";
  if (!source.includes(anchor) || !source.trimEnd().endsWith(entry)) {
    throw new Error("Unsupported installed bundle: known runtime-probe anchors differ");
  }
  // Expose real constructors without executing the CLI/model entry. Preserve
  // lazy chunk resolution against the original installed bundle location.
  source = source.replace(anchor, anchor + "globalThis.__WBBoardProbe={HookManager:kw,HookExecutor:kh};")
    .replace(entry, "globalThis.__WBBoardProbeRequire=__webpack_require__;")
    .replaceAll('import("./"+__webpack_require__.u(i))',
      'import(new URL("./"+__webpack_require__.u(i),' + bundleURL + ').href)')
    .replaceAll("import.meta.url", bundleURL);
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), "workbuddy-board-hook-runner-"));
  process.env.CODEBUDDY_CONFIG_DIR = path.join(scratch, "codebuddy-config");
  process.env.WORKBUDDY_CONFIG_DIR = path.join(scratch, "workbuddy-config");
  await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
  globalThis.__WBBoardProbeRequire(67602);
  const { HookManager, HookExecutor } = globalThis.__WBBoardProbe;
  const manager = new HookManager(), executor = new HookExecutor();
  const logger = { info() {}, warn() {}, error() {}, debug() {}, log() {} };
  executor.logger = logger;
  executor.debugService = logger;
  Object.assign(manager, {
    logger, debugService: logger, hookExecutor: executor,
    hookInputProcessorProvider: { sortSync: () => [] },
    hookProvider: { sortSync: () => [] },
    pluginManager: { getActivePlugins: async () => [] },
    scopedHookRegistry: { getHooks: () => [] },
    sdkHooksManager: { getHooks: () => [] },
    endpointProvider: { get: async () => "http://127.0.0.1:1" },
    runtimeSecurityHookLoader: { getHooks: async () => [] },
  });
  const events = path.join(scratch, "events.jsonl");
  const hook = path.join(scratch, "observe.py");
  fs.writeFileSync(hook,
    "import json,sys,pathlib\nx=json.load(sys.stdin)\n" +
    "with pathlib.Path(" + JSON.stringify(events) + ").open('a') as f:f.write(json.dumps(x)+'\\n')\n" +
    "if x.get('hook_event_name') in ['PreToolUse','Stop']:\n" +
    " print(json.dumps({'reason':'Isolated runtime probe blocked this event'}));sys.exit(2)\n");
  const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
  const command = quote(python) + " " + quote(hook);
  manager.settingsManager = { get: async name => name === "hooks" ? {
    PreToolUse: [{ matcher: "^Bash$", hooks: [{ type: "command", command, timeout: 5 }] }],
    PostToolUse: [{ matcher: "^Bash$", hooks: [{ type: "command", command, timeout: 5 }] }],
    Stop: [{ hooks: [{ type: "command", command, timeout: 5 }] }],
  } : undefined };
  const base = { session_id: "isolated-runtime-fixture", cwd: scratch,
    tool_use_id: "fixture-call-id", tool_name: "Bash", tool_input: { command: "true" } };
  const pre = await manager.executeHooks("PreToolUse", { ...base, hook_event_name: "PreToolUse" });
  const post = await manager.executeHooks("PostToolUse", { ...base, hook_event_name: "PostToolUse",
    tool_response: { synthetic_fixture: true } });
  const stop = await manager.executeHooks("Stop", { session_id: base.session_id,
    cwd: scratch, hook_event_name: "Stop", stop_hook_active: false });
  const observed = fs.existsSync(events) ? fs.readFileSync(events, "utf8").trim().split("\n").map(JSON.parse) : [];
  const report = {
    schema: 1, kind: "workbuddy-installed-hook-runner-probe",
    bundle_sha256: crypto.createHash("sha256").update(original).digest("hex"),
    pre_exit2_blocked: pre.allowed === false && pre.blocking === true,
    post_command_hook_ran: post.allowed === true && observed.some(x => x.hook_event_name === "PostToolUse"),
    stop_exit2_blocked: stop.allowed === false && stop.blocking === true,
    observed_event_names: observed.map(x => x.hook_event_name),
    original_tool_id_preserved: observed.filter(x => x.tool_name).every(x => x.tool_use_id === base.tool_use_id),
    model_requested: false, native_tool_invoked: false, desktop_chat_enforcement_verified: false,
    boundary: "Actual installed HookManager/HookExecutor with isolated fixture dependencies; in-memory entry instrumentation. No desktop session, ImageGen or model/tool-call certification.",
  };
  report.ok = report.pre_exit2_blocked && report.post_command_hook_ran && report.stop_exit2_blocked;
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
  console.log(JSON.stringify(report));
  process.exitCode = report.ok ? 0 : 2;
} catch (error) {
  console.log(JSON.stringify({ ok: false, error: String(error.message).replace(/data:text[^ ]+/g, "[instrumented-module]").slice(0, 400),
    desktop_chat_enforcement_verified: false }));
  process.exitCode = 2;
} finally {
  if (scratch) fs.rmSync(scratch, { recursive: true, force: true });
}
