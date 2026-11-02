"""Offline H5 contract tests; synthetic receipts are never production evidence."""
from pathlib import Path
import copy
import shutil
import sys
import tempfile
import unittest
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import core, delivery, godot
from workflow_fixtures import make_workflow, png


class NativeFileAdapter:
    """Creates synthetic native-like files; does not execute Godot or a model."""
    def assemble(self, *args, **kwargs):
        return godot.assemble(*args, **kwargs)

    def validate(self, project, artifact, output_dir, **kwargs):
        attempt = uuid.uuid4().hex
        output = Path(output_dir) / attempt
        output.mkdir(parents=True)
        capture = output / "baseline.png"
        capture.write_bytes(png(1))
        manifest = core.read(godot.project_path(project, artifact["manifest"]))
        ids = [s.get("id", s.get("name")) for s in manifest["contract"]["validation"]["steps"] if s.get("expect")]
        native = {"passed": True, "gameplay_verified": True, "passed_check_ids": ids,
                  "attempt_id": attempt, "binding_digest": artifact["binding_digest"],
                  "scene": artifact["entry_scene"], "captures": [capture.name], "errors": [],
                  "synthetic_offline_test_only": True}
        core.write(output / "native-report.json", native)
        (output / "godot.log").write_text("SYNTHETIC OFFLINE TEST ONLY\n")
        result = {**native, "returncode": 0, "native_errors": [], "attempt_dir": str(output),
                  "source_hashes": artifact["sources"], "artifact_hashes": artifact["owned_files"],
                  "evidence": [{"path": str(capture), "sha256": core.file_hash(capture)}]}
        core.write(output / "validation.json", result)
        return result


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gb-h5-test-")
        self.project = Path(self.tmp.name) / "project"
        shutil.copytree(ROOT / "fixtures/godot-free", self.project)
        self.plan = core.read(self.project / "plan.json")
        self.plan["purpose"] = "production"
        self.run = self.project / "art/experiments/h5-test"
        self.adapter = NativeFileAdapter()

    def tearDown(self):
        self.tmp.cleanup()

    def ready(self, purpose=None, mode=None, only_style=None, expansion=False, h4_status=None,
              workflow_selected_styles=None, sample_space_ids=None):
        if purpose is not None:
            self.plan["purpose"] = purpose
        if mode is not None:
            self.plan["contract"]["validation"]["mode"] = mode
        if self.plan["purpose"] != "technical_fixture":
            path, checkpoint = make_workflow(self.project, self.plan, expansion=expansion,
                selected_styles=workflow_selected_styles, sample_space_ids=sample_space_ids)
            if h4_status is not None:
                for stage in checkpoint['stages']:
                    if stage['id'] == 'representative_sample':
                        stage['status'] = h4_status
                if h4_status != 'accepted':
                    # An unfinished H4 belongs to the original sample run,
                    # not an expansion that would require accepted H4 evidence.
                    originals = {}
                    for stage in checkpoint['stages']:
                        if stage['id'] == 'representative_sample':
                            source = next(e for e in stage['evidence'] if e['role'] == 'sample_source_production')
                            originals[stage['scope']] = core.read(core.resolve_input(source['path'], self.project))
                    checkpoint['stages'] = [originals.get(s['scope'], s) if s['id'] == 'production_plan' else s
                                            for s in checkpoint['stages']]
                core.write(path, checkpoint)
            self.plan["workflow"] = {"path": str(path), "sha256": core.file_hash(path),
                "production_scope": "expansion" if expansion and h4_status in (None, 'accepted') else "representative"}
        if self.plan.get("workspace"):
            from greybox import layout
            self.run = layout.run_root(self.project, self.plan, self.run.name)
        core.write(self.project / "plan.json", self.plan)
        core.prepare(self.project / "plan.json", self.project, self.run)
        core.run(self.run, adapter=self.adapter, style=only_style)
        core.validate(self.run, adapter=self.adapter)

    def review_document(self):
        inputs = delivery.review_inputs(self.run)
        evidence = [{k: a[k] for k in ('path', 'sha256')} for a in inputs['artifacts']]
        receipt = {'schema': 1, 'kind': 'pre-handoff-review', 'input_digest': inputs['input_digest'],
            'reviewer': {'agent_id': 'synthetic-reviewer', 'task_id': 'synthetic-review'},
            'source_ref': 'synthetic://offline-review', 'independence': 'independent',
            'coverage': [{'id': c, 'status': 'satisfied', 'note': 'OFFLINE SYNTHETIC ONLY', 'evidence': evidence}
                         for c in inputs['criteria']],
            'examined_images': [{k: a[k] for k in ('path', 'sha256')} for a in inputs['artifacts'] if 'dimensions' in a],
            'findings': [], 'unreviewed': []}
        return {'producer': {'agent_id': 'synthetic-author', 'task_id': 'synthetic-production'}, 'receipt': receipt}

    def accept(self):
        delivery.record_review(self.run, self.review_document())
        proposed = delivery.propose_manifest(self.run)
        return delivery.accept(self.run, "user", "synthetic://h5-actual-message", "SYNTHETIC art, playable and performance accepted", proposed["manifestHash"])

    def test_current_policy_needs_review_before_human_acceptance(self):
        self.ready()
        proposed = delivery.propose_manifest(self.run)
        self.assertFalse(proposed['human_reviewable'])
        with self.assertRaisesRegex(core.WorkflowError, 'independent delivery review'):
            delivery.accept(self.run, 'user', 'synthetic://message', 'accept', proposed['manifestHash'])

    def test_review_mutation_invalidates_acceptance(self):
        self.ready()
        self.accept()
        state = core.read(self.run / 'run.json')
        state['deliveryReview']['receipt']['coverage'][0]['note'] = 'different review'
        core.save_run(self.run, state)
        self.assert_stale()

    def test_final_review_includes_accepted_h4_samples_and_judgments(self):
        self.ready(expansion=True)
        inputs = delivery.review_inputs(self.run)
        self.assertEqual(set(inputs['accepted_sample_digests']), {s['id'] for s in self.plan['styles']})
        for sid in (s['id'] for s in self.plan['styles']):
            records = [a for a in inputs['artifacts'] if a['stage'] == sid + '/representative_sample']
            self.assertTrue(any(a['role'] == 'native_capture' for a in records))
            self.assertTrue(any(a['role'] == 'accepted_sample_judgment' for a in records))
        self.accept()
        image = next(a for a in inputs['artifacts'] if a['stage'].endswith('/representative_sample') and a['role'] == 'native_capture')
        Path(image['path']).write_bytes(png(99))
        self.assert_stale()

    def test_draft_h4_is_not_an_accepted_delivery_baseline(self):
        self.ready(expansion=True, h4_status='draft')
        inputs = delivery.review_inputs(self.run)
        self.assertEqual(inputs['accepted_sample_digests'], {})
        self.assertFalse(any(a['stage'].endswith('/representative_sample') for a in inputs['artifacts']))

    def assert_stale(self):
        self.assertEqual(delivery.acceptance_status(self.run)["status"], "stale")
        self.assertFalse(delivery.acceptance_status(self.run)["accepted"])

    def test_reviewable_run_remains_pending_until_user_decides(self):
        self.ready()
        before = (self.run / "run.json").read_bytes()
        proposed = delivery.propose_manifest(self.run)
        self.assertTrue(proposed["ok"])
        self.assertEqual(proposed["acceptance"]["status"], "pending")
        self.assertEqual(before, (self.run / "run.json").read_bytes())
        self.assertEqual(len(proposed["manifest"]["styles"]), 2)
        self.assertEqual(proposed["manifest"]["kind"], "greybox-playable-art-delivery")
        self.assertEqual(len(proposed["manifest"]["styles"][0]["native_reports"]), 3)

    def test_actual_h5_record_is_persisted_exactly(self):
        self.ready()
        result = self.accept()
        self.assertEqual(result["status"], "current")
        state = core.read(self.run / "run.json")
        receipt = state["deliveryAcceptance"]
        self.assertEqual(receipt["source_ref"], "synthetic://h5-actual-message")
        self.assertEqual(receipt["note"], "SYNTHETIC art, playable and performance accepted")
        self.assertEqual(core.digest(receipt["manifest"]), receipt["manifestHash"])

    def test_no_agent_or_bare_acceptance(self):
        self.ready()
        h = delivery.propose_manifest(self.run)["manifestHash"]
        for actor, source, note, value in [("agent", "message", "accept", h), ("user", "", "accept", h),
                                          ("user", "message", "", h), ("user", "message", "accept", "accepted"),
                                          ("user", "message", True, h)]:
            with self.subTest(actor=actor, source=source, note=note, value=value):
                with self.assertRaises(core.WorkflowError):
                    delivery.accept(self.run, actor, source, note, value)

    def test_fixture_and_art_proxy_cannot_be_playable_delivery(self):
        for purpose in ("technical_fixture", "art_proxy"):
            with self.subTest(purpose=purpose):
                self.ready(purpose=purpose)
                with self.assertRaises(core.WorkflowError):
                    delivery.propose_manifest(self.run)
                shutil.rmtree(self.run)

    def test_technical_only_cannot_be_h5_playable_delivery(self):
        self.ready(mode="technical_only")
        with self.assertRaises(core.WorkflowError):
            delivery.propose_manifest(self.run)

    def test_incomplete_promised_styles_block_h5(self):
        self.ready(only_style="ceramic")
        with self.assertRaises(core.WorkflowError):
            delivery.propose_manifest(self.run)

    def test_single_style_plan_cannot_shrink_global_h1_promise(self):
        self.plan['styles'] = self.plan['styles'][:1]
        self.plan['delivery_mode'] = 'single_style'
        self.ready(workflow_selected_styles=['ceramic', 'paper'])
        delivery.record_review(self.run, self.review_document())
        result = delivery.propose_manifest(self.run)
        self.assertEqual(result['delivery_scope']['missing_styles'], ['paper'])
        self.assertFalse(result['human_reviewable'])
        with self.assertRaisesRegex(core.WorkflowError, 'all H1-selected styles'):
            delivery.accept(self.run, 'user', 'synthetic://h5', 'accept', result['manifestHash'])

    def test_complete_short_sample_cannot_shrink_global_space_promise(self):
        self.ready(sample_space_ids=['start'])
        delivery.record_review(self.run, self.review_document())
        result = delivery.propose_manifest(self.run)
        self.assertEqual(result['delivery_scope']['missing_spaces'], {s['id']: ['end'] for s in self.plan['styles']})
        self.assertFalse(result['human_reviewable'])
        self.assertFalse(result['acceptance']['scope_complete'])

    def test_old_reviewed_hash_cannot_accept_changed_validation(self):
        self.ready()
        h = delivery.propose_manifest(self.run)["manifestHash"]
        core.validate(self.run, adapter=self.adapter)
        with self.assertRaises(core.WorkflowError):
            delivery.accept(self.run, "user", "synthetic://old-message", "accepted old output", h)

    def test_new_validation_attempt_invalidates_prior_h5(self):
        self.ready()
        self.accept()
        core.validate(self.run, adapter=self.adapter)
        self.assert_stale()

    def test_owned_art_file_drift_invalidates_h5(self):
        self.ready()
        self.accept()
        path = core.resolve_input(core.read(self.run / "run.json")["artifacts"]["ceramic"]["entry_scene"], self.project)
        path.write_text(path.read_text() + "\n# changed\n")
        self.assert_stale()

    def test_source_file_drift_invalidates_h5(self):
        self.ready()
        self.accept()
        path = self.project / "main.gd"
        path.write_text(path.read_text() + "\n# changed\n")
        self.assert_stale()

    def test_native_capture_drift_invalidates_h5(self):
        self.ready()
        self.accept()
        state = core.read(self.run / "run.json")
        Path(state["validation"]["ceramic"]["result"]["evidence"][0]["path"]).write_bytes(png(2))
        self.assert_stale()

    def test_native_log_and_report_drift_invalidate_h5(self):
        self.ready()
        self.accept()
        state = core.read(self.run / "run.json")
        root = Path(state["validation"]["ceramic"]["result"]["attempt_dir"])
        path = root / "godot.log"
        path.write_text(path.read_text() + "changed\n")
        self.assert_stale()

    def test_report_edit_before_acceptance_is_not_current_validation(self):
        self.ready()
        state = core.read(self.run / "run.json")
        p = Path(state["validation"]["ceramic"]["result"]["attempt_dir"]) / "validation.json"
        value = core.read(p)
        value["unrecorded"] = "edit"
        core.write(p, value)
        with self.assertRaises(core.WorkflowError):
            delivery.propose_manifest(self.run)

    def test_missing_plan_makes_h5_stale_without_status_failure(self):
        self.ready()
        self.accept()
        (self.run / "plan.json").unlink()
        self.assert_stale()

    def test_capability_refresh_or_expiry_does_not_erase_h5(self):
        self.ready()
        self.accept()
        state = core.read(self.run / "run.json")
        state["operationalReadiness"] = {"path": "/missing-expired-capability-report", "sha256": "0" * 64,
                                         "session_id": "expired-session"}
        core.save_run(self.run, state)
        self.assertTrue(delivery.acceptance_status(self.run)["accepted"])

    def test_bare_string_in_journal_is_stale(self):
        self.ready()
        state = core.read(self.run / "run.json")
        state["deliveryAcceptance"] = "accepted"
        core.save_run(self.run, state)
        self.assert_stale()

    def test_validation_row_version_mismatch_blocks_h5(self):
        self.ready()
        state = core.read(self.run / "run.json")
        state["validation"]["ceramic"]["planHash"] = "0" * 64
        core.save_run(self.run, state)
        with self.assertRaises(core.WorkflowError):
            delivery.propose_manifest(self.run)

    def test_new_artifact_receipt_cannot_reuse_prior_native_validation(self):
        self.ready()
        state = core.read(self.run / "run.json")
        item = state["artifacts"]["ceramic"]["owned_files"][0]
        p = Path(item["path"])
        p.write_text(p.read_text() + "\\n")
        item["sha256"] = core.file_hash(p)
        core.save_run(self.run, state)
        with self.assertRaises(core.WorkflowError):
            delivery.propose_manifest(self.run)

    def test_native_receipts_cannot_be_replaced_with_boolean_pass(self):
        self.ready()
        state = core.read(self.run / "run.json")
        state["validation"]["ceramic"]["result"].pop("attempt_id")
        core.save_run(self.run, state)
        with self.assertRaises(core.WorkflowError):
            delivery.propose_manifest(self.run)


if __name__ == "__main__":
    unittest.main()
