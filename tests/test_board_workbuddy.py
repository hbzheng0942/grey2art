"""Offline real-module WorkBuddy entry tests; never touch user settings/tools."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art/runtime"))
from greybox import board_production, board_registry, board_workbuddy as entry, core, workbuddy_board_guard as guard
try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "Optional Pillow missing")
class WorkBuddyEntry(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        self.workspace = self.project / "run" / "production"
        self.settings = self.project / "fake-settings.json"
        self.original = {"sentinel": "user setting", "skillOverrides": {"existing": True},
                         "hooks": {"PreToolUse": [{"matcher": "Read", "hooks": [{"type": "command", "command": "original-read-hook"}]}]}}
        core.write(self.settings, self.original)
        Image.new("RGB", (32, 32), "blue").save(self.project / "style.png")
        self.registry = self.project / "registry.json"
        core.write(self.registry, {"schema": 1, "kind": "reference-board-registry", "authority": "registry",
            "source_ref": "Offline test input; no spending approval", "channel_size": [768, 768],
            "size_source_ref": "Offline synthetic image size",
            "requirements": {"min_subject_long_edge_px": 128, "min_subject_short_edge_px": 128,
                             "source_ref": "Offline test detail policy"},
            "images": [{"path": "style.png", "sha256": core.file_hash(self.project / "style.png")}],
            "image_roles": [{"role": "style"}],
            "capabilities": {"edit": True, "max_references": 2, "layout_guide": True, "source_ref": "Offline tool fixture"},
            "assets": [{"asset_id": "prop-" + str(i), "category": "prop", "function": "A rigid display object.",
                        "appearance": "A solid blue rounded object with a shallow authored mark.",
                        "structure": "One closed solid with an integral flat support.",
                        "modeling_contract": {"category": "prop", "use": "static"},
                        "views": [{"view_id": "three_quarter", "role": "three_quarter", "projected_aspect": 1.0}]}
                       for i in range(5)]})
        self.binding = self.project / "binding.json"
        core.write(self.binding, {"schema": 1, "kind": "reference-board-native-binding", "host": "workbuddy",
            "tool": "DeferExecuteTool", "source_ref": "Offline current tool-schema evidence",
            "input_transport": "local_paths", "max_references": 2, "prompt_argument": "prompt",
            "image_arguments": ["image1", "image2"], "arguments_container": "params",
            "envelope_arguments": {"toolName": "ImageGen"}})

    def start(self, **kwargs):
        return entry.start(self.registry, self.project, self.workspace, settings=self.settings, **kwargs)

    def probe_bind(self, workspace=None):
        workspace = workspace or self.workspace
        scope = entry._paths(workspace)[2]
        probe = guard.probe_status(scope)
        event = {"hook_event_name": "PreToolUse", "cwd": str(self.project), "session_id": "offline-host-session",
                 "tool_name": "Bash", "tool_use_id": "offline-probe-1", "tool_input": {"command": probe["command"]}}
        self.assertEqual(guard.handle(scope, event)[1], 2)
        return entry.bind(workspace, self.binding)

    def stage_master(self, max_calls=1, only_master=False):
        value = core.read(self.registry)
        value["requirements"]["min_subject_long_edge_px"] = 300
        value["assets"][0]["views"] = [{"view_id": role, "role": role, "projected_aspect": 1.0}
                                         for role in ("front", "left", "back")]
        if only_master:
            value["assets"] = value["assets"][:1]
        core.write(self.registry, value)
        self.start(max_calls=max_calls, max_credits=max_calls * 10, quote_upper_credits=10)
        self.probe_bind()
        info = entry.claim(self.workspace, "board-001")
        image = self.project / "offline-master.png"
        with Image.new("RGB", (768, 768), "white") as board:
            board.paste("purple", (184, 184, 584, 584))
            board.save(image)
        outer = {"hook_event_name": "PreToolUse", "cwd": str(self.project), "session_id": "offline-host-session",
                 "tool_name": info["tool"], "tool_use_id": "offline-master-call", "call_id": "offline-master-call",
                 "generation_id": "offline-generation", "tool_input": info["tool_arguments"]}
        inner = dict(outer, tool_name="ImageGen", tool_input=info["tool_arguments"]["params"])
        scope = entry._paths(self.workspace)[2]
        guard.handle(scope, outer)
        guard.handle(scope, inner)
        result = {"type": "image_gen_tool_result", "status": "completed", "images": [{"localPath": str(image)}]}
        guard.handle(scope, dict(inner, hook_event_name="PostToolUse", tool_response=result))
        guard.handle(scope, dict(outer, hook_event_name="PostToolUse", tool_response=result))
        board_production.record(self.workspace, "board-001", info["tool_arguments"], image,
                                source_ref="offline-master-call", tool_result=result)
        board_production.crop(self.workspace, "board-001", [{"asset_id": "prop-0", "view_id": "front",
                                "role": "front", "roi": [160, 160, 608, 608]}])
        page = core.read(self.workspace / "pages/board-001/state.json")
        receipt = core.read(self.project / next(iter(page["crops"].values()))["path"])
        board_production.review(self.workspace, "board-001", {"reviews": [{"asset_id": "prop-0", "view_id": "front",
            "role": "front", "image": receipt["output"], "verdict": "pass",
            "observation": "Offline solid color test silhouette; no real artistic acceptance.",
            "inspection_source_ref": "Offline pixel fixture inspection"}]})
        return board_registry.advance(self.workspace)

    def test_start_compiles_all_pages_and_installs_only_its_scoped_hooks(self):
        result = self.start()
        self.assertEqual([len(j["slots"]) for j in result["production"]["jobs"]], [4, 1])
        self.assertFalse(result["carrier_probe"]["probe_passed"])
        settings = core.read(self.settings)
        self.assertEqual(settings["skillOverrides"], self.original["skillOverrides"])
        self.assertIn(self.original["hooks"]["PreToolUse"][0], settings["hooks"]["PreToolUse"])
        with self.assertRaisesRegex(ValueError, "probe"):
            entry.claim(self.workspace, "board-001")
        self.assertFalse(any(self.workspace.glob("pages/*/claim.json")))

    def test_live_shaped_probe_binds_all_pages_and_emits_one_exact_envelope(self):
        self.start(max_calls=1, max_credits=10, quote_upper_credits=10, limit_source_ref="Offline ceiling only")
        bound = self.probe_bind()
        self.assertTrue(all(j["mapped"] for j in bound["jobs"]))
        result = entry.claim(self.workspace, "board-001")
        arguments = core.read(Path(result["arguments_path"]))
        self.assertEqual(arguments, result["tool_arguments"])
        self.assertEqual(set(arguments), {"toolName", "params"})
        self.assertEqual(arguments["toolName"], "ImageGen")
        self.assertEqual(core.read(Path(result["call_ready_path"]))["tool_arguments"], arguments)
        self.assertEqual(result["reserved_credit_upper"], 10)
        with self.assertRaisesRegex(ValueError, "ceiling"):
            entry.claim(self.workspace, "board-002")
        self.assertFalse((self.workspace / "pages/board-002/claim.json").exists())
        next_page = entry.next_job(self.workspace)["jobs"][0]
        self.assertEqual(next_page["claim_status"], "pending")
        self.assertIn("original pending", next_page["next_action"])

    def test_default_zero_limit_does_not_grant_a_native_claim(self):
        self.start()
        self.probe_bind()
        with self.assertRaisesRegex(ValueError, "ceiling"):
            entry.claim(self.workspace, "board-001")

    def test_missing_hooks_after_probe_blocks_claim(self):
        self.start(max_calls=3, max_credits=30, quote_upper_credits=10)
        self.probe_bind()
        core.write(self.settings, self.original)
        with self.assertRaisesRegex(ValueError, "no longer installed"):
            entry.claim(self.workspace, "board-001")

    def test_cleanup_preserves_other_settings_and_pending_claim(self):
        self.start(max_calls=3, max_credits=30, quote_upper_credits=10)
        self.probe_bind()
        info = entry.claim(self.workspace, "board-001")
        original_claim = Path(info["claim_file"]["path"]).read_bytes()
        self.assertFalse(entry.cleanup(self.workspace)["active"])
        self.assertEqual(core.read(self.settings), self.original)
        self.assertEqual(Path(info["claim_file"]["path"]).read_bytes(), original_claim)
        with self.assertRaisesRegex(ValueError, "inactive"):
            entry.claim(self.workspace, "board-002")

    def test_invalid_registry_does_not_install_hooks(self):
        value = core.read(self.registry)
        value["assets"][0]["views"] *= 2
        core.write(self.registry, value)
        with self.assertRaises(ValueError):
            self.start()
        self.assertEqual(core.read(self.settings), self.original)

    def test_limits_cannot_silently_change_on_resume(self):
        self.start(max_calls=1, max_credits=10, quote_upper_credits=10)
        with self.assertRaisesRegex(ValueError, "Existing board entry changed"):
            self.start(max_calls=3, max_credits=30, quote_upper_credits=10)

    def test_nonfinite_limits_rejected_before_preparation(self):
        with self.assertRaises(ValueError):
            self.start(max_calls=2, max_credits=float("inf"), quote_upper_credits=10)
        self.assertFalse(self.workspace.exists())

    def test_concurrent_pages_cannot_exceed_one_call_ceiling(self):
        self.start(max_calls=1, max_credits=10, quote_upper_credits=10)
        self.probe_bind()
        barrier = threading.Barrier(2)
        results = []
        def invoke(page):
            barrier.wait(timeout=10)
            try:
                results.append(entry.claim(self.workspace, page))
            except ValueError as error:
                results.append({"error": str(error)})
        threads = [threading.Thread(target=invoke, args=(page,)) for page in ("board-001", "board-002")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(list(self.workspace.glob("pages/*/claim.json"))), 1)
        self.assertEqual(sum("tool_arguments" in result for result in results), 1)

    def test_start_on_resume_requires_a_new_native_probe_without_clearing_claims(self):
        options = dict(max_calls=2, max_credits=20, quote_upper_credits=10)
        self.start(**options)
        self.probe_bind()
        info = entry.claim(self.workspace, "board-001")
        original = Path(info["claim_file"]["path"]).read_bytes()
        repeated = self.start(**options)
        self.assertFalse(repeated["carrier_probe"]["probe_passed"])
        self.assertEqual(Path(info["claim_file"]["path"]).read_bytes(), original)
        with self.assertRaisesRegex(ValueError, "probe"):
            entry.claim(self.workspace, "board-002")

    def test_lower_level_claim_cannot_bypass_guard_side_zero_ceiling(self):
        self.start()
        self.probe_bind()
        info = board_production.claim(self.workspace, "board-001")
        event = {"hook_event_name": "PreToolUse", "cwd": str(self.project),
                 "session_id": "offline-host-session", "tool_name": info["tool"],
                 "tool_use_id": "offline-forbidden-native-call", "tool_input": info["tool_arguments"]}
        with self.assertRaisesRegex(ValueError, "ceiling"):
            guard.handle(entry._paths(self.workspace)[2], event)
        self.assertFalse((self.workspace / "host-guard/claims").exists())

    def test_changed_ceiling_file_is_rejected_at_native_hook(self):
        self.start(max_calls=1, max_credits=10, quote_upper_credits=10)
        self.probe_bind()
        info = entry.claim(self.workspace, "board-001")
        path = entry._paths(self.workspace)[3]
        changed = core.read(path)
        changed["limit"]["max_calls"] = 50
        core.write(path, changed)
        event = {"hook_event_name": "PreToolUse", "cwd": str(self.project),
                 "session_id": "offline-host-session", "tool_name": info["tool"],
                 "tool_use_id": "offline-mutated-ceiling-call", "tool_input": info["tool_arguments"]}
        with self.assertRaisesRegex(ValueError, "ceiling changed"):
            guard.handle(entry._paths(self.workspace)[2], event)

    def test_dependent_stage_inherits_original_total_ceiling_and_switches_scope(self):
        advanced = self.stage_master()
        child = Path(advanced["created_workspace"])
        self.assertFalse(entry.next_job(self.workspace)["complete"])
        resumed = entry.resume(child)
        self.assertEqual(resumed["workflow_root"], str(self.workspace))
        self.assertFalse(core.read(entry._paths(self.workspace)[2])["active"])
        self.assertTrue(core.read(entry._paths(child)[2])["active"])
        self.probe_bind(child)
        self.assertEqual(entry.next_job(child)["reserved_calls"], 1)
        with self.assertRaisesRegex(ValueError, "ceiling"):
            entry.claim(child, "board-001")
        self.assertFalse(any(child.glob("pages/*/claim.json")))
        low = board_production.claim(child, "board-001")
        event = {"hook_event_name": "PreToolUse", "cwd": str(self.project), "session_id": "offline-host-session",
                 "tool_name": low["tool"], "tool_use_id": "offline-child-over-ceiling", "tool_input": low["tool_arguments"]}
        with self.assertRaisesRegex(ValueError, "ceiling"):
            guard.handle(entry._paths(child)[2], event)

    def test_dependent_native_page_is_allowed_with_remaining_original_ceiling(self):
        advanced = self.stage_master(max_calls=3)
        child = Path(advanced["created_workspace"])
        entry.resume(child)
        self.probe_bind(child)
        info = entry.claim(child, "board-001")
        self.assertEqual(info["reserved_calls"], 2)
        self.assertEqual(info["reserved_credit_upper"], 20)
        outer = {"hook_event_name": "PreToolUse", "cwd": str(self.project), "session_id": "offline-host-session",
                 "tool_name": info["tool"], "tool_use_id": "offline-child-native", "call_id": "offline-child-native",
                 "generation_id": "offline-child-generation", "tool_input": info["tool_arguments"]}
        inner = dict(outer, tool_name="ImageGen", tool_input=info["tool_arguments"]["params"])
        scope = entry._paths(child)[2]
        self.assertEqual(guard.handle(scope, outer)[1], 0)
        result, code = guard.handle(scope, inner)
        self.assertEqual(code, 0)
        self.assertTrue(result["execution_authorized"])

    def test_unknown_original_call_prevents_stage_switch(self):
        advanced = self.stage_master()
        child = Path(advanced["created_workspace"])
        # A lower-level pending original claim still has to be recovered even
        # when it has not reached the native tool or reserved provider credit.
        board_production.claim(self.workspace, "board-002")
        with self.assertRaisesRegex(ValueError, "pending calls"):
            entry.resume(child)
        self.assertTrue(core.read(entry._paths(self.workspace)[2])["active"])
        self.assertFalse(entry._paths(child)[2].exists())

    def test_stage_activation_and_hook_install_share_the_original_root_lock(self):
        advanced = self.stage_master()
        child = Path(advanced["created_workspace"])
        entered, release = threading.Event(), threading.Event()
        real_install = guard.install
        results = []
        def delayed_install(*args):
            entered.set()
            self.assertTrue(release.wait(timeout=20))
            return real_install(*args)
        def parent_resume():
            try:
                results.append(entry.resume(self.workspace))
            except Exception as error:
                results.append(error)
        with patch.object(guard, "install", side_effect=delayed_install):
            worker = threading.Thread(target=parent_resume)
            worker.start()
            self.assertTrue(entered.wait(timeout=20))
            try:
                with self.assertRaisesRegex(ValueError, "live process"):
                    entry.resume(child)
            finally:
                release.set()
                worker.join(timeout=20)
            self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], dict)
        self.assertTrue(core.read(entry._paths(self.workspace)[2])["active"])
        self.assertFalse(entry._paths(child)[2].exists())

    def test_stop_does_not_confuse_complete_master_stage_with_full_multiview_scope(self):
        self.stage_master(only_master=True)
        self.assertTrue(board_production.status(self.workspace)["complete"])
        self.assertFalse(board_registry.next_jobs(self.workspace)["complete"])
        scope = entry._paths(self.workspace)[2]
        event = {"hook_event_name": "Stop", "cwd": str(self.project), "session_id": "offline-host-session",
                 "generation_id": "offline-master-stage-stop"}
        result, code = guard.handle(scope, event)
        self.assertEqual(code, 2)
        self.assertNotEqual(result.get("action"), "allow_completed_scope")


if __name__ == "__main__":
    unittest.main()
