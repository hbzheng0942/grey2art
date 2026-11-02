"""Scoped host-hook contracts; real board module, offline synthetic images."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art/runtime"))
from greybox import board_production, core, workbuddy_board_guard as guard
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "Pixel-backed board preparation requires Pillow")
class WorkBuddyBoardGuard(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name).resolve()
        self.workspace = self.project / "art/production"
        self.scope = self.project / "guard-scope.json"
        core.write(self.scope, {"schema": 1, "kind": "workbuddy-board-guard-scope", "active": True,
                               "stage": "S7", "project": str(self.project), "workspace": str(self.workspace),
                               "host_session_id": "guard-fixture-session"})
        self.event = {"hook_event_name": "PreToolUse", "session_id": "guard-fixture-session",
                      "cwd": str(self.project), "tool_name": "DeferExecuteTool", "tool_use_id": "fixture-call-1",
                      "tool_input": {"toolName": "ImageGen", "params": {"prompt": "unprepared"}}}

    def prepare(self, tool="DeferExecuteTool", parameters=None):
        Image.new("RGB", (256, 256), "blue").save(self.project / "style.png")
        views = [{"asset_id": "fixture-prop", "view_id": "three_quarter", "role": "three_quarter",
                  "projected_aspect": 1., "min_subject_long_edge_px": 128, "min_subject_short_edge_px": 128}]
        core.write(self.project / "upstream.json", {"schema": 1, "kind": "reference-board-scope", "asset_views": views})
        core.write(self.project / "prepare.json", {
            "schema": 1, "kind": "reference-board-prepare-input", "purpose": "modeling",
            "plan": {"schema": 1, "kind": "reference-board-plan-input", "channel_size": [768, 768],
                     "size_source_ref": "offline fixture dimensions", "views": views},
            "images": [{"path": "style.png", "sha256": core.file_hash(self.project / "style.png")}],
            "image_roles": [{"role": "style"}],
            "objects": [{"asset_id": "fixture-prop", "view_id": "three_quarter", "role": "three_quarter",
                         "category": "prop", "function": "A rigid independent museum exhibit.",
                         "appearance": "A rounded purple vessel with a readable opening and ivory rim.",
                         "structure": "One closed solid volume with an integral flat support surface.",
                         "modeling_contract": {"category": "prop", "use": "rigid_motion"}}],
            "capabilities": {"edit": True, "max_references": 2, "layout_guide": True,
                             "source_ref": "offline fixture capability declaration"}, "parameters": parameters or {}})
        binding = {"schema": 1, "kind": "reference-board-native-binding", "host": "workbuddy", "tool": tool,
                   "source_ref": "fixture-original-schema-call", "input_transport": "local_paths", "max_references": 2,
                   "prompt_argument": "prompt", "image_arguments": ["image1", "image2"]}
        if tool == "DeferExecuteTool":
            binding.update(arguments_container="params", envelope_arguments={"toolName": "ImageGen"})
        if parameters:
            binding["parameter_arguments"] = {key: key for key in parameters}
        core.write(self.project / "binding.json", binding)
        ref = lambda name: {"path": name, "sha256": core.file_hash(self.project / name)}
        request = {"schema": 1, "kind": "reference-board-production-input", "host_session_id": "guard-fixture-session",
                   "scope": {"source_ref": "fixture source decision", "source": ref("upstream.json"), "asset_views": views},
                   "prepare_spec": ref("prepare.json"), "native_binding": ref("binding.json")}
        core.write(self.project / "request.json", request)
        board_production.prepare(request, self.project, self.workspace, request_path="request.json")
        board_production.map_native(self.workspace, "board-001", self.project / "binding.json")
        info = board_production.inspect_claim(self.workspace, "board-001")
        self.event.update(tool_name=tool, tool_input=info["tool_arguments"])
        return info

    def claim(self):
        board_production.claim(self.workspace, "board-001")

    def nested_events(self):
        self.prepare(parameters={"size": "768x768", "quality": "high"})
        self.claim()
        # The field shape matches native WorkBuddy 5.9.2 events, with synthetic
        # IDs/paths/parameters. This test does not impersonate live host proof.
        outer = dict(copy.deepcopy(self.event), call_id=self.event["tool_use_id"], agent_type="cli",
                     client="WorkBuddy", version="5.9.2", permission_mode="default",
                     generation_id="offline-native-shaped-generation", model="offline-fixture-model",
                     transcript_path=str(self.project / "offline-not-a-real-session.jsonl"))
        inner = dict(copy.deepcopy(outer), tool_name="ImageGen", tool_input=copy.deepcopy(outer["tool_input"]["params"]))
        return outer, inner

    def synthetic_result(self):
        image = self.project / "offline-output.png"
        Image.new("RGB", (768, 768), "purple").save(image)
        return image, {"type": "image_gen_tool_result", "status": "completed", "images": [{"localPath": str(image)}]}

    def test_native_deferred_pre_post_layers_then_record_one_synthetic_png(self):
        outer, inner = self.nested_events()
        info = board_production.inspect_claim(self.workspace, "board-001")
        claim_bytes = Path(info["claim_file"]["path"]).read_bytes()
        outer_result, code = guard.handle(self.scope, outer)
        self.assertEqual(code, 0)
        self.assertFalse(outer_result["execution_authorized"])
        outer_path = guard._claim_path(self.workspace, info)
        outer_bytes = outer_path.read_bytes()
        result, code = guard.handle(self.scope, inner)
        self.assertEqual(code, 0)
        self.assertTrue(result["execution_authorized"])
        execution_path = guard._execution_claim_path(self.workspace, info["claim"]["id"])
        execution = core.read(execution_path)
        self.assertEqual(execution["event"], inner)
        self.assertEqual(execution["outer_pre_sha256"], core.file_hash(outer_path))
        image, raw = self.synthetic_result()
        # Native hook rawResponse carries credit metadata, while the visible
        # tool result's JSON content may omit it. Retain both original forms.
        native_raw = dict(raw, credit=3)
        inner_post = dict(inner, hook_event_name="PostToolUse", tool_response=native_raw)
        outer_post = dict(outer, hook_event_name="PostToolUse", tool_response=native_raw)
        inner_receipt = guard.handle(self.scope, inner_post)[0]
        outer_receipt = guard.handle(self.scope, outer_post)[0]
        self.assertNotEqual(inner_receipt["evidence"], outer_receipt["evidence"])
        self.assertEqual(core.read(inner_receipt["evidence"])["event"], inner_post)
        self.assertEqual(core.read(outer_receipt["evidence"])["event"], outer_post)
        self.assertEqual(outer_path.read_bytes(), outer_bytes)
        self.assertEqual(Path(info["claim_file"]["path"]).read_bytes(), claim_bytes)
        recorded = board_production.record(self.workspace, "board-001", outer["tool_input"], image,
                                           source_ref=outer["tool_use_id"],
                                           tool_result={"content": [{"type": "text", "text": json.dumps(raw)}]})
        self.assertTrue(recorded["invocation_recorded"])
        self.assertFalse(recorded["human_acceptance"])
        self.assertFalse(recorded["host_trace_verified"])
        resumed = board_production.status(self.workspace)
        self.assertFalse(resumed["complete"])
        self.assertTrue(resumed["pages"][0]["invocation_recorded"])
        self.assertFalse(resumed["pages"][0]["human_acceptance"])

    def test_deferred_inner_requires_outer_and_both_layers_refuse_pre_replays(self):
        outer, inner = self.nested_events()
        with self.assertRaises(ValueError):
            guard.handle(self.scope, inner)
        guard.handle(self.scope, outer)
        guard.handle(self.scope, inner)
        with self.assertRaisesRegex(ValueError, "already reached"):
            guard.handle(self.scope, outer)
        with self.assertRaisesRegex(ValueError, "already authorized"):
            guard.handle(self.scope, inner)
        other = dict(inner, call_id="other-original-call", tool_use_id="other-original-call")
        with self.assertRaises(ValueError):
            guard.handle(self.scope, other)

    def test_deferred_same_call_rejects_all_changed_flat_params_without_consuming_inner(self):
        outer, inner = self.nested_events()
        guard.handle(self.scope, outer)
        for field in ("prompt", "image1", "image2", "size", "quality", "extra"):
            changed = copy.deepcopy(inner)
            changed["tool_input"][field] = "changed-value"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "complete frozen deferred params"):
                guard.handle(self.scope, changed)
        self.assertTrue(guard.handle(self.scope, inner)[0]["execution_authorized"])

    def test_deferred_inner_binds_original_project_session_generation_and_both_ids(self):
        outer, inner = self.nested_events()
        guard.handle(self.scope, outer)
        child = self.project / "different-native-cwd"
        child.mkdir()
        for changes in ({"cwd": str(child)}, {"session_id": "other-native-session"},
                        {"generation_id": "another-generation"}, {"call_id": "contradicting-call-id"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                guard.handle(self.scope, dict(inner, **changes))
        self.assertEqual(guard.handle(self.scope, inner)[1], 0)

    def test_ended_outer_failure_cannot_be_revived_by_same_call_inner(self):
        outer, inner = self.nested_events()
        guard.handle(self.scope, outer)
        failed = dict(outer, hook_event_name="PostToolUse",
                      tool_response='Error executing tool "ImageGen": blocked by the resolved Pre hook')
        receipt = guard.handle(self.scope, failed)[0]
        with self.assertRaisesRegex(ValueError, "call has ended"):
            guard.handle(self.scope, inner)
        self.assertEqual(core.read(receipt["evidence"])["event"], failed)
        self.assertEqual(board_production.inspect_claim(self.workspace, "board-001")["claim"]["status"], "pending")

    def test_deferred_posts_can_arrive_outer_first_without_overwriting_either_layer(self):
        outer, inner = self.nested_events()
        guard.handle(self.scope, outer)
        guard.handle(self.scope, inner)
        outer_post = dict(outer, hook_event_name="PostToolUse", tool_response="raw outer response")
        outer_path = Path(guard.handle(self.scope, outer_post)[0]["evidence"])
        original_outer = outer_path.read_bytes()
        inner_post = dict(inner, hook_event_name="PostToolUse", tool_response="raw inner response")
        inner_path = Path(guard.handle(self.scope, inner_post)[0]["evidence"])
        self.assertEqual(outer_path.read_bytes(), original_outer)
        self.assertNotEqual(inner_path, outer_path)
        self.assertEqual(guard.handle(self.scope, inner_post)[1], 0)
        with self.assertRaisesRegex(ValueError, "Original host result changed"):
            guard.handle(self.scope, dict(inner_post, tool_response="conflicting later response"))

    def test_completed_board_late_same_layer_post_conflicts_are_retained_and_block_status(self):
        outer, inner = self.nested_events()
        guard.handle(self.scope, outer)
        guard.handle(self.scope, inner)
        page = core.read(self.workspace / "pages/board-001/state.json")
        image = Image.new("RGB", (768, 768), "white")
        drawing = ImageDraw.Draw(image)
        observed = []
        for slot in page["slots"]:
            left, top, right, bottom = slot["planned_region"]
            x, y = left + (right - left - 145) // 2, top + (bottom - top - 145) // 2
            drawing.rectangle([x, y, x + 144, y + 144], fill="purple")
            observed.append({"asset_id": slot["asset_id"], "view_id": slot["view_id"], "role": slot["role"],
                             "roi": [left + 12, top + 12, right - 12, bottom - 12]})
        output = self.project / "late-conflict-synthetic-output.png"
        image.save(output)
        raw = {"type": "image_gen_tool_result", "status": "completed", "images": [{"localPath": str(output)}],
               "synthetic_business_flag": True}
        posts = {"inner": dict(inner, hook_event_name="PostToolUse", tool_response=raw),
                 "outer": dict(outer, hook_event_name="PostToolUse", tool_response=raw)}
        originals = {}
        for layer, event in posts.items():
            path = Path(guard.handle(self.scope, event)[0]["evidence"])
            originals[layer] = (path, path.read_bytes())
            self.assertEqual(guard.handle(self.scope, event)[1], 0)
        board_production.record(self.workspace, "board-001", outer["tool_input"], output,
                                source_ref=outer["tool_use_id"], tool_result=raw)
        board_production.crop(self.workspace, "board-001", observed)
        page = core.read(self.workspace / "pages/board-001/state.json")
        reviews = []
        for ref in page["crops"].values():
            receipt = core.read(self.project / ref["path"])
            recipe = receipt["recipe"]
            reviews.append({"asset_id": recipe["asset_id"], "view_id": recipe["view_id"], "role": recipe["role"],
                            "image": receipt["output"], "verdict": "pass",
                            "observation": "Offline constructed purple rectangle has complete white margins.",
                            "inspection_source_ref": "offline fixture pixel observation, not live host proof"})
        board_production.review(self.workspace, "board-001", reviews)
        self.assertTrue(board_production.status(self.workspace)["complete"])
        conflicts = self.workspace / "host-guard/conflicts"
        self.assertEqual(list(conflicts.glob("*.json")), [])
        incoming = {"inner": dict(posts["inner"], tool_response={"type": "image_gen_tool_result", "status": "failed",
                                                                   "images": [], "error": "late conflicting native error"}),
                    # Python dict equality treats True and 1 as equal. Strict
                    # canonical JSON must retain this contradiction too.
                    "outer": dict(posts["outer"], tool_response=dict(raw, synthetic_business_flag=1))}
        for layer, event in incoming.items():
            with self.assertRaisesRegex(ValueError, "Original host result changed"):
                guard.handle(self.scope, event)
            with self.assertRaisesRegex(ValueError, "[Cc]onflict"):
                board_production.status(self.workspace)
            for path, original in originals.values():
                self.assertEqual(path.read_bytes(), original)
        retained = [core.read(path) for path in conflicts.glob("*.json")]
        self.assertEqual({row["layer"] for row in retained}, {"inner", "outer"})
        self.assertEqual(len(retained), 2)
        for row in retained:
            path, _ = originals[row["layer"]]
            self.assertEqual(row["original_result"], {"path": str(path), "sha256": core.file_hash(path)})
            self.assertEqual(row["source_ref"], outer["tool_use_id"])
            self.assertEqual(row["page_id"], "board-001")
            original = core.read(path)
            self.assertEqual(row["original_pre_sha256"], original.get("execution_pre_sha256" if row["layer"] == "inner" else "pre_event_sha256"))
            self.assertTrue(guard._same_arguments(row["incoming_record"]["event"], incoming[row["layer"]]))
        with self.assertRaisesRegex(ValueError, "Original host result changed"):
            guard.handle(self.scope, incoming["outer"])
        self.assertEqual(len(list(conflicts.glob("*.json"))), 2)

    def test_deferred_inner_post_without_execution_pre_is_not_execution_evidence(self):
        outer, inner = self.nested_events()
        guard.handle(self.scope, outer)
        with self.assertRaises((ValueError, OSError)):
            guard.handle(self.scope, dict(inner, hook_event_name="PostToolUse", tool_response="unlinked"))
        self.assertFalse(guard._result_path(self.workspace, outer["tool_use_id"], execution=True).exists())
        self.assertFalse(guard._result_path(self.workspace, outer["tool_use_id"]).exists())

    def test_deferred_inner_rejects_changed_original_claim_and_dispatch(self):
        outer, inner = self.nested_events()
        guard.handle(self.scope, outer)
        info = board_production.inspect_claim(self.workspace, "board-001")
        for target in (info["claim_file"]["path"], info["dispatch"]["path"]):
            path = Path(target)
            original = path.read_bytes()
            changed = core.read(path)
            changed["id" if target == info["claim_file"]["path"] else "tool"] = "changed-original"
            core.write(path, changed)
            try:
                with self.assertRaises((ValueError, OSError)):
                    guard.handle(self.scope, inner)
            finally:
                path.write_bytes(original)
        self.assertTrue(guard.handle(self.scope, inner)[0]["execution_authorized"])

    def test_direct_imagegen_pre_post_record_does_not_need_deferred_execution_layer(self):
        self.prepare(tool="ImageGen")
        self.claim()
        result = guard.handle(self.scope, self.event)[0]
        self.assertTrue(result["execution_authorized"])
        image, raw = self.synthetic_result()
        guard.handle(self.scope, dict(self.event, hook_event_name="PostToolUse", tool_response=raw))
        recorded = board_production.record(self.workspace, "board-001", self.event["tool_input"], image,
                                           source_ref=self.event["tool_use_id"], tool_result=raw)
        self.assertTrue(recorded["invocation_recorded"])
        self.assertFalse((self.workspace / "host-guard/execution-claims").exists())

    def test_registered_but_unprepared_is_blocked(self):
        with self.assertRaises((ValueError, OSError)):
            guard.handle(self.scope, self.event)

    def test_other_session_project_tool_and_stage_are_outside_scope(self):
        for changes in ({"cwd": "/unrelated-project"},
                        {"tool_input": {"toolName": "UnrelatedTool"}}, {"tool_name": "Bash"}):
            result, code = guard.handle(self.scope, dict(self.event, **changes))
            self.assertEqual(code, 0)
            self.assertTrue(result["action"].startswith("outside_"))
        value = core.read(self.scope)
        value["stage"] = "concept"
        core.write(self.scope, value)
        self.assertEqual(guard.handle(self.scope, self.event)[1], 0)

    def test_same_project_new_session_requires_explicit_handoff(self):
        with self.assertRaisesRegex(ValueError, "guard_not_bound"):
            guard.handle(self.scope, dict(self.event, session_id="new-host-session"))
        self.assertEqual(guard.handle(self.scope, dict(self.event, hook_event_name="Stop",
                                                     session_id="unrelated-project-chat"))[1], 0)

    def test_prepared_without_claim_is_blocked(self):
        self.prepare()
        with self.assertRaises(ValueError):
            guard.handle(self.scope, self.event)

    def test_exact_claim_allowed_once_and_unknown_cannot_resend(self):
        self.prepare()
        self.claim()
        result, code = guard.handle(self.scope, self.event)
        self.assertEqual((code, result["source_ref"]), (0, "fixture-call-1"))
        self.assertEqual(board_production.inspect_claim(self.workspace, "board-001")["claim"]["status"], "pending")
        with self.assertRaisesRegex(ValueError, "already reached PreToolUse"):
            guard.handle(self.scope, dict(self.event, tool_use_id="new-call-is-forbidden"))

    def test_changed_prompt_and_missing_image_block_before_consumption(self):
        self.prepare()
        self.claim()
        for mutation in ("prompt", "image2"):
            value = copy.deepcopy(self.event)
            if mutation == "prompt":
                value["tool_input"]["params"]["prompt"] += " changed"
            else:
                del value["tool_input"]["params"]["image2"]
            with self.assertRaises(ValueError):
                guard.handle(self.scope, value)
        self.assertEqual(guard.handle(self.scope, self.event)[1], 0)

    def test_direct_imagegen_is_guarded_too(self):
        self.prepare(tool="ImageGen")
        self.claim()
        self.assertEqual(guard.handle(self.scope, self.event)[0]["action"], "allow_exact_claimed_call")

    def test_stale_input_and_wrong_production_session_are_blocked(self):
        self.prepare()
        self.claim()
        Image.new("RGB", (256, 256), "red").save(self.project / "style.png")
        with self.assertRaises(ValueError):
            guard.handle(self.scope, self.event)

    def test_missing_host_call_id_cannot_be_invented(self):
        self.prepare()
        self.claim()
        value = dict(self.event)
        del value["tool_use_id"]
        with self.assertRaisesRegex(ValueError, "original tool_use_id"):
            guard.handle(self.scope, value)

    def test_post_preserves_raw_evidence_and_does_not_record_acceptance(self):
        self.prepare()
        self.claim()
        guard.handle(self.scope, self.event)
        raw = {"type": "text", "text": "unknown original response; do not infer success"}
        post = dict(self.event, hook_event_name="PostToolUse", tool_response=raw)
        result, code = guard.handle(self.scope, post)
        self.assertEqual(code, 0)
        self.assertEqual(core.read(result["evidence"])["event"]["tool_response"], raw)
        self.assertEqual(board_production.inspect_claim(self.workspace, "board-001")["claim"]["status"], "pending")
        self.assertEqual(guard.handle(self.scope, post)[1], 0)
        with self.assertRaises(ValueError):
            guard.handle(self.scope, dict(post, tool_response={"changed": True}))

    def test_handoff_preserves_pending_claim_and_late_original_result(self):
        self.prepare()
        self.claim()
        guard.handle(self.scope, self.event)
        info = board_production.inspect_claim(self.workspace, "board-001")
        original = Path(info["claim_file"]["path"]).read_bytes()
        guard.bind_session(self.scope, "new-host-session")
        with self.assertRaises(ValueError):
            guard.handle(self.scope, dict(self.event, session_id="new-host-session", tool_use_id="forbidden-new-call"))
        self.assertEqual(Path(info["claim_file"]["path"]).read_bytes(), original)
        late = dict(self.event, hook_event_name="PostToolUse", tool_response={"original_late_result": True})
        self.assertEqual(guard.handle(self.scope, late)[1], 0)
        self.assertEqual(board_production.inspect_claim(self.workspace, "board-001")["claim"]["status"], "pending")

    def test_unclaimed_page_can_be_claimed_under_explicit_new_session(self):
        self.prepare()
        guard.bind_session(self.scope, "new-host-session")
        self.claim()
        self.assertEqual(guard.handle(self.scope, dict(self.event, session_id="new-host-session"))[1], 0)

    def test_stop_is_bounded_even_without_production_or_generation_id(self):
        stop = {"hook_event_name": "Stop", "session_id": self.event["session_id"], "cwd": self.event["cwd"]}
        self.assertEqual(guard.handle(self.scope, stop)[1], 2)
        self.assertEqual(guard.handle(self.scope, stop)[1], 0)
        self.assertEqual(guard.handle(self.scope, dict(stop, stop_hook_active=True))[1], 0)

    def test_registration_stop_then_first_prepare_keeps_workspace_clean(self):
        stop = {"hook_event_name": "Stop", "session_id": self.event["session_id"], "cwd": self.event["cwd"]}
        self.assertEqual(guard.handle(self.scope, stop)[1], 2)
        self.assertFalse(self.workspace.exists())
        self.prepare()
        self.assertTrue((self.workspace / "production.json").is_file())

    def test_activation_cannot_place_guard_files_in_unprepared_workspace(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(guard.main(["activate", "--project", str(self.project), "--workspace", str(self.workspace),
                                         "--session-id", "new-session", "--scope", str(self.workspace / "scope.json"),
                                         "--hooks-output", str(self.project / "proposed-settings.json")]), 2)
        self.assertFalse(self.workspace.exists())

    def test_stop_pending_unknown_allows_recovery_handoff(self):
        self.prepare()
        self.claim()
        result, code = guard.handle(self.scope, dict(self.event, hook_event_name="Stop"))
        self.assertEqual((code, result["action"]), (0, "allow_pending_reconciliation_handoff"))

    def test_cli_emits_exit_two_for_block_and_deactivate_preserves_state(self):
        with patch("sys.stdin", io.StringIO(json.dumps(self.event))), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(guard.main(["hook", "--scope", str(self.scope)]), 2)
        self.assertIn("S7 board guard", json.loads(out.getvalue())["reason"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(guard.main(["deactivate", "--scope", str(self.scope)]), 0)
        self.assertEqual(guard.handle(self.scope, self.event)[0]["action"], "outside_registered_s7_scope")

    def test_activate_only_writes_reviewable_task_config(self):
        scope, settings = self.project / "new-scope.json", self.project / "proposed-hooks.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(guard.main(["activate", "--project", str(self.project), "--workspace", str(self.workspace),
                                         "--session-id", "new-session", "--scope", str(scope),
                                         "--hooks-output", str(settings)]), 0)
        self.assertTrue(core.read(scope)["active"])
        command = core.read(settings)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("workbuddy_board_guard.py", command)
        self.assertFalse((self.project / ".workbuddy/settings.json").exists())

    def test_discover_session_install_probe_bind_then_real_prepare_without_fake_id(self):
        self.scope = self.project / "discover-scope.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(guard.main(["activate", "--project", str(self.project), "--workspace", str(self.workspace),
                                         "--discover-session", "--scope", str(self.scope),
                                         "--hooks-output", str(self.project / "discover-proposed.json")]), 0)
        value = core.read(self.scope)
        self.assertIsNone(value["host_session_id"])
        self.assertEqual(value["session_binding"], "unbound-probe-only")
        guard.install(self.scope, self.project / "temporary-user-settings.json")
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.project),
                 "session_id": self.event["session_id"], "tool_use_id": "discover-original-native-call",
                 "tool_input": {"command": guard.probe_status(self.scope)["command"]}}
        self.assertEqual(guard.handle(self.scope, event)[1], 2)
        status = guard.probe_status(self.scope)
        self.assertIsNone(core.read(self.scope)["host_session_id"])
        guard.bind_session(self.scope, status["host_session_id"])
        self.assertEqual(core.read(self.scope)["session_binding"], "bound")
        self.assertFalse(self.workspace.exists())
        self.prepare()
        self.claim()
        self.assertEqual(guard.handle(self.scope, self.event)[1], 0)

    def test_unbound_scope_blocks_all_imagegen_and_does_not_trap_stop(self):
        scope = self.project / "unbound-scope.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(guard.main(["activate", "--project", str(self.project), "--workspace", str(self.workspace),
                                         "--discover-session", "--scope", str(scope),
                                         "--hooks-output", str(self.project / "unbound-proposed.json")]), 0)
        for changes in ({}, {"session_id": None}, {"tool_name": "ImageGen", "tool_input": {"prompt": "blocked"}}):
            event = dict(self.event, **changes)
            with patch("sys.stdin", io.StringIO(json.dumps(event))), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(guard.main(["hook", "--scope", str(scope)]), 2)
            self.assertIn("unbound-probe-only", json.loads(output.getvalue())["reason"])
        stop = {"hook_event_name": "Stop", "cwd": str(self.project), "session_id": "actual-native-session"}
        for _ in range(3):
            self.assertEqual(guard.handle(scope, stop)[1], 0)
        self.assertFalse(self.workspace.exists())
        self.assertFalse((self.project / "unbound-scope.json.events/stop").exists())
        for arguments in ([], ["--discover-session", "--session-id", "unnecessary-id"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                guard.main(["activate", "--project", str(self.project), "--workspace", str(self.workspace),
                            "--scope", str(scope), "--hooks-output", str(self.project / "unused.json"), *arguments])

    def test_probe_renewal_changes_only_probe_identity_and_preserves_original_claim_bytes(self):
        value = core.read(self.scope)
        value.update(probe_nonce="c" * 32, probe_revision=1)
        core.write(self.scope, value)
        self.prepare()
        self.claim()
        guarded = guard.handle(self.scope, self.event)[0]
        original_scope = core.read(self.scope)
        original_files = {path: path.read_bytes() for path in self.workspace.rglob("*") if path.is_file()}
        result = guard.renew_probe(self.scope)
        current = core.read(self.scope)
        self.assertEqual({key for key in current if current[key] != original_scope.get(key)},
                         {"probe_nonce", "probe_revision"})
        self.assertEqual(result["probe_revision"], 2)
        self.assertEqual(current["host_session_id"], original_scope["host_session_id"])
        for path, content in original_files.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(board_production.inspect_claim(self.workspace, guarded["page_id"])["claim"]["status"], "pending")


class WorkBuddyBoardGuardInstallation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        self.workspace = self.project / "art/production"
        self.scope = self.project / "scope.json"
        core.write(self.scope, {"schema": 1, "kind": "workbuddy-board-guard-scope", "active": True,
                               "stage": "S7", "project": str(self.project), "workspace": str(self.workspace),
                               "host_session_id": "placeholder-session", "probe_nonce": "a" * 32})
        self.settings = self.project / "selected-host" / "settings.json"
        self.original = {"privateValue": "fixture-secret-never-copy-to-receipt", "language": "zh",
                         "hooks": {"PreToolUse": [{"matcher": "Read", "hooks": [
                             {"type": "command", "command": "someone-elses-pre", "timeout": 7}]}],
                                   "Stop": [{"hooks": [{"type": "command", "command": "someone-elses-stop"}]}],
                                   "SessionStart": [{"hooks": [{"type": "command", "command": "keep-start"}]}]}}
        core.write(self.settings, self.original)

    def test_install_preserves_other_settings_hooks_and_writes_small_receipt(self):
        result = guard.install(self.scope, self.settings)
        self.assertTrue(result["installed"])
        self.assertFalse(result["host_hook_loading_verified"])
        self.assertEqual(result["settings_cache_seconds"], 60)
        settings = core.read(self.settings)
        self.assertEqual(settings["privateValue"], self.original["privateValue"])
        self.assertEqual(settings["hooks"]["PreToolUse"][0], self.original["hooks"]["PreToolUse"][0])
        self.assertEqual(settings["hooks"]["SessionStart"], self.original["hooks"]["SessionStart"])
        self.assertFalse(settings.get("allowUntrustedFrontmatterHooks", False))
        receipt = Path(result["receipt"]).read_text()
        self.assertNotIn(self.original["privateValue"], receipt)
        parsed = json.loads(receipt)
        self.assertNotEqual(parsed["before_sha256"], parsed["after_sha256"])
        self.assertEqual(set(parsed["entries_added"]), {"PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop"})
        self.assertFalse(self.workspace.exists())

    def test_install_is_idempotent_without_reformatting_second_time(self):
        guard.install(self.scope, self.settings)
        first = self.settings.read_bytes()
        result = guard.install(self.scope, self.settings)
        self.assertFalse(result["changed"])
        self.assertEqual(self.settings.read_bytes(), first)
        receipt = core.read(result["receipt"])
        self.assertEqual(receipt["entries_added"], {})
        self.assertEqual(receipt["before_sha256"], receipt["after_sha256"])

    def test_two_scopes_and_uninstall_preserve_other_scope_and_mixed_hooks(self):
        other = self.project / "other-scope.json"
        core.write(other, dict(core.read(self.scope), probe_nonce="b" * 32))
        guard.install(self.scope, self.settings)
        guard.install(other, self.settings)
        settings = core.read(self.settings)
        entry = settings["hooks"]["PreToolUse"][1]
        entry["hooks"].append({"type": "command", "command": "keep-mixed-hook"})
        core.write(self.settings, settings)
        self.assertFalse(guard.uninstall(self.scope, self.settings)["installed"])
        remaining = core.read(self.settings)
        commands = [item["command"] for event in remaining["hooks"].values()
                    for entry in event for item in entry["hooks"] if item.get("type") == "command"]
        self.assertIn("keep-mixed-hook", commands)
        self.assertIn(guard._script_command(other), commands)
        self.assertNotIn(guard._script_command(self.scope), commands)
        self.assertEqual(remaining["privateValue"], self.original["privateValue"])
        before = self.settings.read_bytes()
        self.assertFalse(guard.uninstall(self.scope, self.settings)["changed"])
        self.assertEqual(self.settings.read_bytes(), before)

    def test_uninstall_does_not_delete_claims_or_require_active_scope(self):
        guard.install(self.scope, self.settings)
        old_claim = self.workspace / "pages/board-001/claim.json"
        core.write(old_claim, {"source_ref": "keep-original-call", "status": "pending"})
        scope = core.read(self.scope)
        scope["active"] = False
        core.write(self.scope, scope)
        guard.uninstall(self.scope, self.settings)
        self.assertEqual(core.read(old_claim)["source_ref"], "keep-original-call")
        settings = core.read(self.settings)
        self.assertEqual(settings["hooks"], self.original["hooks"])

    def test_atomic_install_and_uninstall_preserve_mode(self):
        os.chmod(self.settings, 0o640)
        for action in (guard.install, guard.uninstall):
            action(self.scope, self.settings)
            self.assertEqual(stat.S_IMODE(self.settings.stat().st_mode), 0o640)

    def test_visible_concurrent_settings_change_is_not_overwritten(self):
        original_write = guard._atomic_settings_write

        def competing_write(path, raw, snapshot):
            core.write(path, dict(self.original, concurrent="preserve-this"))
            return original_write(path, raw, snapshot)

        with patch.object(guard, "_atomic_settings_write", side_effect=competing_write):
            with self.assertRaisesRegex(ValueError, "concurrently"):
                guard.install(self.scope, self.settings)
        self.assertEqual(core.read(self.settings)["concurrent"], "preserve-this")
        self.assertEqual(list(self.settings.parent.glob("*.board-guard-*")), [])

    def test_missing_settings_creates_private_file_and_explicit_cli_path_required(self):
        missing = self.project / "explicit-new-config/settings.json"
        guard.install(self.scope, missing)
        self.assertEqual(stat.S_IMODE(missing.stat().st_mode), 0o600)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            guard.main(["install", "--scope", str(self.scope)])

    def test_conflicting_same_command_matcher_and_malformed_json_are_preserved(self):
        value = copy.deepcopy(self.original)
        own = guard._hook_settings(self.scope)["hooks"]["PreToolUse"][0]
        value["hooks"]["PreToolUse"].append(dict(own, matcher="Read"))
        core.write(self.settings, value)
        original = self.settings.read_bytes()
        with self.assertRaisesRegex(ValueError, "different matcher/options"):
            guard.install(self.scope, self.settings)
        self.assertEqual(self.settings.read_bytes(), original)
        self.settings.write_text("{invalid JSON", encoding="utf-8")
        with self.assertRaises(ValueError):
            guard.install(self.scope, self.settings)
        self.assertEqual(self.settings.read_text(), "{invalid JSON")

    def test_uninstall_reports_modified_own_entry_that_it_preserves(self):
        guard.install(self.scope, self.settings)
        settings = core.read(self.settings)
        settings["hooks"]["PreToolUse"][-1]["hooks"][0]["timeout"] = 29
        core.write(self.settings, settings)
        result = guard.uninstall(self.scope, self.settings)
        self.assertTrue(result["installed"])
        self.assertEqual(result["remaining_scope_commands"], 1)
        self.assertEqual(core.read(self.settings)["hooks"]["PreToolUse"][-1]["hooks"][0]["timeout"], 29)
        self.assertIn("Review them explicitly", result["next_action"])

    def event(self, command=None, **changes):
        return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "actual-desktop-session",
                "tool_use_id": "actual-probe-call", "cwd": str(self.project),
                "tool_input": {"command": command or guard.probe_status(self.scope)["command"]}, **changes}

    def test_exact_probe_blocks_before_session_binding_and_returns_original_evidence(self):
        event = self.event()
        result, code = guard.handle(self.scope, event)
        self.assertEqual(code, 2)
        self.assertEqual(core.read(result["evidence"])["event"], event)
        status = guard.probe_status(self.scope)
        self.assertTrue(status["pre_hook_observed"])
        self.assertTrue(status["probe_passed"])
        self.assertEqual(status["host_session_id"], "actual-desktop-session")
        self.assertFalse(status["imagegen_interception_verified"])
        self.assertEqual(core.read(self.scope)["host_session_id"], "placeholder-session")
        self.assertFalse(self.workspace.exists())

    def test_other_bash_command_or_prefix_never_records_probe(self):
        exact = guard.probe_status(self.scope)["command"]
        for command in ("printf ordinary", "cd . && " + exact, exact + " --extra", exact.replace("a" * 32, "b" * 32)):
            result, code = guard.handle(self.scope, self.event(command))
            self.assertEqual((code, result["action"]), (0, "outside_tool_scope"))
        self.assertEqual(list(guard._probe_dir(self.scope).glob("*.json")), [])
        with self.assertRaisesRegex(ValueError, "registered native project"):
            guard.handle(self.scope, self.event(cwd="/outside-project"))

    def test_executed_probe_is_always_failure_even_if_pre_event_exists(self):
        guard.handle(self.scope, self.event())
        result, code = guard.probe(self.scope, "a" * 32)
        self.assertEqual(code, 2)
        self.assertTrue(result["unexpected_execution"])
        status = guard.probe_status(self.scope)
        self.assertFalse(status["probe_passed"])
        self.assertTrue(status["unexpected_execution"])
        self.assertFalse(self.workspace.exists())

    def test_probe_cli_status_never_treats_body_execution_as_host_evidence(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(guard.main(["probe", "--scope", str(self.scope), "--nonce", "a" * 32]), 2)
        self.assertFalse(json.loads(output.getvalue())["probe_passed"])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(guard.main(["probe-status", "--scope", str(self.scope)]), 0)
        status = json.loads(output.getvalue())
        self.assertFalse(status["pre_hook_observed"])
        self.assertFalse(status["probe_passed"])

    def test_unloaded_probe_failure_can_renew_then_pass_new_exact_pre_without_deleting_history(self):
        result, code = guard.probe(self.scope, "a" * 32)
        self.assertEqual(code, 2)
        failed = Path(result["evidence"])
        original = failed.read_bytes()
        # An earlier build lacked nonce fields; explicit renewal
        # also archives that exact legacy failure by immutable path/hash.
        legacy = guard._probe_dir(self.scope) / "legacy-unloaded-body.json"
        core.write(legacy, {"schema": 1, "kind": "workbuddy-board-carrier-probe-unexpected-execution",
                            "scope_sha256": core.file_hash(self.scope)})
        legacy_original = legacy.read_bytes()
        self.assertFalse(guard.probe_status(self.scope)["probe_passed"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(guard.main(["renew-probe", "--scope", str(self.scope)]), 0)
        status = guard.probe_status(self.scope)
        self.assertEqual(status["probe_revision"], 2)
        self.assertFalse(status["probe_passed"])
        self.assertEqual(status["historical_failed_attempt_count"], 2)
        self.assertEqual(guard.handle(self.scope, self.event())[1], 2)
        status = guard.probe_status(self.scope)
        self.assertTrue(status["probe_passed"])
        self.assertFalse(status["unexpected_execution"])
        self.assertEqual(status["historical_failed_attempt_count"], 2)
        self.assertEqual(failed.read_bytes(), original)
        self.assertEqual(legacy.read_bytes(), legacy_original)

    def test_old_pre_event_cannot_satisfy_a_renewed_probe(self):
        old_event = self.event()
        self.assertEqual(guard.handle(self.scope, old_event)[1], 2)
        self.assertTrue(guard.probe_status(self.scope)["probe_passed"])
        guard.renew_probe(self.scope)
        status = guard.probe_status(self.scope)
        self.assertFalse(status["pre_hook_observed"])
        self.assertFalse(status["probe_passed"])
        self.assertIsNone(status["host_session_id"])
        self.assertEqual(len(status["historical_pre_events"]), 1)
        self.assertEqual(guard.handle(self.scope, old_event)[0]["action"], "outside_tool_scope")


if __name__ == "__main__":
    unittest.main()
