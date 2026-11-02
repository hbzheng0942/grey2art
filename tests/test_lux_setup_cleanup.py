"""Exercise the shipped Lux setup wrapper, never the unwrapped vendor installer."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/greybox-to-multistyle-art/runtime"))
from greybox import lux


class LuxSetupCleanupTests(unittest.TestCase):
    def test_wrapper_removes_only_failed_invocation_environments(self):
        with tempfile.TemporaryDirectory(prefix="lux-cleanup-synthetic-") as directory:
            cache = Path(directory)
            ready = cache / "environments" / "synthetic-previous-ready"
            concurrent = cache / "environments" / "synthetic-other-install"
            for path in (ready, concurrent):
                path.mkdir(parents=True)
                (path / "unique-marker").write_text(path.name)
            def fail(module, target, requirements):
                (target / "partial-install").write_bytes(b"synthetic partial environment")
                raise lux.LuxError("DEPENDENCY_INDEX_UNAVAILABLE", "Synthetic offline package failure")
            with patch.dict(lux.os.environ, {"LUX3D_COMMON_ENV_DIR": str(cache)}), \
                    patch.object(lux, "_install_environment_with_diagnostics", side_effect=fail) as install:
                for _ in range(2):
                    with self.assertRaises(lux.LuxError) as error:
                        lux._prepare_runtime_worker(install=True)
                    self.assertEqual(error.exception.code, "DEPENDENCY_INDEX_UNAVAILABLE")
            self.assertEqual(install.call_count, 2)
            self.assertEqual({p.name for p in (cache / "environments").iterdir()}, {ready.name, concurrent.name})
            self.assertEqual((ready / "unique-marker").read_text(), ready.name)
            self.assertEqual((concurrent / "unique-marker").read_text(), concurrent.name)
            self.assertEqual(list(cache.glob("*.ready.json")), [])

    def test_check_only_wrapper_creates_no_environment(self):
        with tempfile.TemporaryDirectory(prefix="lux-check-synthetic-") as directory:
            cache = Path(directory) / "not-created"
            with patch.dict(lux.os.environ, {"LUX3D_COMMON_ENV_DIR": str(cache)}), \
                    patch.object(lux, "_install_environment_with_diagnostics") as install:
                with self.assertRaises(lux.LuxError) as error:
                    lux._prepare_runtime_worker(install=False)
                self.assertEqual(error.exception.code, "DEPENDENCY_SETUP_REQUIRED")
                install.assert_not_called()
            self.assertFalse(cache.exists())


if __name__ == "__main__":
    unittest.main()
