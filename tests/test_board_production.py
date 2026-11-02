"""Real-module, offline production tests with synthetic images; no provider calls."""
import contextlib
import copy
import errno
import io
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art/runtime"))
from greybox import board_production as production, core, cli
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "Board production pixel operations require the selected private Pillow runtime")
class BoardProduction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name).resolve()
        self.workspace = self.project / "art/production"
        Image.new("RGB", (256, 256), "blue").save(self.project / "style.png")
        self.views = [{"asset_id": "prop-" + str(index), "view_id": "three_quarter", "role": "three_quarter",
                       "projected_aspect": 1.0, "min_subject_long_edge_px": 128,
                       "min_subject_short_edge_px": 128} for index in range(5)]
        self.source = {"schema": 1, "kind": "reference-board-scope", "asset_views": copy.deepcopy(self.views)}
        self.spec = {"schema": 1, "kind": "reference-board-prepare-input", "purpose": "modeling",
                     "plan": {"schema": 1, "kind": "reference-board-plan-input", "channel_size": [768, 768],
                              "size_source_ref": "synthetic test image dimensions, no provider qualification", "views": copy.deepcopy(self.views)},
                     "images": [{"path": "style.png", "sha256": core.file_hash(self.project / "style.png")}],
                     "image_roles": [{"role": "style"}],
                     "objects": [dict(asset_id=row["asset_id"], view_id=row["view_id"], role=row["role"],
                                      category="prop", function="An independent museum exhibit used as a rigid object.",
                                      appearance="A rounded solid exhibit with a visible authored surface pattern.",
                                      structure="A single closed volume with a flat integral underside.",
                                      modeling_contract={"category": "prop", "use": "rigid_motion"}) for row in self.views],
                     "capabilities": {"edit": True, "max_references": 2, "layout_guide": True,
                                      "source_ref": "synthetic capability fixture; not real host evidence"}, "parameters": {}}
        self.binding = {"schema": 1, "kind": "reference-board-native-binding", "host": "codex", "tool": "image_gen.imagegen",
                        "source_ref": "synthetic tool schema fixture", "input_transport": "local_paths", "max_references": 2,
                        "image_argument": "referenced_image_paths", "fixed_arguments": {"transparent_background": False}}
        self.request = {"schema": 1, "kind": "reference-board-production-input", "host_session_id": "synthetic-session",
                        "scope": {"source_ref": "synthetic upstream scope; no paid-generation authorization",
                                  "asset_views": copy.deepcopy(self.views)}}
        self.save_inputs()

    def ref(self, name):
        return {"path": name, "sha256": core.file_hash(self.project / name)}

    def save_inputs(self):
        core.write(self.project / "scope.json", self.source)
        core.write(self.project / "prepare.json", self.spec)
        core.write(self.project / "binding.json", self.binding)
        self.request["scope"]["source"] = self.ref("scope.json")
        self.request["prepare_spec"] = self.ref("prepare.json")
        self.request["native_binding"] = self.ref("binding.json")
        core.write(self.project / "production-request.json", self.request)

    def prepare(self):
        return production.prepare(self.request, self.project, self.workspace, request_path="production-request.json")

    def page(self, page_id="board-001"):
        return core.read(self.workspace / "pages" / page_id / "state.json")

    def make_output(self, page_id="board-001"):
        page = self.page(page_id)
        image = Image.new("RGB", (768, 768), "white")
        drawing = ImageDraw.Draw(image)
        rows = []
        for number, slot in enumerate(page["slots"]):
            left, top, right, bottom = slot["planned_region"]
            x, y = left + (right - left - 145) // 2, top + (bottom - top - 145) // 2
            drawing.rectangle([x, y, x + 144, y + 144], fill=["red", "green", "purple", "black"][number % 4])
            rows.append({"asset_id": slot["asset_id"], "view_id": slot["view_id"], "role": slot["role"],
                         "roi": [left + 12, top + 12, right - 12, bottom - 12]})
        path = self.project / (page_id + "-generated.png")
        image.save(path)
        return path, rows

    def record(self, page_id="board-001"):
        production.claim(self.workspace, page_id)
        info = production.inspect_claim(self.workspace, page_id)
        image, rois = self.make_output(page_id)
        result = production.record(self.workspace, page_id, info["tool_arguments"], image,
                                   source_ref="synthetic-call-" + page_id,
                                   tool_result={"synthetic": True, "path": str(image)})
        return result, image, rois

    def reviews(self, page_id="board-001", verdict="pass"):
        result = []
        for name, crop_ref in self.page(page_id)["crops"].items():
            receipt = core.read(self.project / crop_ref["path"])
            recipe = receipt["recipe"]
            result.append({"asset_id": recipe["asset_id"], "view_id": recipe["view_id"], "role": recipe["role"],
                           "image": receipt["output"], "verdict": verdict,
                           "observation": "Synthetic fixture has one complete colored silhouette and an intact white boundary.",
                           "inspection_source_ref": "synthetic test pixel inspection; not native host evidence"})
        return result

    def test_prepare_and_claim_keep_broker_checks_when_existing_mkdir_returns_eexist(self):
        native_mkdir = Path.mkdir
        checked = []

        def broker(path, *args, **kwargs):
            checked.append(path)
            if path.exists():
                raise FileExistsError(errno.EEXIST, "host shim omitted exist_ok", str(path))
            return native_mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", broker):
            self.prepare()
            result = production.claim(self.workspace, "board-001")
        self.assertEqual(result["claim"]["status"], "pending")
        self.assertTrue(checked)
        self.assertFalse(self.page().get("invocation_recorded"))

    def test_multiple_pages_are_prepared_mapped_and_do_not_claim_success(self):
        result = self.prepare()
        self.assertEqual(result["declared_view_count"], 5)
        self.assertEqual(len(result["pages"]), 2)
        self.assertTrue(all(page["mapped"] for page in result["pages"]))
        self.assertFalse(result["complete"])
        self.assertFalse(result["human_approval"])
        self.assertFalse(result["host_trace_verified"])

    def test_status_orders_claim_recovery_crop_and_review_without_premature_repairs(self):
        prepared = self.prepare()
        self.assertEqual(prepared["repair_views"], [])
        self.assertTrue(all(page["phase"] == "claim" and page["repair_views"] == [] for page in prepared["pages"]))
        self.assertIn("Claim this prepared page", prepared["next_action"])
        production.claim(self.workspace, "board-001")
        pending = production.status(self.workspace)
        first = pending["pages"][0]
        self.assertEqual(first["phase"], "recover")
        self.assertEqual(first["repair_views"], [])
        self.assertIn("Recover the original pending", pending["next_action"])
        info = production.inspect_claim(self.workspace, "board-001")
        image, rois = self.make_output()
        recorded = production.record(self.workspace, "board-001", info["tool_arguments"], image,
                                     source_ref="synthetic-original-status-call", tool_result={"synthetic": True})
        self.assertEqual(recorded["phase"], "crop")
        self.assertIn("actual board", recorded["next_action"])
        self.assertEqual(len(recorded["repair_views"]), 4)
        cropped = production.crop(self.workspace, "board-001", rois)
        self.assertEqual(cropped["phase"], "review")
        self.assertEqual(cropped["repair_views"], [])
        reviewed = production.review(self.workspace, "board-001", self.reviews())
        self.assertEqual(reviewed["phase"], "complete")
        self.assertIsNone(reviewed["next_action"])

    def test_bad_native_binding_keeps_creative_ready_and_a_new_binding_can_recover(self):
        self.binding["max_references"] = 1
        self.save_inputs()
        result = self.prepare()
        self.assertEqual(result["preparation_status"], "ready")
        self.assertFalse(result["complete"])
        self.assertFalse(result["pages"][0]["mapped"])
        self.assertEqual(result["pages"][0]["phase"], "map")
        self.assertEqual(result["pages"][0]["repair_views"], [])
        self.assertTrue(result["pages"][0]["mapping_error"])
        self.assertFalse(result["submission"])
        self.assertFalse((self.workspace / "pages/board-001/claim.json").exists())
        original_bad_hash = core.file_hash(self.project / "binding.json")
        request_hash = core.file_hash(self.project / "production-request.json")
        repaired = dict(self.binding, max_references=2)
        core.write(self.project / "binding-fixed.json", repaired)
        production.map_native(self.workspace, "board-001", "binding-fixed.json")
        info = production.claim(self.workspace, "board-001")
        self.assertEqual(info["claim"]["status"], "pending")
        self.assertEqual(core.file_hash(self.project / "binding.json"), original_bad_hash)
        self.assertEqual(core.file_hash(self.project / "production-request.json"), request_hash)
        attempts = self.page()["mapping_attempts"]
        self.assertEqual([row["result"] for row in attempts], ["failed", "mapped"])
        self.assertEqual(attempts[0]["binding"]["path"], "binding.json")

    def test_only_unclaimed_pages_can_be_remapped_and_old_dispatch_is_retained(self):
        self.prepare()
        original = production.inspect_claim(self.workspace, "board-001")
        changed = dict(self.binding, source_ref="new explicit current schema with the same parameters")
        core.write(self.project / "binding-new.json", changed)
        remapped = production.map_native(self.workspace, "board-001", "binding-new.json")
        self.assertNotEqual(original["dispatch"]["path"], remapped["dispatch"]["path"])
        self.assertTrue(Path(original["dispatch"]["path"]).is_file())
        production.claim(self.workspace, "board-001")
        another = dict(changed, source_ref="another native schema revision")
        core.write(self.project / "binding-next.json", another)
        with self.assertRaisesRegex(ValueError, "Claimed page cannot be remapped"):
            production.map_native(self.workspace, "board-001", "binding-next.json")

    def test_legal_delimiter_containing_ids_do_not_collide_in_state_or_crop_paths(self):
        names = [("a", "b--c"), ("a--b", "c")]
        self.spec["plan"]["views"] = self.spec["plan"]["views"][:2]
        self.spec["objects"] = self.spec["objects"][:2]
        self.source["asset_views"] = self.source["asset_views"][:2]
        self.request["scope"]["asset_views"] = self.request["scope"]["asset_views"][:2]
        for index, (asset, view) in enumerate(names):
            for rows in (self.spec["plan"]["views"], self.spec["objects"], self.source["asset_views"], self.request["scope"]["asset_views"]):
                rows[index].update(asset_id=asset, view_id=view)
        self.save_inputs()
        result = self.prepare()
        self.assertEqual(result["pages"][0]["view_count"], 2)
        _, _, rois = self.record()
        result = production.crop(self.workspace, "board-001", rois)
        self.assertEqual(len(result["crops"]), 2)
        self.assertNotEqual(production.identity_key(*names[0]), production.identity_key(*names[1]))
        result = production.review(self.workspace, "board-001", self.reviews())
        self.assertTrue(result["complete"])
        self.assertEqual(len({ref["path"] for ref in result["crops"].values()}), 2)

    def test_os_lock_rejects_concurrent_thread_and_never_unlinks_another_owner(self):
        self.prepare()
        lock_path = self.workspace / "pages/board-001/operation.lock"
        # Legacy dead-PID contents must not trigger compare/unlink recovery.
        core.write(lock_path, {"pid": 999999999, "created_at": "historical synthetic dead owner"})
        acquired, release, attempted = threading.Event(), threading.Event(), threading.Event()
        outcomes = []
        inode = lock_path.stat().st_ino
        def first():
            with production._page_lock(self.workspace, "board-001"):
                acquired.set()
                if not release.wait(5):
                    outcomes.append("timeout")
        def second():
            acquired.wait(5)
            try:
                with production._page_lock(self.workspace, "board-001"):
                    outcomes.append("unsafe second owner")
            except ValueError:
                outcomes.append("busy")
            finally:
                attempted.set()
        one, two = threading.Thread(target=first), threading.Thread(target=second)
        one.start(); two.start()
        try:
            self.assertTrue(attempted.wait(5))
            self.assertEqual(outcomes, ["busy"])
            self.assertEqual(lock_path.stat().st_ino, inode)
        finally:
            release.set()
            one.join(5); two.join(5)
        with production._page_lock(self.workspace, "board-001"):
            self.assertEqual(lock_path.stat().st_ino, inode)

    def test_plan_and_objects_cannot_omit_the_same_upstream_view(self):
        self.spec["plan"]["views"].pop()
        self.spec["objects"].pop()
        self.request["scope"]["asset_views"].pop()
        self.save_inputs()
        with self.assertRaisesRegex(ValueError, "Upstream scope"):
            self.prepare()
        self.assertFalse(self.workspace.exists())

    def test_scope_cannot_bind_itself_as_an_independent_source(self):
        self.request["scope"]["source"] = self.ref("prepare.json")
        core.write(self.project / "production-request.json", self.request)
        with self.assertRaisesRegex(ValueError, "independent"):
            self.prepare()

    def test_view_names_are_not_guessed_from_bom(self):
        self.source = {"asset_proposals": [{"asset_id": "prop-0", "required_views": ["side"]}]}
        self.save_inputs()
        with self.assertRaisesRegex(ValueError, "approved_reference_views"):
            self.prepare()

    def test_placeholder_object_and_contract_are_blocked(self):
        for field in ("appearance", "contract"):
            original = copy.deepcopy(self.spec)
            if field == "contract":
                self.spec["objects"][0]["modeling_contract"]["structure"] = "TODO"
            else:
                self.spec["objects"][0][field] = "Placeholder"
            self.save_inputs()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "concrete|Placeholder"):
                self.prepare()
            self.spec = original

    def test_normal_prose_about_replacing_placeholders_is_valid(self):
        self.spec["objects"][0]["appearance"] = "A rounded finished prop, not the greybox placeholder; its authored surface pattern stays visible."
        self.spec["objects"][0]["structure"] = "已替换占位体，当前实体有封闭底面和完整连接结构。"
        self.request["scope"]["source_ref"] = "已确认替换占位体的上游范围记录；不是自动审批。"
        self.save_inputs()
        self.assertEqual(self.prepare()["preparation_status"], "ready")

    def test_unresolved_quality_keeps_a_blocked_persistent_result(self):
        self.spec["plan"]["views"][0]["min_subject_long_edge_px"] = 3000
        self.save_inputs()
        with self.assertRaisesRegex(ValueError, "Unresolved"):
            self.prepare()
        state = production.status(self.workspace)
        self.assertEqual(state["preparation_status"], "blocked")
        self.assertFalse(state["complete"])

    def test_frozen_source_spec_and_image_changes_block_claim(self):
        self.prepare()
        for filename in ("scope.json", "prepare.json", "style.png"):
            path = self.project / filename
            raw = path.read_bytes()
            path.write_bytes(raw + b" ")
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, "Frozen"):
                production.claim(self.workspace, "board-001")
            path.write_bytes(raw)

    def test_atomic_claim_is_once_and_inspection_exposes_hook_identity(self):
        self.prepare()
        first = production.claim(self.workspace, "board-001")
        self.assertEqual(first["claim"]["status"], "pending")
        self.assertEqual(first["host_session_id"], "synthetic-session")
        self.assertTrue(first["claim_file"]["sha256"])
        self.assertTrue(Path(first["dispatch"]["path"]).is_absolute())
        with self.assertRaisesRegex(ValueError, "already claimed"):
            production.claim(self.workspace, "board-001")

    def test_handoff_preserves_pending_claim_and_allows_only_unclaimed_pages_in_new_session(self):
        self.prepare()
        original = production.claim(self.workspace, "board-001")
        request_hash = core.file_hash(self.project / "production-request.json")
        dispatch_hash = original["dispatch"]["sha256"]
        claim_hash = original["claim_file"]["sha256"]
        changed = production.bind_session(self.workspace, "session-B")
        self.assertEqual(changed["pending_original_calls"][0]["page_id"], "board-001")
        old = production.inspect_claim(self.workspace, "board-001")
        self.assertEqual(old["host_session_id"], "synthetic-session")
        self.assertEqual(old["active_host_session_id"], "session-B")
        self.assertEqual(old["claim_file"]["sha256"], claim_hash)
        self.assertEqual(old["dispatch"]["sha256"], dispatch_hash)
        self.assertEqual(core.file_hash(self.project / "production-request.json"), request_hash)
        with self.assertRaisesRegex(ValueError, "already claimed"):
            production.claim(self.workspace, "board-001")
        with self.assertRaisesRegex(ValueError, "previous host session"):
            production.verify(self.workspace, "board-001", old["tool_arguments"])
        second = production.claim(self.workspace, "board-002")
        self.assertEqual(second["host_session_id"], "session-B")
        self.assertEqual(second["claim"]["host_session_id"], "session-B")
        image, _ = self.make_output()
        result = production.record(self.workspace, "board-001", old["tool_arguments"], image,
                                   source_ref="original-session-A-call", tool_result={"synthetic": "recovered original outcome"})
        self.assertTrue(result["invocation_recorded"])
        self.assertFalse(result["handoff_pending"])
        context = core.read(self.workspace / "context.json")
        self.assertEqual([row["host_session_id"] for row in context["history"]], ["synthetic-session", "session-B"])

    def test_exact_arguments_are_required_by_verify_and_record(self):
        self.prepare()
        production.claim(self.workspace, "board-001")
        info = production.inspect_claim(self.workspace, "board-001")
        arguments = copy.deepcopy(info["tool_arguments"])
        arguments["prompt"] += "Rewrite the object"
        with self.assertRaisesRegex(ValueError, "arguments differ"):
            production.verify(self.workspace, "board-001", arguments)
        image, _ = self.make_output()
        with self.assertRaisesRegex(ValueError, "arguments differ"):
            production.record(self.workspace, "board-001", arguments, image, source_ref="synthetic-call")

    def test_unclaimed_record_is_rejected(self):
        self.prepare()
        info = production.inspect_claim(self.workspace, "board-001")
        image, _ = self.make_output()
        with self.assertRaisesRegex(ValueError, "one-time claim"):
            production.record(self.workspace, "board-001", info["tool_arguments"], image, source_ref="synthetic-call")

    def test_input_cannot_impersonate_a_generated_board(self):
        self.prepare()
        production.claim(self.workspace, "board-001")
        info = production.inspect_claim(self.workspace, "board-001")
        with self.assertRaisesRegex(ValueError, "impersonate"):
            production.record(self.workspace, "board-001", info["tool_arguments"], self.project / "style.png", source_ref="synthetic-call")

    def test_record_is_idempotent_and_rejects_a_different_original_call(self):
        self.prepare()
        _, image, _ = self.record()
        info = production.inspect_claim(self.workspace, "board-001")
        receipt = self.page()["generation_receipt"]
        before = (self.project / receipt["path"]).stat().st_mtime_ns
        production.record(self.workspace, "board-001", info["tool_arguments"], image,
                          source_ref="synthetic-call-board-001", tool_result={"synthetic": True, "path": str(image)})
        self.assertEqual(before, (self.project / receipt["path"]).stat().st_mtime_ns)
        with self.assertRaisesRegex(ValueError, "original call"):
            production.record(self.workspace, "board-001", info["tool_arguments"], image, source_ref="a-new-call")

    def test_record_can_recover_the_same_local_receipt_after_interruption(self):
        self.prepare()
        production.claim(self.workspace, "board-001")
        info = production.inspect_claim(self.workspace, "board-001")
        image, _ = self.make_output()
        original = production.board_native.record
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("synthetic response lost after receipt")
        with patch.object(production.board_native, "record", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "response lost"):
                production.record(self.workspace, "board-001", info["tool_arguments"], image, source_ref="synthetic-call")
        self.assertEqual(production.inspect_claim(self.workspace, "board-001")["claim"]["status"], "pending")
        with patch.object(production.board_native, "record", side_effect=AssertionError("Must reuse the existing original receipt")):
            result = production.record(self.workspace, "board-001", info["tool_arguments"], image, source_ref="synthetic-call")
        self.assertTrue(result["invocation_recorded"])

    def test_crop_inherits_quality_and_allows_a_partial_repair(self):
        self.prepare()
        _, _, rois = self.record()
        partial = production.crop(self.workspace, "board-001", rois[:-1])
        self.assertEqual(partial["available_crop_count"], 3)
        self.assertFalse(partial["all_crops_available"])
        self.assertFalse(partial["crop_technical_pass"])
        altered = copy.deepcopy(rois)
        altered[0]["min_subject_long_edge_px"] = 1
        with self.assertRaisesRegex(ValueError, "may not lower"):
            production.crop(self.workspace, "board-001", altered)
        result = production.crop(self.workspace, "board-001", rois)
        self.assertTrue(result["crop_technical_pass"])
        self.assertFalse(result["visual_review_recorded"])

    def test_actual_small_subject_cannot_pass_the_frozen_pixel_requirement(self):
        self.prepare()
        production.claim(self.workspace, "board-001")
        info = production.inspect_claim(self.workspace, "board-001")
        image, rois = self.make_output()
        small = Image.new("RGB", (768, 768), "white")
        draw = ImageDraw.Draw(small)
        for row in rois:
            x, y = row["roi"][:2]
            draw.rectangle([x + 30, y + 30, x + 60, y + 60], fill="black")
        small.save(image)
        production.record(self.workspace, "board-001", info["tool_arguments"], image, source_ref="synthetic-small-call")
        result = production.crop(self.workspace, "board-001", rois)
        self.assertEqual(result["available_crop_count"], 4)
        self.assertTrue(result["all_crops_available"])
        self.assertFalse(result["crop_technical_pass"])
        self.assertFalse(result["complete"])
        self.assertEqual(len(result["repair_views"]), 4)
        for ref in result["crops"].values():
            self.assertTrue((self.project / core.read(self.project / ref["path"])["output"]["path"]).is_file())
            with self.assertRaisesRegex(ValueError, "inspection evidence only"):
                production.boards.validate_crop_receipt(ref, self.project)
        reviewed = production.review(self.workspace, "board-001", self.reviews())
        self.assertTrue(reviewed["visual_all_pass"])
        self.assertFalse(reviewed["complete"])

    def test_invalid_first_slot_does_not_abort_good_siblings_and_can_be_repaired(self):
        self.prepare()
        _, _, rois = self.record()
        invalid = copy.deepcopy(rois)
        invalid[0]["roi"][0] = -1
        first = production.crop(self.workspace, "board-001", invalid)
        self.assertEqual(first["available_crop_count"], 3)
        self.assertEqual(len(first["crop_errors"]), 1)
        self.assertFalse(first["crop_technical_pass"])
        good = copy.deepcopy(first["crops"])
        old_attempts = copy.deepcopy(first["crop_attempts"])
        production.review(self.workspace, "board-001", self.reviews())
        repaired = production.crop(self.workspace, "board-001", rois[:1])
        self.assertEqual(repaired["crop_errors"], {})
        self.assertTrue(repaired["crop_technical_pass"])
        self.assertEqual({key: repaired["crops"][key] for key in good}, good)
        self.assertEqual(len(self.page()["reviews"]), 3)
        name = production.identity_key(rois[0]["asset_id"], rois[0]["view_id"])
        self.assertEqual(len(repaired["crop_attempts"][name]), 2)
        self.assertTrue((self.project / old_attempts[name][0]["path"]).is_file())

    def test_tight_roi_is_inspectable_and_corrected_roi_retries_without_generation(self):
        self.prepare()
        _, _, rois = self.record()
        name = production.identity_key(rois[0]["asset_id"], rois[0]["view_id"])
        tight = copy.deepcopy(rois[:1])
        tight[0]["roi"] = [119, 119, 264, 264]
        first = production.crop(self.workspace, "board-001", tight)
        self.assertTrue(first["crop_available"])
        self.assertFalse(first["crop_technical_pass"])
        check = first["crop_results"][0]
        self.assertIn("nonwhite_boundary", {row["code"] for row in check["qualification_failures"]})
        before = copy.deepcopy(first["crops"][name])
        receipt = core.read(self.project / before["path"])
        old_image = self.project / receipt["output"]["path"]
        old_hash = core.file_hash(old_image)
        production.review(self.workspace, "board-001", self.reviews())
        with patch.object(production.board_native, "record", side_effect=AssertionError("Cropping cannot submit/record another generation")):
            fixed = production.crop(self.workspace, "board-001", rois[:1])
        self.assertTrue(fixed["crop_results"][0]["technical_pass"])
        self.assertNotEqual(fixed["crops"][name], before)
        self.assertEqual(core.file_hash(old_image), old_hash)
        self.assertNotIn(name, self.page()["reviews"])
        frozen = copy.deepcopy(self.page()["frozen"])
        again = production.crop(self.workspace, "board-001", rois[:1])
        self.assertEqual(again["crop_attempts"], fixed["crop_attempts"])
        self.assertEqual(self.page()["frozen"], frozen)

    def test_identical_rois_cannot_relabel_one_subject_as_multiple_assets(self):
        self.prepare()
        _, _, rois = self.record()
        for row in rois:
            row["roi"] = list(rois[0]["roi"])
        with self.assertRaisesRegex(ValueError, "identical ROI"):
            production.crop(self.workspace, "board-001", rois)

    def test_final_review_requires_actual_bound_crop_images(self):
        self.prepare()
        _, _, rois = self.record()
        with self.assertRaisesRegex(ValueError, "actual crops"):
            production.review(self.workspace, "board-001", [{"asset_id": row["asset_id"], "view_id": row["view_id"], "role": row["role"]} for row in rois])
        production.crop(self.workspace, "board-001", rois)
        reviews = self.reviews()
        reviews[0]["image"] = self.ref("style.png")
        with self.assertRaisesRegex(ValueError, "exact current crop"):
            production.review(self.workspace, "board-001", reviews)

    def test_failed_view_is_actionable_and_good_siblings_remain_reviewed(self):
        self.prepare()
        _, _, rois = self.record()
        production.crop(self.workspace, "board-001", rois)
        reviews = self.reviews()
        reviews[0].update(verdict="unclear", repair_layer="construction", repair_action="Inspect the underside closure in an explicit repair reference.")
        result = production.review(self.workspace, "board-001", reviews)
        self.assertEqual(len(result["repair_views"]), 1)
        self.assertEqual(result["repair_views"][0]["asset_id"], reviews[0]["asset_id"])
        self.assertFalse(result["complete"])
        old_review = copy.deepcopy(self.page()["review_ref"])
        reviews[0]["verdict"] = "pass"
        repaired = production.review(self.workspace, "board-001", reviews[:1])
        self.assertEqual(repaired["repair_views"], [])
        self.assertTrue(repaired["visual_all_pass"])
        self.assertEqual(len(self.page()["reviews"]), 4)
        self.assertNotEqual(old_review, self.page()["review_ref"])
        self.assertEqual(core.file_hash(self.project / old_review["path"]), old_review["sha256"])
        self.assertEqual(core.read(self.project / old_review["path"])["reviews"][0]["verdict"], "unclear")

    def test_editing_mutable_review_state_cannot_overrule_real_failure_evidence(self):
        self.prepare()
        _, _, rois = self.record()
        production.crop(self.workspace, "board-001", rois)
        reviews = self.reviews(verdict="fail")
        production.review(self.workspace, "board-001", reviews)
        page_path = self.workspace / "pages/board-001/state.json"
        page = core.read(page_path)
        for row in page["reviews"].values():
            row["verdict"] = "pass"
        core.write(page_path, page)
        with self.assertRaisesRegex(ValueError, "actual recorded review evidence"):
            production.status(self.workspace)

    def workbuddy_ready(self):
        self.binding.update(host="workbuddy", tool="DeferExecuteTool", image_arguments=["image1", "image2", "image3"],
                            arguments_container="params", envelope_arguments={"toolName": "ImageGen"})
        self.binding.pop("image_argument", None)
        self.binding["fixed_arguments"] = {}
        self.save_inputs()
        self.prepare()
        production.claim(self.workspace, "board-001")
        info = production.inspect_claim(self.workspace, "board-001")
        image, _ = self.make_output()
        result = {"type": "image_gen_tool_result", "status": "completed", "images": [{"localPath": str(image)}]}
        return info, image, result

    def guard_pre(self, info, source="fixture-call-1"):
        path = self.workspace / "host-guard/claims" / (hashlib.sha256(info["claim"]["id"].encode()).hexdigest() + ".json")
        core.write(path, {"schema": 1, "kind": "workbuddy-board-hook-claim", "page_id": "board-001",
                         "claim_id": info["claim"]["id"], "claim_sha256": info["claim_file"]["sha256"],
                         "dispatch_sha256": info["dispatch"]["sha256"], "source_ref": source,
                         "event": {"tool_use_id": source, "tool_name": info["tool"], "tool_input": info["tool_arguments"],
                                   "session_id": "synthetic-session", "cwd": str(self.project)}})
        inner_path = self.workspace / "host-guard/execution-claims" / path.name
        core.write(inner_path, {"schema": 1, "kind": "workbuddy-board-hook-execution-claim", "page_id": "board-001",
                               "claim_id": info["claim"]["id"], "claim_sha256": info["claim_file"]["sha256"],
                               "dispatch_sha256": info["dispatch"]["sha256"], "source_ref": source,
                               "outer_pre_sha256": core.file_hash(path),
                               "event": {"hook_event_name": "PreToolUse", "tool_use_id": source, "tool_name": "ImageGen",
                                         "tool_input": info["tool_arguments"]["params"], "session_id": "synthetic-session",
                                         "cwd": str(self.project)}})
        return path

    def guard_post(self, info, pre, result, source="fixture-call-1"):
        path = self.workspace / "host-guard/results" / (hashlib.sha256(source.encode()).hexdigest() + ".json")
        core.write(path, {"schema": 1, "kind": "workbuddy-board-hook-result", "page_id": "board-001",
                         "source_ref": source, "pre_event_sha256": core.file_hash(pre),
                         "event": {"tool_use_id": source, "tool_name": info["tool"], "tool_input": info["tool_arguments"],
                                   "session_id": "synthetic-session", "tool_response": result}})
        return path

    def test_guard_pre_pins_the_original_host_call_id(self):
        info, image, result = self.workbuddy_ready()
        self.guard_pre(info)
        with self.assertRaisesRegex(ValueError, "Guard Pre original host call ID"):
            production.record(self.workspace, "board-001", info["tool_arguments"], image,
                              source_ref="different-call-2", tool_result=result)
        self.assertEqual(production.inspect_claim(self.workspace, "board-001")["claim"]["status"], "pending")

    def test_guard_actual_failure_cannot_be_washed_with_a_fake_completed_result(self):
        info, image, result = self.workbuddy_ready()
        pre = self.guard_pre(info)
        self.guard_post(info, pre, {"error": "actual tool failure", "status": "failed"})
        with self.assertRaisesRegex(ValueError, "Guard Post actual arguments/result"):
            production.record(self.workspace, "board-001", info["tool_arguments"], image,
                              source_ref="fixture-call-1", tool_result=result)

    def test_late_guard_post_conflict_blocks_an_already_recorded_page(self):
        info, image, result = self.workbuddy_ready()
        pre = self.guard_pre(info)
        production.record(self.workspace, "board-001", info["tool_arguments"], image,
                          source_ref="fixture-call-1", tool_result=result)
        self.guard_post(info, pre, {"error": "late actual failure", "status": "failed"})
        with self.assertRaisesRegex(ValueError, "Guard Post actual arguments/result"):
            production.status(self.workspace)

    def test_matching_guard_pre_and_post_do_not_claim_cryptographic_host_verification(self):
        info, image, result = self.workbuddy_ready()
        pre = self.guard_pre(info)
        self.guard_post(info, pre, result)
        recorded = production.record(self.workspace, "board-001", info["tool_arguments"], image,
                                     source_ref="fixture-call-1", tool_result=result)
        self.assertTrue(recorded["invocation_recorded"])
        self.assertFalse(recorded["host_trace_verified"])

    def test_deferred_wrapper_without_inner_execution_cannot_be_recorded(self):
        info, image, result = self.workbuddy_ready()
        pre = self.guard_pre(info)
        (self.workspace / "host-guard/execution-claims" / pre.name).unlink()
        with self.assertRaisesRegex(ValueError, "original inner Pre"):
            production.record(self.workspace, "board-001", info["tool_arguments"], image,
                              source_ref="fixture-call-1", tool_result=result)

    def test_deferred_inner_execution_must_keep_exact_session_call_and_params(self):
        info, image, result = self.workbuddy_ready()
        pre = self.guard_pre(info)
        path = self.workspace / "host-guard/execution-claims" / pre.name
        original = core.read(path)
        for field, value in (("session_id", "another-session"), ("tool_use_id", "another-call"),
                             ("call_id", "different-from-tool-use-id"), ("generation_id", "another-generation"),
                             ("tool_input", {"prompt": "different"}), ("cwd", "/unrelated-project"),
                             ("cwd", str(self.project / "another-subdirectory"))):
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                changed["event"][field] = value
                core.write(path, changed)
                with self.assertRaisesRegex(ValueError, "inner original event"):
                    production.record(self.workspace, "board-001", info["tool_arguments"], image,
                                      source_ref="fixture-call-1", tool_result=result)

    def test_workbuddy_raw_credit_and_json_content_bind_the_same_business_result(self):
        info, image, result = self.workbuddy_ready()
        pre = self.guard_pre(info)
        self.guard_post(info, pre, dict(result, credit=5))
        wrapped = {"type": "text", "text": json.dumps(result)}
        recorded = production.record(self.workspace, "board-001", info["tool_arguments"], image,
                                     source_ref="fixture-call-1", tool_result=wrapped)
        self.assertTrue(recorded["invocation_recorded"])
        self.assertEqual(core.read(self.workspace / "pages/board-001/completion.json")["tool_result"], wrapped)

    def test_workbuddy_transport_does_not_discard_error_or_changed_result(self):
        info, image, result = self.workbuddy_ready()
        for altered in (dict(result, status="failed"), dict(result, images=[{"localPath": "/different.png"}]),
                        {"error": "actual failure", "content": json.dumps(result)},
                        {"status": "failed", "content": json.dumps(result)},
                        {"is_error": True, "content": json.dumps(result)},
                        {"success": False, "content": json.dumps(result)},
                        {"ok": False, "content": json.dumps(result)}):
            with self.subTest(value=altered):
                self.assertFalse(production._workbuddy_same_result(altered, result))
                with self.assertRaises(ValueError):
                    production._workbuddy_result(altered, core.file_hash(image))
        with self.assertRaises(ValueError):
            production._workbuddy_result(dict(result, isError=True), core.file_hash(image))
        self.assertFalse(production._workbuddy_same_result(dict(result, vendor_field=True), dict(result, vendor_field=1)))

    def test_all_pages_need_crops_and_review_before_scope_completion(self):
        self.prepare()
        for page_id in ("board-001", "board-002"):
            _, _, rois = self.record(page_id)
            production.crop(self.workspace, page_id, rois)
            production.review(self.workspace, page_id, self.reviews(page_id))
            if page_id == "board-001":
                self.assertFalse(production.status(self.workspace)["complete"])
        status = production.status(self.workspace)
        self.assertTrue(status["complete"])
        self.assertFalse(status["host_trace_verified"])
        self.assertFalse(status["human_acceptance"])
        self.assertFalse(status["identity_continuity_verified"])

    def test_production_identity_master_requires_a_passing_source_review(self):
        role = {"role": "identity_master", "asset_id": "prop-0", "source_view_id": "front", "target_view_ids": ["three_quarter"]}
        self.spec["image_roles"] = [role]
        self.save_inputs()
        with self.assertRaisesRegex(ValueError, "source_review"):
            self.prepare()

    def add_master(self, verdict="pass"):
        Image.new("RGB", (256, 256), "green").save(self.project / "master.png")
        review = {"image_sha256": core.file_hash(self.project / "master.png"), "asset_id": "prop-0", "view_id": "front",
                  "verdict": verdict, "observation": "Synthetic source has a complete closed silhouette and an identifiable shape.",
                  "source_ref": "synthetic image inspection fixture, no actual host acceptance"}
        core.write(self.project / "master-review.json", review)
        self.spec["images"].append(self.ref("master.png"))
        self.spec["image_roles"].append({"role": "identity_master", "asset_id": "prop-0", "source_view_id": "front",
                                           "target_view_ids": ["three_quarter"], "source_review": self.ref("master-review.json")})
        self.spec["capabilities"]["max_references"] = 3
        self.binding["max_references"] = 3
        self.save_inputs()

    def test_passing_identity_source_is_bound_and_its_review_cannot_drift(self):
        self.add_master()
        result = self.prepare()
        self.assertTrue(result["pages"][0]["identity_master_bound"])
        review = core.read(self.project / "master-review.json")
        review["verdict"] = "fail"
        core.write(self.project / "master-review.json", review)
        with self.assertRaisesRegex(ValueError, "Frozen"):
            production.claim(self.workspace, "board-001")

    def test_failed_identity_source_cannot_be_relabelled_as_a_master(self):
        self.add_master(verdict="fail")
        with self.assertRaisesRegex(ValueError, "pass|review"):
            self.prepare()
        self.assertFalse(production.status(self.workspace)["complete"])

    def test_split_views_without_qualified_identity_inputs_are_blocked(self):
        self.spec["plan"]["views"][1]["asset_id"] = "prop-0"
        self.spec["plan"]["views"][1]["view_id"] = "left"
        self.spec["plan"]["views"][0]["requires_single"] = True
        self.spec["plan"]["views"][1]["requires_single"] = True
        self.spec["objects"][1].update(asset_id="prop-0", view_id="left")
        self.source["asset_views"][1].update(asset_id="prop-0", view_id="left")
        self.request["scope"]["asset_views"][1].update(asset_id="prop-0", view_id="left")
        self.save_inputs()
        with self.assertRaisesRegex(ValueError, "Split multiview"):
            self.prepare()
        result = production.status(self.workspace)
        self.assertFalse(result["complete"])
        self.assertEqual(len(result["unbound_identity_views"]), 2)

    def test_same_page_shared_design_is_explicitly_exploration_not_verified_identity(self):
        self.spec["plan"]["views"][1].update(asset_id="prop-0", view_id="left")
        self.spec["objects"][1].update(asset_id="prop-0", view_id="left")
        self.source["asset_views"][1].update(asset_id="prop-0", view_id="left")
        self.request["scope"]["asset_views"][1].update(asset_id="prop-0", view_id="left")
        self.save_inputs()
        result = self.prepare()
        self.assertEqual(result["pages"][0]["design_mode"], "joint_design_exploration")
        self.assertFalse(result["identity_continuity_verified"])

    def prepare_shared_design(self):
        self.spec["plan"]["views"][1].update(asset_id="prop-0", view_id="left")
        self.spec["objects"][1].update(asset_id="prop-0", view_id="left")
        self.source["asset_views"][1].update(asset_id="prop-0", view_id="left")
        self.request["scope"]["asset_views"][1].update(asset_id="prop-0", view_id="left")
        self.save_inputs()
        result = self.prepare()
        for page in result["pages"]:
            page_id = page["id"]
            _, _, rois = self.record(page_id)
            production.crop(self.workspace, page_id, rois)
            production.review(self.workspace, page_id, self.reviews(page_id))
        return production.status(self.workspace)

    def cross_review(self, status, verdict="pass"):
        item = status["cross_view_reviews"][0]
        return {"asset_id": item["asset_id"], "verdict": verdict,
                "images": copy.deepcopy(item["required_images"]),
                "observation": "Synthetic views were compared as one designed object; their part count and authored markings agree.",
                "source_ref": "synthetic explicit cross-view observation; not a 3D proof"}

    def test_per_view_passes_cannot_complete_multiview_without_a_comparison(self):
        status = self.prepare_shared_design()
        self.assertFalse(status["complete"])
        first = status["pages"][0]
        self.assertTrue(first["visual_all_pass"])
        self.assertFalse(first["cross_view_review_pass"])
        self.assertEqual(status["cross_view_reviews"][0]["verdict"], "missing")
        review = self.cross_review(status)
        result = production.review(self.workspace, "board-001", {"cross_view_reviews": [review]})
        self.assertTrue(result["complete"])
        self.assertTrue(production.status(self.workspace)["complete"])
        self.assertFalse(result["identity_continuity_verified"])

    def test_recrop_invalidates_old_cross_view_review_without_losing_its_evidence(self):
        status = self.prepare_shared_design()
        production.review(self.workspace, "board-001", {"cross_view_reviews": [self.cross_review(status)]})
        old_cross = copy.deepcopy(self.page()["cross_view_reviews"]["prop-0"])
        old_ref = next(ref for ref in self.page()["crops"].values()
                       if core.read(self.project / ref["path"])["recipe"]["asset_id"] == "prop-0")
        recipe = core.read(self.project / old_ref["path"])["recipe"]
        observed = {key: recipe[key] for key in ("asset_id", "view_id", "role", "roi")}
        observed["roi"] = [recipe["roi"][0] + 2, *recipe["roi"][1:]]
        result = production.crop(self.workspace, "board-001", [observed])
        self.assertFalse(result["complete"])
        self.assertEqual(result["cross_view_reviews"][0]["verdict"], "stale")
        self.assertIn("current crop changed", result["cross_view_reviews"][0]["next_action"])
        self.assertEqual(core.file_hash(self.project / old_cross["path"]), old_cross["sha256"])
        refreshed = [row for row in self.reviews()
                     if (row["asset_id"], row["view_id"]) == (observed["asset_id"], observed["view_id"])]
        production.review(self.workspace, "board-001", refreshed)
        current = production.status(self.workspace)
        production.review(self.workspace, "board-001", {"cross_view_reviews": [self.cross_review(current)]})
        self.assertTrue(production.status(self.workspace)["complete"])

    def test_cross_view_pass_cannot_accept_a_technically_failed_inspection_crop(self):
        status = self.prepare_shared_design()
        slot = self.page()["slots"][0]
        production.crop(self.workspace, "board-001", [{"asset_id": slot["asset_id"], "view_id": slot["view_id"],
                                                       "role": slot["role"], "roi": [119, 119, 264, 264]}])
        status = production.status(self.workspace)
        self.assertFalse(status["cross_view_reviews"][0]["technical_ready"])
        with self.assertRaisesRegex(ValueError, "frozen crop technical checks"):
            production.review(self.workspace, "board-001", {"cross_view_reviews": [self.cross_review(status)]})

    def test_cross_view_failure_keeps_individual_good_views_and_names_the_gap(self):
        status = self.prepare_shared_design()
        review = self.cross_review(status, verdict="unclear")
        review["observation"] = "Synthetic side view differs in one identifying mark; compare it to the front before repairing only that view."
        result = production.review(self.workspace, "board-001", {"cross_view_reviews": [review]})
        self.assertTrue(result["visual_all_pass"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["cross_view_reviews"][0]["verdict"], "unclear")
        self.assertIn("locate the inconsistent view", result["cross_view_reviews"][0]["next_action"])
        self.assertEqual(len(self.page()["reviews"]), 4)

    def test_cross_view_review_cannot_compare_missing_or_stale_crop_hashes(self):
        status = self.prepare_shared_design()
        review = self.cross_review(status)
        review["images"][0]["image"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "every exact current crop"):
            production.review(self.workspace, "board-001", {"cross_view_reviews": [review]})
        self.assertFalse(production.status(self.workspace)["complete"])

    def test_initial_plan_cannot_lower_upstream_minimum_subject_pixels(self):
        self.spec["plan"]["views"][0]["min_subject_long_edge_px"] = 64
        self.save_inputs()
        with self.assertRaisesRegex(ValueError, "lowers an upstream"):
            self.prepare()

    def test_workbuddy_record_binds_real_returned_image_and_unknown_stays_pending(self):
        self.binding.update(host="workbuddy", tool="DeferExecuteTool", image_arguments=["image1", "image2", "image3"],
                            arguments_container="params", envelope_arguments={"toolName": "ImageGen"})
        self.binding.pop("image_argument")
        self.binding["fixed_arguments"] = {}
        self.save_inputs()
        self.prepare()
        production.claim(self.workspace, "board-001")
        info = production.inspect_claim(self.workspace, "board-001")
        image, _ = self.make_output()
        unknown = {"type": "image_gen_tool_result", "status": "unknown", "images": []}
        with self.assertRaisesRegex(ValueError, "stay pending"):
            production.record(self.workspace, "board-001", info["tool_arguments"], image, source_ref="call-real", tool_result=unknown)
        self.assertEqual(production.inspect_claim(self.workspace, "board-001")["claim"]["status"], "pending")
        actual = {"type": "image_gen_tool_result", "status": "completed", "images": [{"localPath": str(self.project / "style.png")}]}
        with self.assertRaisesRegex(ValueError, "output bytes"):
            production.record(self.workspace, "board-001", info["tool_arguments"], image, source_ref="call-real", tool_result=actual)
        actual["images"][0]["localPath"] = str(image)
        result = production.record(self.workspace, "board-001", info["tool_arguments"], image, source_ref="call-real", tool_result=actual)
        self.assertTrue(result["invocation_recorded"])

    def test_cli_routes_production_and_preserves_legacy_help(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = cli.main(["boards", "production", "prepare", "--project", str(self.project),
                               "--workspace", "art/production", "--file", "production-request.json"])
        self.assertEqual(result, 0)
        self.assertIn('"preparation_status": "ready"', output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as stopped:
                cli.main(["boards", "--help"])
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn("record-native", output.getvalue())
        self.assertIn("production", output.getvalue())


if __name__ == "__main__":
    unittest.main()
