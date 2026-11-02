"""Offline contract/fixture tests for dedicated Meshy and Tripo v3 adapters."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox.providers import meshy, tripo
from greybox.provider_http import ProviderError, file_hash

TASK = "task_abc123"


def glb(rig=False, animation=False, geometry=True):
    doc = {"asset": {"version": "2.0"}}
    if geometry: doc["meshes"] = [{"primitives": [{"attributes": {"POSITION": 0}}]}]
    if rig: doc["skins"] = [{"joints": [0]}]
    if animation: doc["animations"] = [{"channels": [{}], "samplers": [{}]}]
    data = json.dumps(doc).encode(); data += b" " * (-len(data) % 4)
    return b"glTF" + struct.pack("<IIII", 2, 20 + len(data), len(data), 0x4e4f534a) + data


class FakeAPI:
    def __init__(self, responses, content=None):
        self.responses = list(responses)
        self.content = content or glb(rig=True, animation=True)
        self.calls, self.downloads = [], []
    def request(self, method, path, payload=None, files=None):
        self.calls.append((method, path, copy.deepcopy(payload), files))
        result = self.responses.pop(0)
        if isinstance(result, Exception): raise result
        return copy.deepcopy(result)
    def download(self, url, output_dir, filename):
        path = Path(output_dir) / filename
        self.downloads.append(url)
        if filename.endswith(".fbx"): content = b"Kaydara FBX Binary  \x00"
        elif filename.endswith(".png"): content = b"\x89PNG\r\n\x1a\nfixture"
        elif filename.endswith(".obj"): content = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
        else: content = self.content
        path.write_bytes(content)
        return {"path": str(path), "sha256": file_hash(path), "bytes": len(content)}


def mesh_request(operation="image_to_3d", model="meshy-7.1", **parameters):
    if operation == "image_to_3d" and not parameters: parameters = {"image_url": "https://example.com/ref.png"}
    return {"operation": operation, "model_version": model, "parameters": parameters}


def tripo_request(operation="image_to_3d", model="v3.1-20260211", **parameters):
    if operation == "image_to_3d" and not parameters: parameters = {"input": "https://example.com/ref.png"}
    if operation in {"animation", "retarget"} and "input" in parameters:
        parameters.setdefault("rig_context", {"task_id": parameters["input"], "model_version": "v3.0-20260909", "rig_type": "biped"})
    return {"operation": operation, "model_version": model, "parameters": parameters}


def mesh_task(**changes):
    result = {"id": TASK, "status": "SUCCEEDED", "model_urls": {"glb": "https://assets.meshy.ai/model.glb"}, "consumed_credits": 30}
    result.update(changes); return result


def tripo_task(**changes):
    data = {"task_id": TASK, "status": "success", "output": {"model_url": "https://cdn.tripo3d.ai/model.glb"}, "credits_consumed": 30}
    data.update(changes); return {"code": 0, "data": data}


class DedicatedProviderTests(unittest.TestCase):
    def setUp(self):
        from greybox import provider_credentials
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        storage = patch.object(provider_credentials, 'store_path', return_value=Path(temporary.name) / 'credentials/providers.json')
        storage.start()
        self.addCleanup(storage.stop)

    def test_offline_capabilities_never_claim_connection_or_generation(self):
        for module in (meshy, tripo):
            with self.subTest(module=module.PROVIDER), patch.dict(os.environ, {}, clear=True):
                result = module.dispatch("capabilities", {})
                self.assertTrue(result["installed"])
                self.assertFalse(result["configured"])
                self.assertFalse(result["connection_verified"])
                self.assertEqual(result["operations_verified"], [])

    def test_validate_is_pure_and_omits_private_payload(self):
        for module, request in [(meshy, mesh_request()), (tripo, tripo_request())]:
            client = FakeAPI([])
            result = module.dispatch("validate", request, client)
            self.assertEqual(client.calls, [])
            self.assertNotIn("example.com", json.dumps(result))

    def test_meshy_text_preview_and_refine_are_two_paid_jobs(self):
        preview = mesh_request("text_to_3d", prompt="A ceramic fox", target_formats=["glb"])
        self.assertEqual(meshy.build_payload(preview)[1]["mode"], "preview")
        refine = mesh_request("texture_refine", preview_task_id=TASK, enable_pbr=True)
        self.assertEqual(meshy.build_payload(refine)[1]["mode"], "refine")
        client = FakeAPI([{"result": TASK}])
        result = meshy.dispatch("submit", preview, client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result["recovery"]["endpoint"], "/openapi/v2/text-to-3d")
        with self.assertRaises(ProviderError): meshy.build_payload(mesh_request("text_to_3d", prompt="fox", mode="refine"))

    def test_meshy_model_specific_constraints(self):
        valid = mesh_request(model="meshy-t2.5", image_url="https://example.com/ref.png", model_type="smart-topology", topology="triangle", target_polycount=25000)
        self.assertEqual(meshy.build_payload(valid)[1]["target_polycount"], 25000)
        bad_requests = [mesh_request(model="latest"), mesh_request(model="meshy-7"),
            mesh_request(model="meshy-t2.5", image_url="https://example.com/ref.png", model_type="smart-topology", topology="quad"),
            mesh_request(model="meshy-6-lite", image_url="https://example.com/ref.png", image_enhancement=True),
            mesh_request(image_url="https://example.com/ref.png", enable_pbr=True, should_texture=False),
            mesh_request(image_url="https://example.com/ref.png", target_polycount=1000, decimation_mode=2),
            mesh_request(image_url="https://example.com/ref.png", unexpected_key=True)]
        for request in bad_requests:
            with self.subTest(request=request), self.assertRaises(ProviderError): meshy.build_payload(request)

    def test_meshy_multiview_limits_and_endpoint_resolution(self):
        valid = mesh_request("multiview_to_3d", image_urls=["https://example.com/a.png", "https://example.com/b.png"], geometry_resolution="2k")
        self.assertEqual(meshy.build_payload(valid)[0], "/openapi/v1/multi-image-to-3d")
        valid["parameters"]["geometry_resolution"] = "4k"
        with self.assertRaises(ProviderError): meshy.build_payload(valid)
        valid["parameters"] = {"image_urls": ["https://example.com/a.png"] * 5}
        with self.assertRaises(ProviderError): meshy.build_payload(valid)

    def test_meshy_hash_bound_local_image_and_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "reference.png"; path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            request = mesh_request(image_path=0)
            request["inputs"] = [{"path": str(path), "sha256": file_hash(path)}]
            self.assertTrue(meshy.build_payload(request)[1]["image_url"].startswith("data:image/png;base64,"))
            path.write_bytes(b"changed")
            with self.assertRaises(ProviderError): meshy.build_payload(request)
            request["parameters"] = {"image_path": str(Path(temporary) / "unbound.png")}
            with self.assertRaises(ProviderError): meshy.build_payload(request)

    def test_meshy_rig_animation_dependency_binding(self):
        document = mesh_request("animation", "animations-v1", rig_task_from="rig-op", action_ids=[4, 92])
        document["dependencies"] = {"rig-op": {"provider": "meshy", "state": "ready", "task_id": TASK}}
        payload = meshy.build_payload(document)[1]
        self.assertEqual(payload["rig_task_id"], TASK)
        document["dependencies"]["rig-op"]["provider"] = "tripo"
        with self.assertRaises(ProviderError): meshy.build_payload(document)
        with self.assertRaises(ProviderError): meshy.build_payload(mesh_request("animation", "animations-v1", rig_task_id=TASK, action_id=4, action_ids=[92]))

    def test_meshy_local_rig_rejects_non_glb_before_post(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "character.fbx"
            path.write_bytes(b"Kaydara FBX Binary  \x00fixture")
            request = mesh_request("rig", "rigging-v1", model_path=0)
            request["inputs"] = [{"path": str(path), "sha256": file_hash(path)}]
            client = FakeAPI([])
            with self.assertRaises(ProviderError): meshy.dispatch("submit", request, client)
            self.assertEqual(client.calls, [])

    def test_meshy_encoded_bytes_cannot_drift_after_hash_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = (Path(temporary) / "reference.png").resolve()
            path.write_bytes(b"\x89PNG\r\n\x1a\noriginal")
            request = mesh_request(image_path=0)
            request["inputs"] = [{"path": str(path), "sha256": file_hash(path)}]
            original_read = Path.read_bytes
            def changed_read(p):
                if p.resolve() == path:
                    path.write_bytes(b"\x89PNG\r\n\x1a\nchanged")
                return original_read(p)
            client = FakeAPI([])
            with patch.object(Path, "read_bytes", changed_read), self.assertRaises(ProviderError):
                meshy.dispatch("submit", request, client)
            self.assertEqual(client.calls, [])

    def test_meshy_rig_and_remesh_versions_and_external_formats(self):
        meshy.build_payload(mesh_request("rig", "rigging-v1", model_url="https://example.com/character.glb", height_meters=1.8))
        meshy.build_payload(mesh_request("remesh", "remesh-v1", model_url="https://example.com/prop.fbx", target_polycount=50000, topology="quad"))
        with self.assertRaises(ProviderError): meshy.build_payload(mesh_request("rig", "rigging-v1", model_url="https://example.com/character.fbx"))

    def test_meshy_exact_task_and_recovery_ownership(self):
        document = {"task_id": TASK, "accepted_request": mesh_request()}
        with self.assertRaises(ProviderError): meshy.dispatch("status", document, FakeAPI([mesh_task(id="other-task")]))
        document["recovery"] = {"provider": "meshy", "task_id": TASK, "endpoint": "/openapi/v1/rigging"}
        with self.assertRaises(ProviderError): meshy.dispatch("status", document, FakeAPI([]))

    def test_meshy_all_states_and_consumed_credits(self):
        for status, expected in [("PENDING", "queued"), ("IN_PROGRESS", "running"), ("SUCCEEDED", "succeeded"), ("FAILED", "failed"), ("CANCELED", "cancelled")]:
            with self.subTest(status=status):
                result = meshy.dispatch("status", {"task_id": TASK, "accepted_request": mesh_request()}, FakeAPI([mesh_task(status=status)]))
                self.assertEqual(result["state"], expected)
                self.assertEqual(result["consumed_credits"], 30)

    def test_meshy_fetch_all_requested_formats_and_texture_channels(self):
        with tempfile.TemporaryDirectory() as temporary:
            accepted = mesh_request(image_url="https://example.com/ref.png", target_formats=["glb", "fbx"])
            task = mesh_task(model_urls={"glb": "https://assets.meshy.ai/model.glb", "fbx": "https://assets.meshy.ai/model.fbx"}, texture_urls=[{"base_color": "https://assets.meshy.ai/color.png", "roughness": "https://assets.meshy.ai/rough.png"}])
            result = meshy.dispatch("fetch", {"task_id": TASK, "accepted_request": accepted, "output_dir": temporary}, FakeAPI([task]))
            self.assertEqual(len(result["artifacts"]), 4)
            self.assertEqual({a["role"] for a in result["artifacts"]}, {"model-glb", "model-fbx", "texture-0-base_color", "texture-0-roughness"})

    def test_meshy_fetch_requires_outputs_and_requested_formats(self):
        for model_urls in [{}, {"fbx": "https://assets.meshy.ai/model.fbx"}]:
            with self.subTest(model_urls=model_urls), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(ProviderError): meshy.dispatch("fetch", {"task_id": TASK, "accepted_request": mesh_request(), "output_dir": temporary}, FakeAPI([mesh_task(model_urls=model_urls)]))

    def test_meshy_rig_and_animation_structural_demands(self):
        cases = [("rig", "rigging-v1", {"rigged_character_glb_url": "https://assets.meshy.ai/rig.glb"}),
                 ("animation", "animations-v1", {"animation_glb_url": "https://assets.meshy.ai/motion.glb"})]
        for operation, model, output in cases:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(ProviderError):
                    meshy.dispatch("fetch", {"task_id": TASK, "accepted_request": mesh_request(operation, model), "output_dir": temporary}, FakeAPI([mesh_task(result=output)], content=glb()))

    def test_meshy_unknown_submission_missing_id_never_retries(self):
        client = FakeAPI([{"result": None}])
        with self.assertRaises(ProviderError) as context: meshy.dispatch("submit", mesh_request(), client)
        self.assertTrue(context.exception.unknown_submission)
        self.assertEqual(len(client.calls), 1)

    def test_tripo_h_and_p_model_specific_bounds(self):
        tripo.build_payload(tripo_request(model="P2-20260801", input="https://example.com/ref.png", quad=True, face_limit=25000))
        tripo.build_payload(tripo_request(model="v3.1-20260211", input="https://example.com/ref.png", geometry_quality="detailed", face_limit=2000000))
        bad = [tripo_request(model="latest"), tripo_request(model="P1-20260311", input="file_abc", quad=True),
               tripo_request(model="P2-20260801", input="file_abc", quad=True, face_limit=25001),
               tripo_request(model="v2.5-20250123", input="file_abc", geometry_quality="detailed"),
               tripo_request(input="file_abc", texture_quality="fast"), tripo_request(input="file_abc", texture=False),
               tripo_request(input="file_abc", generate_parts=True), tripo_request(input="file_abc", arbitrary=True)]
        for request in bad:
            with self.subTest(request=request), self.assertRaises(ProviderError): tripo.build_payload(request)

    def test_tripo_new_texture_and_parts_options(self):
        tripo.build_payload(tripo_request(input="file_abc", texture_quality="fast", texture_version="v3.5-20260815", delight=True))
        tripo.build_payload(tripo_request(input="file_abc", texture=False, pbr=False, generate_parts=True))

    def test_tripo_multiview_views_and_positional_order(self):
        tripo.build_payload(tripo_request("multiview_to_3d", inputs=[{"front": "file_a"}, {"back": "file_b"}]))
        tripo.build_payload(tripo_request("multiview_to_3d", inputs=["file_a", "", "file_b", ""]))
        tripo.build_payload(tripo_request("multiview_to_3d", inputs=[{"task_id": TASK}]))
        for inputs in [[{"front": "file_a"}], [{"left": "file_a"}, {"back": "file_b"}], [{"front": "file_a"}, {"front": "file_b"}], ["file_a", "file_b"]]:
            with self.subTest(inputs=inputs), self.assertRaises(ProviderError): tripo.build_payload(tripo_request("multiview_to_3d", inputs=inputs))

    def test_tripo_local_upload_precedes_one_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "reference.png"; path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            request = tripo_request(image_path=0); request["inputs"] = [{"path": str(path), "sha256": file_hash(path)}]
            client = FakeAPI([{"code": 0, "data": {"file_token": "file_abc"}}, {"code": 0, "data": {"task_id": TASK}}])
            tripo.dispatch("validate", request, client)
            self.assertEqual(client.calls, [])
            result = tripo.dispatch("submit", request, client)
            self.assertEqual(result["task_id"], TASK)
            self.assertEqual([c[1] for c in client.calls], ["/files", "/generation/image-to-model"])
            self.assertEqual(client.calls[1][2]["input"], "file_abc")

    def test_tripo_uploaded_bytes_cannot_change_after_bound_input_inspection(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = (Path(temporary) / "reference.png").resolve()
            path.write_bytes(b"\x89PNG\r\n\x1a\noriginal")
            request = tripo_request(image_path=0)
            request["inputs"] = [{"path": str(path), "sha256": file_hash(path)}]
            original_read = Path.read_bytes
            def changed_read(p):
                if p.resolve() == path:
                    path.write_bytes(b"\x89PNG\r\n\x1a\nchanged")
                return original_read(p)
            client = FakeAPI([])
            with patch.object(Path, "read_bytes", changed_read), self.assertRaises(ProviderError):
                tripo.dispatch("submit", request, client)
            self.assertEqual(client.calls, [])

    def test_tripo_cannot_smuggle_unbound_local_upload(self):
        with self.assertRaises(ProviderError): tripo.build_payload(tripo_request(input={"_bound_upload": "/private/key"}))
        with self.assertRaises(ProviderError): tripo.build_payload(tripo_request("multiview_to_3d", inputs=[{"front": {"_bound_upload": "/private/key"}}, {"back": "file_b"}]))

    def test_tripo_rig_models_and_skeleton_conventions(self):
        tripo.build_payload(tripo_request("rig", "v3.0-20260909", input=TASK, spec="unity", out_format="fbx"))
        tripo.build_payload(tripo_request("rig", "v2.5-20260210", input=TASK, rig_type="quadruped"))
        with self.assertRaises(ProviderError): tripo.build_payload(tripo_request("rig", "v1.0-20240301", input=TASK, rig_type="quadruped"))
        with self.assertRaises(ProviderError): tripo.build_payload(tripo_request("rig", "v2.5-20260210", input=TASK, spec="unity"))

    def test_tripo_animation_and_remesh_constraints(self):
        tripo.build_payload(tripo_request("animation", "retarget-v3", input=TASK, animations=["preset:walk", "preset:run"], animate_in_place=True))
        tripo.build_payload(tripo_request("remesh", "v3.0", input=TASK, smart_uv=True, face_limit=5000))
        with self.assertRaises(ProviderError): tripo.build_payload(tripo_request("animation", "retarget-v3", input=TASK, animation="preset:walk", animations=["preset:run"]))
        with self.assertRaises(ProviderError): tripo.build_payload(tripo_request("remesh", "v2.0", input=TASK, smart_uv=True))
        with self.assertRaises(ProviderError): tripo.build_payload(tripo_request("remesh", "v1.0", input=TASK, face_limit=5000, bake=True))

    def test_tripo_batch_is_five_not_six_and_rejects_undocumented_presets(self):
        actions = ["preset:" + name for name in ("idle", "walk", "run", "dive", "climb", "jump")]
        request = tripo_request("retarget", "retarget-v3", input=TASK, animations=actions[:5])
        payload = tripo.build_payload(request)[1]
        self.assertEqual(len(payload["animations"]), 5)
        self.assertNotIn("rig_context", payload)
        request["parameters"]["animations"] = actions
        client = FakeAPI([])
        with self.assertRaisesRegex(ProviderError, "1 to 5"):
            tripo.dispatch("submit", request, client)
        self.assertEqual(client.calls, [])
        request["parameters"]["animations"] = ["preset:invented_care_action"]
        with self.assertRaisesRegex(ProviderError, "not documented"):
            tripo.build_payload(request)

    def test_tripo_presets_match_actual_rig_version_and_type(self):
        request = tripo_request("retarget", "retarget-v3", input=TASK, animation="preset:quadruped:walk")
        request["parameters"]["rig_context"]["rig_type"] = "quadruped"
        tripo.build_payload(request)
        request["parameters"]["animation"] = "preset:walk"
        with self.assertRaisesRegex(ProviderError, "not documented"):
            tripo.build_payload(request)
        request["parameters"]["rig_context"].update(model_version="v1.0-20240301", rig_type="biped")
        with self.assertRaisesRegex(ProviderError, "not documented"):
            tripo.build_payload(request)
        request["parameters"]["animation"] = "preset:biped:walk"
        tripo.build_payload(request)
        request["parameters"]["rig_context"]["task_id"] = "task_another"
        with self.assertRaisesRegex(ProviderError, "another task"):
            tripo.build_payload(request)

    def test_tripo_retarget_uses_rig_fetch_context_and_refuses_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            rig = tripo_request("rig", "v2.5-20260210", input="file_source", rig_type="quadruped")
            fetched = tripo.dispatch("fetch", {"task_id": TASK, "accepted_request": rig, "output_dir": temporary},
                                     FakeAPI([tripo_task()], content=glb(rig=True)))
            request = tripo_request("retarget", "retarget-v3", input_from="rig", animation="preset:quadruped:walk")
            request["dependencies"] = {"rig": {"provider": "tripo", "state": "ready", "task_id": TASK,
                                                "artifacts": fetched["artifacts"]}}
            self.assertEqual(tripo.build_payload(request)[1]["input"], TASK)
            request["parameters"]["rig_context"] = {"task_id": TASK, "model_version": "v3.0-20260909", "rig_type": "biped"}
            with self.assertRaisesRegex(ProviderError, "conflicts"):
                tripo.build_payload(request)

    def test_tripo_new_retarget_needs_context_but_historical_fetch_remains_recoverable(self):
        request = tripo_request("retarget", "retarget-v3", input=TASK, animation="preset:walk")
        request["parameters"].pop("rig_context")
        with self.assertRaisesRegex(ProviderError, "needs rig_context"):
            tripo.build_payload(request)
        with tempfile.TemporaryDirectory() as temporary:
            fetched = tripo.dispatch("fetch", {"task_id": TASK, "accepted_request": request, "output_dir": temporary},
                                     FakeAPI([tripo_task()], content=glb(animation=True)))
            self.assertEqual(len(fetched["artifacts"]), 1)

    def test_tripo_expired_and_banned_are_terminal(self):
        for state in ["expired", "banned", "failed", "cancelled", "running", "queued", "success"]:
            with self.subTest(state=state):
                result = tripo.dispatch("status", {"task_id": TASK, "accepted_request": tripo_request()}, FakeAPI([tripo_task(status=state)]))
                self.assertEqual(result["state"], "failed" if state in {"expired", "banned"} else "succeeded" if state == "success" else state)
                self.assertEqual(result["consumed_credits"], 30)

    def test_tripo_task_and_recovery_mismatch(self):
        with self.assertRaises(ProviderError): tripo.dispatch("status", {"task_id": TASK, "accepted_request": tripo_request()}, FakeAPI([tripo_task(task_id="task_other")]))
        with self.assertRaises(ProviderError): tripo.dispatch("status", {"task_id": TASK, "accepted_request": tripo_request(), "recovery": {"provider": "meshy", "task_id": TASK}}, FakeAPI([]))

    def test_tripo_fetch_multiformat_and_parts(self):
        with tempfile.TemporaryDirectory() as temporary:
            task = tripo_task(output={"model_url": "https://cdn.tripo3d.ai/model.glb", "model_urls": {"fbx": "https://cdn.tripo3d.ai/model.fbx"}, "parts": [{"model_url": "https://cdn.tripo3d.ai/part.glb"}]})
            result = tripo.dispatch("fetch", {"task_id": TASK, "accepted_request": tripo_request(), "output_dir": temporary}, FakeAPI([task]))
            self.assertEqual(len(result["artifacts"]), 3)

    def test_tripo_fetch_missing_or_wrong_format_fails(self):
        for output in [{}, {"model_url": "https://cdn.tripo3d.ai/model.glb"}]:
            with self.subTest(output=output), tempfile.TemporaryDirectory() as temporary:
                accepted = tripo_request("rig", "v3.0-20260909", input=TASK, out_format="fbx")
                with self.assertRaises(ProviderError): tripo.dispatch("fetch", {"task_id": TASK, "accepted_request": accepted, "output_dir": temporary}, FakeAPI([tripo_task(output=output)]))

    def test_tripo_animation_requires_channels_but_may_exclude_geometry(self):
        accepted = tripo_request("animation", "retarget-v3", input=TASK, animation="preset:walk", export_with_geometry=False)
        with tempfile.TemporaryDirectory() as temporary:
            result = tripo.dispatch("fetch", {"task_id": TASK, "accepted_request": accepted, "output_dir": temporary}, FakeAPI([tripo_task()], content=glb(animation=True, geometry=False)))
            self.assertEqual(len(result["artifacts"]), 1)
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ProviderError):
            tripo.dispatch("fetch", {"task_id": TASK, "accepted_request": accepted, "output_dir": temporary}, FakeAPI([tripo_task()], content=glb()))

    def test_tripo_rig_check_is_report_not_model(self):
        accepted = tripo_request("rig_check", "rig-check-v3", input=TASK)
        with tempfile.TemporaryDirectory() as temporary:
            result = tripo.dispatch("fetch", {"task_id": TASK, "accepted_request": accepted, "output_dir": temporary}, FakeAPI([tripo_task(output={"riggable": True, "rig_type": "biped"}, credits_consumed=0)]))
            self.assertEqual(result["artifacts"][0]["role"], "rig-check-report")

    def test_tripo_business_rejection_sanitized_and_unknown_result_preserved(self):
        client = FakeAPI([{"code": 2010, "message": "secret-key"}])
        with self.assertRaises(ProviderError) as context: tripo.dispatch("submit", tripo_request(), client)
        self.assertFalse(context.exception.unknown_submission)
        self.assertNotIn("secret-key", str(context.exception))
        for response in [{"code": 0, "data": {}}, {"code": 0}, {}]:
            with self.subTest(response=response):
                client = FakeAPI([response])
                with self.assertRaises(ProviderError) as context: tripo.dispatch("submit", tripo_request(), client)
                self.assertTrue(context.exception.unknown_submission)
                self.assertEqual(len(client.calls), 1)

    def test_same_provider_task_dependencies_and_cross_provider_model_transfer(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "character.glb"; path.write_bytes(glb())
            artifact = {"path": str(path), "sha256": file_hash(path), "role": "model-glb"}
            dependencies = {"source": {"state": "ready", "provider": "meshy", "task_id": TASK, "artifacts": [artifact]}}
            request = tripo_request("rig", "v3.0-20260909", model_from="source"); request["dependencies"] = dependencies
            self.assertEqual(tripo.build_payload(request)[1]["input"], {"_bound_upload": str(path.resolve()), "_sha256": file_hash(path)})
            request["parameters"] = {"input_from": "source"}
            with self.assertRaises(ProviderError): tripo.build_payload(request)
            request = mesh_request("rig", "rigging-v1", model_from="source"); request["dependencies"] = dependencies
            self.assertTrue(meshy.build_payload(request)[1]["model_url"].startswith("data:application/octet-stream"))

    def test_multi_motion_partial_glb_cannot_pass(self):
        cases = [(meshy, mesh_request("animation", "animations-v1", rig_task_id=TASK, action_ids=[4, 92]),
                  mesh_task(result={"animation_glb_url": "https://assets.meshy.ai/motion.glb"})),
                 (tripo, tripo_request("animation", "retarget-v3", input=TASK, animations=["preset:walk", "preset:run"]), tripo_task())]
        for module, accepted, task in cases:
            with self.subTest(provider=module.PROVIDER), tempfile.TemporaryDirectory() as temporary, self.assertRaises(ProviderError):
                module.dispatch("fetch", {"task_id": TASK, "accepted_request": accepted, "output_dir": temporary}, FakeAPI([task], content=glb(animation=True)))
        with self.assertRaises(ProviderError):
            tripo.build_payload(tripo_request("animation", "retarget-v3", input=TASK, animations=["preset:walk", "preset:run"], out_format="fbx"))

    def test_rig_check_false_or_changed_report_blocks_paid_rig(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "check.json"
            request = tripo_request("rig", "v3.0-20260909", input=TASK, rig_check_from="check")
            dependency = {"provider": "tripo", "state": "ready", "task_id": "task_check", "artifacts": []}
            request["dependencies"] = {"check": dependency}
            for riggable in [False, True]:
                path.write_text(json.dumps({"provider": "tripo", "task_id": "task_check", "source_digest": tripo._source_fingerprint(TASK), "output": {"riggable": riggable, "rig_type": "biped"}}))
                dependency["artifacts"] = [{"path": str(path), "sha256": file_hash(path), "role": "rig-check-report"}]
                if riggable:
                    tripo.build_payload(request)
                else:
                    with self.assertRaises(ProviderError): tripo.build_payload(request)
            path.write_text("changed")
            with self.assertRaises(ProviderError): tripo.build_payload(request)

    def test_tripo_green_check_for_another_model_cannot_enable_rig(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "check.json"
            path.write_text(json.dumps({"provider": "tripo", "task_id": "task_check", "source_digest": tripo._source_fingerprint("task_model_a"), "output": {"riggable": True, "rig_type": "biped"}}))
            request = tripo_request("rig", "v3.0-20260909", input="task_model_b", rig_check_from="check")
            request["dependencies"] = {"check": {"provider": "tripo", "state": "ready", "task_id": "task_check", "artifacts": [
                {"path": str(path), "sha256": file_hash(path), "role": "rig-check-report"}]}}
            client = FakeAPI([])
            with self.assertRaises(ProviderError): tripo.dispatch("submit", request, client)
            self.assertEqual(client.calls, [])
            request["parameters"]["input"] = "task_model_a"
            tripo.build_payload(request)

    def test_tripo_local_check_recovery_keeps_actual_model_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "character.glb"; path.write_bytes(glb())
            accepted = tripo_request("rig_check", "rig-check-v3", model_path=0)
            accepted["inputs"] = [{"path": str(path), "sha256": file_hash(path)}]
            client = FakeAPI([{"code": 0, "data": {"file_token": "file_checked"}}, {"code": 0, "data": {"task_id": TASK}}])
            submitted = tripo.dispatch("submit", accepted, client)
            self.assertEqual(submitted["recovery"]["source_digest"], tripo._source_fingerprint({"_bound_upload": str(path), "_sha256": file_hash(path)}))
            output = Path(temporary) / "output"
            result = tripo.dispatch("fetch", {"task_id": TASK, "accepted_request": {k: accepted[k] for k in ("operation", "model_version", "parameters")},
                                   "recovery": submitted["recovery"], "output_dir": str(output)},
                                   FakeAPI([tripo_task(output={"riggable": True, "rig_type": "biped"}, credits_consumed=0)]))
            report = json.loads(Path(result["artifacts"][0]["path"]).read_text())
            self.assertEqual(report["source_digest"], submitted["recovery"]["source_digest"])
            rig = tripo_request("rig", "v3.0-20260909", model_path=0, rig_check_from="check")
            rig["inputs"] = accepted["inputs"]
            rig["dependencies"] = {"check": {"provider": "tripo", "state": "ready", "task_id": TASK, "artifacts": result["artifacts"]}}
            tripo.build_payload(rig)

    def test_explicit_readonly_account_only(self):
        m = FakeAPI([{"balance": 123}]); t = FakeAPI([{"code": 0, "data": {"balance": 456, "frozen": 10}}])
        self.assertTrue(meshy.dispatch("account", {}, m)["connection_verified"])
        self.assertTrue(tripo.dispatch("account", {}, t)["connection_verified"])
        self.assertEqual([m.calls[0][0], t.calls[0][0]], ["GET", "GET"])


if __name__ == "__main__": unittest.main()
