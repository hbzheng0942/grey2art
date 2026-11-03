"""Native-adapter metadata I/O; no game engine, provider or user project."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
SKILL = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(SKILL / "runtime"))
from greybox import core, unity, execution_process
import test_continuity as continuity_fixtures
import test_unity_v04 as unity_fixtures


def ansi_reader(original):
    def read(path, *args, **kwargs):
        kwargs.setdefault("encoding", "cp1252")
        return original(path, *args, **kwargs)
    return read


class NativeIOTests(unittest.TestCase):
    def test_concurrent_disjoint_package_additions_both_survive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "Packages/manifest.json"
            core.write(target, {"dependencies": {"existing": "1"}})
            snapshot, contended = threading.Event(), threading.Event()
            read_write, acquire = unity._json, execution_process.exclusive
            def hold_first_snapshot(path, data=None):
                result = read_write(path, data)
                if data is None and not snapshot.is_set():
                    snapshot.set()
                    self.assertTrue(contended.wait(10))
                return result
            @contextmanager
            def observe_lock(path):
                try:
                    with acquire(path) as handle:
                        yield handle
                except execution_process.LockBusyError:
                    contended.set()
                    raise
            with patch.object(unity, "_json", side_effect=hold_first_snapshot), \
                 patch.object(execution_process, "exclusive", observe_lock), ThreadPoolExecutor(2) as pool:
                first = pool.submit(unity.configure_packages, root, True, False)
                self.assertTrue(snapshot.wait(10))
                second = pool.submit(unity.configure_packages, root, False, True)
                first.result(timeout=15)
                second.result(timeout=15)
            self.assertEqual(core.read(target)["dependencies"], {
                "existing": "1", "com.unity.cloud.gltfast": unity.GLTFAST_VERSION,
                "com.unity.render-pipelines.universal": unity.URP_VERSION})

    def test_unity_scene_inventory_preserves_utf8_under_ansi_locale(self):
        fixture = unity_fixtures.UnityV04Tests("test_inventory_uses_project_version_and_manifest")
        fixture.setUp()
        try:
            fixture.write("Assets/陶瓷.unity", "%YAML 1.1\n")
            fixture.write("ProjectSettings/EditorBuildSettings.asset",
                          "  m_Scenes:\n  - enabled: 1\n    path: Assets/陶瓷.unity\n")
            with patch.object(Path, "read_text", ansi_reader(Path.read_text)), \
                 patch.object(unity, "engine", return_value="synthetic-not-invoked"):
                report = unity.inspect(fixture.root)
            self.assertEqual(report["main_scene"], "Assets/陶瓷.unity")
        finally:
            fixture.doCleanups()

    def test_progress_cli_preserves_unicode_plan_updates(self):
        fixture = continuity_fixtures.ContinuityTests("test_questions_and_proposals_do_not_become_approval_or_change")
        fixture.setUp()
        try:
            token = fixture.token()
            request = fixture.project / "update.json"
            core.write(request, {"changes": {"objective": "陶瓷场景"}, "event": fixture.event})
            spec = importlib.util.spec_from_file_location("progress_unicode_test", SKILL / "scripts/progress.py")
            progress = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(progress)
            argv = ["progress.py", "update", "--project", str(fixture.project), "--case", str(fixture.case),
                    "--writer", "integrator", "--expected-revision", str(token["plan_revision"]),
                    "--checkpoint-sha256", token["checkpoint_sha256"], "--input", str(request)]
            output = io.StringIO()
            with patch.object(Path, "read_text", ansi_reader(Path.read_text)), \
                 patch.object(sys, "argv", argv), patch.object(sys, "stdout", output):
                code = progress.main()
            self.assertEqual(code, 0, output.getvalue())
            self.assertEqual(core.read(fixture.case / "PLAN.json")["objective"], "陶瓷场景")
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
