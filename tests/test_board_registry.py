"""Single-source board entry and recovery contracts; offline synthetic inputs."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art/runtime"))
from greybox import board_registry as registry, board_production as production, cli, core
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "Optional Pillow unavailable")
class BoardRegistry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.workspace = self.project / "art" / "boards"
        self.path = self.project / "registry.json"
        Image.new("RGB", (32, 32), "blue").save(self.project / "style.png")
        self.spec = {"schema": 1, "kind": "reference-board-registry", "authority": "registry",
                     "source_ref": "Synthetic scoped input, not approval or provider qualification",
                     "host_session_id": "synthetic-session", "channel_size": [768, 768],
                     "size_source_ref": "Synthetic native canvas for offline tests",
                     "requirements": {"min_subject_long_edge_px": 128, "min_subject_short_edge_px": 128,
                                      "source_ref": "Synthetic subject pixel basis"},
                     "images": [self.ref("style.png")], "image_roles": [{"role": "style"}],
                     "capabilities": {"edit": True, "max_references": 2, "layout_guide": True,
                                      "source_ref": "Synthetic native edit capability"},
                     "assets": [self.asset(i) for i in range(20)]}

    def ref(self, name):
        return {"path": name, "sha256": core.file_hash(self.project / name)}

    def asset(self, number, views=None):
        return {"asset_id": "prop-" + str(number), "category": "prop",
                "function": "A freestanding museum object for a rigid display.",
                "appearance": "A rounded solid blue object with a distinct shallow relief.",
                "structure": "One closed volume with an integral flat underside.",
                "modeling_contract": {"category": "prop", "use": "static"},
                "views": views or [{"view_id": "three_quarter", "role": "three_quarter", "projected_aspect": 1.0}]}

    def start(self):
        core.write(self.path, self.spec)
        return registry.start(self.spec, self.project, self.workspace, registry_path=self.path)

    def binding(self, maximum=2):
        value = {"schema": 1, "kind": "reference-board-native-binding", "host": "codex", "tool": "image_gen.imagegen",
                 "source_ref": "Synthetic tool schema", "input_transport": "local_paths", "max_references": maximum,
                 "image_argument": "referenced_image_paths", "fixed_arguments": {"transparent_background": False}}
        core.write(self.project / "binding.json", value)
        return self.ref("binding.json")

    def external_source(self):
        rows, _ = registry.flatten(self.spec)
        core.write(self.project / "source.json", {"schema": 1, "kind": "reference-board-scope", "asset_views": rows})
        self.spec.pop("authority")
        self.spec["source"] = self.ref("source.json")

    def test_twenty_assets_compile_to_complete_pages_without_four_handwritten_lists(self):
        result = self.start()
        self.assertEqual(result["asset_count"], 20)
        self.assertEqual(result["view_count"], 20)
        self.assertEqual([len(job["slots"]) for job in result["jobs"]], [4, 4, 4, 4, 4])
        self.assertEqual([slot["asset_id"] for job in result["jobs"] for slot in job["slots"]],
                         ["prop-" + str(i) for i in range(20)])
        self.assertTrue(all(job["next_action"] == "map" for job in result["jobs"]))
        self.assertTrue(all(Path(job["prompt_file"]).is_file() for job in result["jobs"]))
        self.assertFalse(any(self.workspace.glob("pages/*/claim.json")))
        self.assertFalse(result["submission"])
        self.assertFalse(result["human_acceptance"])
        self.assertIn("coherent_asset_groups", core.read(registry._inputs(self.workspace) / "prepare.json")["plan"])

    def test_missing_or_duplicate_view_is_rejected_before_creating_work(self):
        self.spec["assets"][0]["views"] *= 2
        with self.assertRaisesRegex(core.WorkflowError, "repeats an asset/view"):
            self.start()
        self.assertFalse(self.workspace.exists())
        self.assertFalse(registry._inputs(self.workspace).exists())

    def test_source_cannot_be_silently_replaced_by_a_self_declared_scope(self):
        self.spec.pop("authority")
        with self.assertRaisesRegex(core.WorkflowError, "authority:registry"):
            self.start()
        self.assertFalse(self.workspace.exists())

    def test_stale_upstream_hash_blocks_before_compilation(self):
        self.external_source()
        path = self.project / "source.json"
        source = core.read(path)
        source["asset_views"].pop()
        core.write(path, source)
        with self.assertRaisesRegex(core.WorkflowError, "changed or hash is wrong"):
            self.start()
        self.assertFalse(registry._inputs(self.workspace).exists())

    def test_upstream_omission_or_orientation_change_is_rejected(self):
        self.external_source()
        self.spec["assets"].pop()
        with self.assertRaisesRegex(core.WorkflowError, "exactly the upstream"):
            self.start()
        self.assertFalse(self.workspace.exists())

    def test_unsourced_forced_singles_do_not_become_a_legal_batch(self):
        for asset in self.spec["assets"]:
            asset["views"][0]["requires_single"] = True
        with self.assertRaisesRegex(core.WorkflowError, "sourced single_exception"):
            self.start()
        self.assertFalse(self.workspace.exists())

    def test_sourced_single_keeps_its_reason_in_derived_input(self):
        view = self.spec["assets"][0]["views"][0]
        view.update(requires_single=True, single_exception={"source_ref": "Synthetic approved detail decision",
                                                          "reason": "This tested isolated specimen needs a dedicated source image."})
        result = self.start()
        saved = core.read(registry._inputs(self.workspace) / "scope.json")["asset_views"][0]
        self.assertEqual(saved["single_exception"], view["single_exception"])
        self.assertEqual(len(result["jobs"][0]["slots"]), 1)

    def test_same_asset_views_stay_together_when_they_fit(self):
        views = [{"view_id": role, "role": role, "projected_aspect": 1.0} for role in ("front", "left", "back")]
        self.spec["assets"] = [self.asset(0, copy.deepcopy(views)), self.asset(1, copy.deepcopy(views))]
        result = self.start()
        self.assertEqual([len(job["slots"]) for job in result["jobs"]], [3, 3])
        self.assertEqual([{slot["asset_id"] for slot in job["slots"]} for job in result["jobs"]],
                         [{"prop-0"}, {"prop-1"}])
        self.assertFalse(any(self.workspace.glob("pages/*/claim.json")))

    def test_multiview_that_requires_split_stages_a_master_without_omitting_views(self):
        roles = ["front", "left", "back", "right", "top", "bottom"]
        self.spec["assets"] = [self.asset(0, [{"view_id": role, "role": role, "projected_aspect": 1.0} for role in roles])]
        result = self.start()
        self.assertEqual(result["view_count"], 1)
        self.assertEqual(result["full_scope_view_count"], 6)
        self.assertEqual(len(result["deferred_views"]), 5)
        self.assertFalse(result["complete"])
        waiting = registry.advance(self.workspace)
        self.assertFalse(waiting["advanced"])
        self.assertEqual(waiting["next_action"]["action"], "wait_for_qualified_identity_master")
        self.assertFalse(any(self.workspace.glob("pages/*/claim.json")))
        self.assertEqual(core.read(self.workspace / "production.json")["preparation_status"], "ready")

    def test_claimed_start_replay_preserves_original_call(self):
        self.spec["native_binding"] = self.binding()
        first = self.start()
        self.assertEqual(first["jobs"][0]["next_action"], "claim_then_invoke_exact_page")
        production.claim(self.workspace, "board-001")
        claim = self.workspace / "pages" / "board-001" / "claim.json"
        original = claim.read_bytes()
        second = registry.start(self.spec, self.project, self.workspace, registry_path=self.path)
        self.assertEqual(second["jobs"][0]["next_action"], "recover_original_call")
        self.assertEqual(claim.read_bytes(), original)
        self.assertTrue(all(job["claim_status"] == "unclaimed" for job in second["jobs"][1:]))

    def test_changed_registry_cannot_overwrite_existing_compilation(self):
        self.start()
        previous = (registry._inputs(self.workspace) / "prepare.json").read_bytes()
        self.spec["assets"][0]["appearance"] = "A newly designed object with a square silhouette."
        with self.assertRaisesRegex(core.WorkflowError, "new explicit workspace revision"):
            self.start()
        self.assertEqual((registry._inputs(self.workspace) / "prepare.json").read_bytes(), previous)

    def test_changed_real_upstream_is_visible_to_production_status(self):
        self.external_source()
        self.start()
        source = self.project / "source.json"
        value = core.read(source)
        value["asset_views"].pop()
        core.write(source, value)
        with self.assertRaisesRegex(core.WorkflowError, "changed"):
            production.status(self.workspace)
        with self.assertRaisesRegex(core.WorkflowError, "changed"):
            registry.next_jobs(self.workspace)

    def test_changing_upstream_pixel_minimum_needs_its_source_and_cannot_lower(self):
        self.external_source()
        self.spec.pop("requirements")
        for asset in self.spec["assets"]:
            asset["views"][0].update(min_subject_long_edge_px=127, min_subject_short_edge_px=127)
        with self.assertRaisesRegex(core.WorkflowError, "requirements_source_ref"):
            self.start()
        self.spec["assets"][0]["views"][0]["requirements_source_ref"] = "Synthetic changed quality proposal"
        with self.assertRaisesRegex(core.WorkflowError, "may not lower"):
            self.start()

    def test_cli_dispatches_the_normal_short_entry(self):
        core.write(self.path, self.spec)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(["boards", "start", "--file", str(self.path), "--project", str(self.project), "--workspace", str(self.workspace)])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["view_count"], 20)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["boards", "next", "--workspace", str(self.workspace)]), 0)
        self.assertEqual(json.loads(output.getvalue())["job_count"], result["job_count"])

    def staged_spec(self, styles=1):
        self.spec["channel_size"] = [1536, 1024]
        self.spec["requirements"].update(min_subject_long_edge_px=340, min_subject_short_edge_px=280)
        views = [{"view_id": role, "role": role, "projected_aspect": 1.0} for role in ("front", "left", "back")]
        self.spec["assets"] = [self.asset(0, views), self.asset(1)]
        self.spec["capabilities"]["max_references"] = 3
        self.spec["native_binding"] = self.binding(3)
        if styles == 2:
            Image.new("RGB", (32, 32), "green").save(self.project / "style-two.png")
            self.spec["images"].append(self.ref("style-two.png"))
            self.spec["image_roles"].append({"role": "style"})

    def finish_stage(self, workspace, *, small=False, review=True):
        state = core.read(workspace / "production.json")
        for page_id in state["pages"]:
            info = production.claim(workspace, page_id)
            page = core.read(workspace / "pages" / page_id / "state.json")
            image = Image.new("RGB", tuple(self.spec["channel_size"]), "white")
            drawing = ImageDraw.Draw(image)
            rois = []
            for slot in page["slots"]:
                left, top, right, bottom = slot["planned_region"]
                size = 60 if small else max(slot["requirements"]["min_subject_long_edge_px"], slot["requirements"]["min_subject_short_edge_px"]) + 20
                x, y = (left + right - size) // 2, (top + bottom - size) // 2
                drawing.rectangle([x, y, x + size - 1, y + size - 1], fill="purple")
                rois.append({"asset_id": slot["asset_id"], "view_id": slot["view_id"], "role": slot["role"],
                             "roi": [x - 10, y - 10, x + size + 10, y + size + 10]})
            path = self.project / (workspace.name + "-" + page_id + "-synthetic.png")
            image.save(path)
            production.record(workspace, page_id, info["tool_arguments"], path,
                              source_ref="synthetic-call-" + workspace.name + "-" + page_id,
                              tool_result={"synthetic": True, "path": str(path)})
            production.crop(workspace, page_id, rois)
            if review:
                page = core.read(workspace / "pages" / page_id / "state.json")
                observations = []
                for slot in page["slots"]:
                    receipt = core.read(self.project / page["crops"][production.identity_key(slot["asset_id"], slot["view_id"])]["path"])
                    observations.append({"asset_id": slot["asset_id"], "view_id": slot["view_id"], "role": slot["role"],
                                         "image": receipt["output"], "verdict": "fail" if small else "pass",
                                         "observation": "Synthetic visible purple specimen is fully contained; no artistic acceptance is inferred.",
                                         "inspection_source_ref": "Synthetic pixel observation, no human acceptance"})
                production.review(workspace, page_id, observations)
        if review and not small:
            state = core.read(workspace / "production.json")
            for comparison in production._cross_view_status(self.project, state):
                production.review(workspace, comparison["owner_page"], {"cross_view_reviews": [
                    {"asset_id": comparison["asset_id"], "images": comparison["required_images"], "verdict": "pass",
                     "observation": "Synthetic views share the test shape; this is protocol validation only.",
                     "source_ref": "Synthetic comparison of generated fixture pixels"}]})

    def test_master_stage_completion_does_not_claim_complete_original_scope(self):
        self.staged_spec()
        result = self.start()
        self.assertEqual(result["view_count"], 2)
        self.assertEqual(result["full_scope_view_count"], 4)
        self.assertEqual(result["master_dependencies"][0]["master_view_id"], "front")
        self.finish_stage(self.workspace)
        result = registry.next_jobs(self.workspace)
        self.assertTrue(result["stage_complete"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["next_action"]["action"], "advance_qualified_masters")

    def test_explicit_master_view_is_selected_without_relabeling_the_camera(self):
        self.staged_spec()
        self.spec["assets"][0]["master_view_id"] = "back"
        result = self.start()
        selected = [slot for job in result["jobs"] for slot in job["slots"] if slot["asset_id"] == "prop-0"]
        self.assertEqual([(row["view_id"], row["role"]) for row in selected], [("back", "back")])
        self.assertEqual({row["view_id"] for row in result["deferred_views"]}, {"front", "left"})
        self.assertIn("master_view_id", result["master_dependencies"][0]["selection_basis"])

    def test_cli_advance_reports_waiting_views_without_generating_or_claiming(self):
        self.staged_spec()
        self.start()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(["boards", "advance", "--workspace", str(self.workspace)])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertFalse(result["advanced"])
        self.assertEqual(result["waiting_for_masters"][0]["master_view_id"], "front")
        self.assertFalse(result["submission"])
        self.assertFalse(any(self.workspace.glob("pages/*/claim.json")))

    def test_advance_uses_real_master_crop_then_requires_complete_asset_comparison(self):
        self.staged_spec()
        self.start()
        self.finish_stage(self.workspace)
        result = registry.advance(self.workspace)
        child = Path(result["created_workspace"])
        self.assertEqual(registry.workflow_root(child), self.workspace)
        self.assertEqual(registry.workflow_workspaces(child), [self.workspace, child])
        self.assertEqual(result["view_count"], 2)
        self.assertEqual({slot["asset_id"] for job in result["jobs"] for slot in job["slots"]}, {"prop-0"})
        self.assertEqual({slot["view_id"] for job in result["jobs"] for slot in job["slots"]}, {"left", "back"})
        child_registry_path = self.project / result["child_registry"]["path"]
        child_registry = core.read(child_registry_path)
        master = next(role for role in child_registry["image_roles"] if role["role"] == "identity_master")
        review = core.read(self.project / master["source_review"]["path"])
        self.assertIn("board_crop_receipt", review)
        self.assertEqual(review["view_id"], "front")
        self.assertFalse(result["complete"])
        self.finish_stage(child)
        current = registry.next_jobs(child)
        self.assertTrue(current["stage_complete"])
        self.assertFalse(current["complete"])
        comparison = current["workflow_cross_view_reviews"][0]
        self.assertEqual([row["view_id"] for row in comparison["required_images"]], ["front", "left", "back"])
        bad = {"asset_id": "prop-0", "images": comparison["required_images"][1:], "verdict": "pass",
               "observation": "Synthetic comparison excluding the source is intentionally incomplete.", "source_ref": "Synthetic protocol check"}
        with self.assertRaisesRegex(core.WorkflowError, "every exact current source and target"):
            registry.compare(child, [bad])
        finished = registry.compare(child, [dict(bad, images=comparison["required_images"])])
        self.assertTrue(finished["complete"])
        self.assertFalse(finished["human_acceptance"])

    def test_two_styles_and_one_master_preserve_inputs_and_omit_only_optional_guide(self):
        self.staged_spec(styles=2)
        self.start()
        self.finish_stage(self.workspace)
        result = registry.advance(self.workspace)
        child = core.read(self.project / result["child_registry"]["path"])
        self.assertEqual([row["sha256"] for row in child["images"][:2]], [row["sha256"] for row in self.spec["images"]])
        self.assertEqual(len(child["images"]), 3)
        self.assertFalse(child["capabilities"]["layout_guide"])
        self.assertEqual(child["stage_adjustments"][-1]["kind"], "omit_optional_layout_guide")
        self.assertTrue(all(len(job["images"]) == 3 for job in result["jobs"]))
        # A normal later entry with an already qualified master takes the
        # no-dependency branch, which must use the same adjusted capability as
        # its preflight rather than silently putting the guide back.
        child["capabilities"]["layout_guide"] = True
        path = self.project / "existing-master-registry.json"
        core.write(path, child)
        fresh = registry.start(child, self.project, self.project / "existing-master-run", registry_path=path)
        self.assertTrue(all(len(job["images"]) == 3 for job in fresh["jobs"]))
        self.assertFalse(core.read(registry._inputs(self.project / "existing-master-run") / "prepare.json")["capabilities"]["layout_guide"])

    def test_advance_waits_for_exact_visual_pass_and_technical_qualification(self):
        self.staged_spec()
        self.start()
        self.finish_stage(self.workspace, small=True)
        result = registry.advance(self.workspace)
        self.assertFalse(result["advanced"])
        self.assertEqual(registry.workflow_workspaces(self.workspace), [self.workspace])
        self.assertTrue(result["waiting_for_masters"][0]["next_action"])
        self.assertFalse(registry._child_workspace(self.workspace).exists())

    def test_optional_guide_omission_also_works_without_any_dependency_stage(self):
        self.spec["capabilities"]["max_references"] = 3
        for name, color in (("second-style.png", "green"), ("third-style.png", "red")):
            Image.new("RGB", (32, 32), color).save(self.project / name)
            self.spec["images"].append(self.ref(name))
            self.spec["image_roles"].append({"role": "style"})
        result = self.start()
        self.assertTrue(all(len(job["images"]) == 3 for job in result["jobs"]))
        self.assertFalse(core.read(registry._inputs(self.workspace) / "prepare.json")["capabilities"]["layout_guide"])
        self.assertFalse(registry._lineage_path(self.workspace).exists())

    def test_advance_is_idempotent_and_child_resume_never_creates_another_workflow(self):
        self.staged_spec()
        self.start()
        self.finish_stage(self.workspace)
        before = (self.workspace / "production.json").read_bytes()
        first = registry.advance(self.workspace)
        child = Path(first["created_workspace"])
        production.claim(child, "board-001")
        claim = child / "pages" / "board-001" / "claim.json"
        original = claim.read_bytes()
        second = registry.advance(self.workspace)
        self.assertEqual(second["created_workspace"], str(child))
        self.assertEqual(claim.read_bytes(), original)
        self.assertEqual((self.workspace / "production.json").read_bytes(), before)
        path = self.project / second["child_registry"]["path"]
        resumed = registry.start(core.read(path), self.project, child, registry_path=path)
        self.assertEqual(resumed["workflow_root"], str(self.workspace))
        self.assertEqual(resumed["jobs"][0]["next_action"], "recover_original_call")

    def test_changed_current_master_review_blocks_child_before_more_spending(self):
        self.staged_spec()
        self.start()
        self.finish_stage(self.workspace)
        result = registry.advance(self.workspace)
        child = Path(result["created_workspace"])
        page = core.read(self.workspace / "pages" / "board-001" / "state.json")
        key = production.identity_key("prop-0", "front")
        previous = page["reviews"][key]
        production.review(self.workspace, "board-001", [dict(previous, verdict="fail", observation="The synthetic master review is now explicitly rejected for this test.")])
        with self.assertRaisesRegex(core.WorkflowError, "no longer the current qualified/reviewed source"):
            registry.workflow_workspaces(child)
        self.assertFalse(any(child.glob("pages/*/claim.json")))


if __name__ == "__main__":
    unittest.main()
