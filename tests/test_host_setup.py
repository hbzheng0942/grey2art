"""Minimal setup uses one host, current operation and real runtime probes; no cloud calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art'
sys.path.insert(0, str(ROOT / 'runtime'))
from greybox import core, host, host_cli, host_setup, overview

installer = host_setup.installer_module()


def report(level='invocation_verified', session='current'):
    return {'schema': 1, 'kind': 'host-capability-report', 'host_id': 'codex',
            'session_id': session, 'checked_at': core.now(), 'operations': {
                name: {'status': 'available', 'evidence': 'actual-call-' + name,
                       'channel': {'kind': 'host_tool', 'target': 'test_' + name,
                                   'supports': sorted(overview.HOST_FEATURES[name])},
                       'verification': {'level': level, 'evidence': 'actual-call-' + name}}
                for name in [*overview.BASE_HOST_OPERATIONS, 'image_generate']}}


def package(root, version='fixture-v1'):
    rows = []
    for name in ['SKILL.md', 'scripts/greybox.py', 'runtime/greybox/cli.py']:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('test-only ' + version, encoding='utf-8')
        rows.append({'path': name, 'bytes': path.stat().st_size,
                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (root / 'MANIFEST.json').write_text(json.dumps({'schema': 1, 'name': installer.NAME,
                                                  'version': version, 'files': rows}), encoding='utf-8')


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='greybox-setup-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skill, self.config = self.root / 'package', self.root / 'private'
        package(self.skill)
        self.project = self.root / 'case/game'
        self.project.mkdir(parents=True)
        (self.project / 'project.godot').write_text('config_version=5\n')

    def setup(self, **kwargs):
        with patch.object(host_setup, 'installer_module', return_value=installer):
            return host_setup.setup('codex', config_dir=self.config, skill_root=self.skill, **kwargs)

    def test_greybox_setup_resolves_engine_root_without_supplier_dependencies(self):
        with (patch.object(installer, 'bootstrap_dependencies', side_effect=AssertionError('inactive image dependencies')),
              patch.object(host_setup, 'prepare_lux', side_effect=AssertionError('inactive supplier'))):
            value = self.setup(scope='greybox', project=self.project.parent, executables={'godot': sys.executable})
        self.assertTrue(value['ok'])
        self.assertEqual(value['project']['path'], str(self.project))
        self.assertEqual(value['project']['engine'], 'godot')
        self.assertFalse(value['project']['native_invocation_verified'])
        self.assertFalse(value['production_ready'])
        self.assertFalse(value['provider_calls'])
        self.assertIsNone(value['connector'])
        self.assertEqual(value['skill_identity']['version'], 'fixture-v1')
        self.assertEqual(value['command_prefix'][1], str(self.skill / 'scripts/greybox.py'))

    def test_native_image_invocation_does_not_prepare_or_require_api_profile(self):
        with (patch.object(installer, 'bootstrap_dependencies', side_effect=AssertionError('unneeded runtime')),
              patch.object(host, '_image_route', side_effect=AssertionError('unneeded profile'))):
            value = self.setup(scope='art', capability_report=report(), session_id='current')
        self.assertTrue(value['ok'])
        self.assertTrue(value['verification']['host_session_ready'])
        self.assertEqual(value['verification']['checks']['image_route']['status'], 'native_invocation_verified')

    def test_discovered_native_tool_is_not_invocation_evidence(self):
        value = self.setup(scope='art', capability_report=report('discovered'), session_id='current')
        self.assertFalse(value['ok'])
        self.assertFalse(value['verification']['host_session_ready'])
        self.assertIsNone(value['runtime'])

    def test_wrong_session_is_rejected_before_configuration_writes(self):
        with self.assertRaisesRegex(core.WorkflowError, 'another session'):
            self.setup(capability_report=report(session='old'), session_id='current')
        self.assertFalse(self.config.exists())

    def test_verified_native_binding_requires_explicit_current_session(self):
        value = self.setup(capability_report=report())
        self.assertFalse(value['ok'])
        self.assertEqual(value['verification']['checks']['image_route']['status'], 'missing')

    def test_art_does_not_fail_on_unused_old_blender_path(self):
        host.configure('codex', {'python': sys.executable}, config_dir=self.config)
        profile, path = host._load('codex', self.config)
        profile['executables']['blender'] = str(self.root / 'missing-blender')
        core.write(path, profile)
        value = host.verify('codex', self.config, report(), 'current')
        self.assertTrue(value['ok'])

    def test_api_route_prepares_only_image_runtime(self):
        runtime = {'status': 'reused', 'python': sys.executable, 'runtime_dir': str(self.config / 'runtimes/image-py311')}
        with (patch.object(installer, 'bootstrap_dependencies', return_value=runtime) as image,
             patch.object(host_setup, 'prepare_lux', side_effect=AssertionError('inactive supplier')),
             patch.object(host, '_image_route', return_value={'ok': True})):
            value = self.setup(scope='art', image_profile='configured-images')
        self.assertTrue(value['ok'])
        image.assert_called_once()
        self.assertEqual(image.call_args.args[1], self.config / 'runtimes/image-py311')
        self.assertEqual(value['runtime']['status'], 'reused')

    def test_runtime_scope_does_not_require_image_services_or_native_engine(self):
        runtime = {'ok': True, 'status': 'reused', 'python': sys.executable, 'provider_calls': False}
        with (patch.object(host_setup, 'prepare_lux', side_effect=lambda root, module, explicit, selected: (runtime, selected)),
              patch.object(host, '_image_route', side_effect=AssertionError('inactive image route'))):
            value = self.setup(scope='runtime', runtime='lux')
        self.assertTrue(value['ok'])
        self.assertEqual(value['verification']['checks']['image_route']['status'], 'not_required_for_runtime')

    def test_corrupt_package_fails_before_host_or_project_writes(self):
        (self.skill / 'SKILL.md').write_text('edited without manifest')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.setup()
        self.assertFalse(self.config.exists())

    def test_upgrade_identity_preserves_previous_and_does_not_touch_case_ledger(self):
        ledger = self.project.parent / 'PROGRESS.md'
        ledger.write_text('original job and approval')
        self.setup(scope='greybox', project=self.project, executables={'godot': sys.executable})
        package(self.skill, 'fixture-v2')
        self.setup(scope='greybox', project=self.project, executables={'godot': sys.executable})
        data, _ = host._load('codex', self.config)
        self.assertEqual(data['skill_identity']['version'], 'fixture-v2')
        self.assertEqual(data['previous_skill_identity']['version'], 'fixture-v1')
        self.assertEqual(ledger.read_text(), 'original job and approval')

    def test_multiple_native_projects_require_selection(self):
        sibling = self.project.parent / 'other'
        sibling.mkdir()
        (sibling / 'project.godot').write_text('config_version=5')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.setup(scope='greybox', project=self.project.parent)
        self.assertFalse(self.config.exists())
        self.assertEqual(host_setup.project_root(self.project)['path'], str(self.project))

    def test_project_search_does_not_follow_link_or_scan_cache(self):
        source = self.root / 'outside'
        source.mkdir()
        (source / 'project.godot').write_text('config_version=5')
        (self.project.parent / 'linked').symlink_to(source, target_is_directory=True)
        cache = self.project.parent / '.godot/another'
        cache.mkdir(parents=True)
        (cache / 'project.godot').write_text('cache')
        self.assertEqual(host_setup.project_root(self.project.parent)['path'], str(self.project))

    def test_unity_root_is_resolved_without_launching_editor(self):
        unity = self.root / 'unity-case/native'
        (unity / 'Assets').mkdir(parents=True)
        (unity / 'ProjectSettings').mkdir()
        (unity / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.3.0f1')
        self.assertEqual(host_setup.project_root(unity.parent)['engine'], 'unity')

    def test_setup_cli_dispatches_without_changing_other_command_defaults(self):
        parser = argparse.ArgumentParser()
        host_cli.add_parser(parser.add_subparsers(dest='command'))
        args = parser.parse_args(['host', 'setup', '--scope', 'greybox', '--project', str(self.project)])
        with patch.object(host_setup, 'setup', return_value={'ok': True}) as call:
            self.assertTrue(host_cli.handle(args)['ok'])
        self.assertEqual(call.call_args.args[0], 'auto')


class InterpreterAndDiscoveryTests(unittest.TestCase):
    def test_one_existing_host_or_explicit_selection_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / '.workbuddy/skills').mkdir(parents=True)
            self.assertEqual(installer.resolve_host('auto', home, environ={}, executable=home / 'python'), 'workbuddy')
            (home / '.codex/skills').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                installer.resolve_host('auto', home, environ={}, executable=home / 'python')
            self.assertEqual(installer.resolve_host('codex', home, environ={}), 'codex')
            self.assertEqual(installer.host_skills_dir('workbuddy', home, environ={}), home / '.workbuddy/skills')

    def test_session_hint_overrides_installed_other_hosts(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / '.workbuddy/skills').mkdir(parents=True)
            self.assertEqual(installer.resolve_host('auto', home, environ={'CODEX_THREAD_ID': 'current'}, executable=home / 'python'), 'codex')

    def test_configured_canonical_install_is_reused_and_explicit_directory_wins(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            installed = folder / 'managed' / installer.NAME
            package(installed)
            profile = folder / 'config/hosts/workbuddy.json'
            profile.parent.mkdir(parents=True)
            profile.write_text(json.dumps({'schema': 1, 'kind': 'greybox-host-profile', 'host': 'workbuddy',
                                           'skill_identity': installer.package_identity(installed)}))
            self.assertEqual(installer.host_skills_dir('workbuddy', folder, config_dir=folder / 'config'), installed.parent)
            self.assertEqual(installer.host_skills_dir('workbuddy', folder, explicit=folder / 'chosen', config_dir=folder / 'config'), folder / 'chosen')

    def test_ensurepip_failure_recovers_to_existing_interpreter_and_records_reason(self):
        with (patch.object(installer, 'python_candidates', return_value=[Path('/existing/managed'), Path('/existing/working')]),
             patch.object(installer, 'probe_python', side_effect=[{'path': '/existing/managed', 'ok': False, 'reason': 'venv-ensurepip-failed', 'exit_code': -6},
                                                                 {'path': '/existing/working', 'ok': True, 'venv_verified': True}])):
            selected = installer.select_python(need_venv=True)
        self.assertEqual(selected['path'], '/existing/working')
        self.assertTrue(selected['recovered'])
        self.assertEqual(selected['attempts'][0]['reason'], 'venv-ensurepip-failed')

    def test_explicit_bad_python_never_falls_back(self):
        with (patch.object(installer, 'python_candidates', side_effect=AssertionError('must honor explicit path')),
              patch.object(installer, 'probe_python', return_value={'ok': False, 'reason': 'venv-ensurepip-failed'})):
            with self.assertRaisesRegex(ValueError, 'explicit interpreter'):
                installer.select_python(explicit='/selected/python', need_venv=True)

    def test_python_310_remains_valid_for_core_but_not_image_runtime(self):
        response = subprocess.CompletedProcess([], 0, '[3, 10, 16]')
        with patch.object(installer.subprocess, 'run', return_value=response):
            self.assertTrue(installer.probe_python('/existing/python310')['ok'])
            self.assertFalse(installer.probe_python('/existing/python310', min_version=(3, 11))['ok'])

    def test_image_selection_skips_310_but_explicit_310_does_not_fall_back(self):
        candidates = [Path('/existing/python310'), Path('/existing/python311')]
        versions = [subprocess.CompletedProcess([], 0, '[3, 10, 16]'),
                    subprocess.CompletedProcess([], 0, '[3, 11, 12]')]
        with (patch.object(installer, 'python_candidates', return_value=candidates),
              patch.object(installer.subprocess, 'run', side_effect=versions)):
            value = installer.select_python(min_version=(3, 11))
        self.assertEqual(value['path'], str(candidates[1]))
        self.assertTrue(value['recovered'])
        with (patch.object(installer, 'python_candidates', side_effect=AssertionError('explicit path only')),
              patch.object(installer.subprocess, 'run', return_value=versions[0])):
            with self.assertRaisesRegex(ValueError, 'Python 3.11.*explicit interpreter'):
                installer.select_python(explicit=candidates[0], min_version=(3, 11))

    def test_old_image_runtime_is_preserved_and_requires_new_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime = base / 'runtime'
            executable = runtime / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            executable.parent.mkdir(parents=True)
            executable.write_text('old Python 3.10 fixture')
            (runtime / 'pyvenv.cfg').write_text('version = 3.10')
            (runtime / 'unique.txt').write_text('preserve')
            with (patch.object(installer, 'probe_python', return_value={'ok': False}),
                  patch.object(installer.subprocess, 'run', side_effect=AssertionError('must not modify old runtime'))):
                with self.assertRaisesRegex(ValueError, 'Python 3.11.*Preserve the existing runtime'):
                    installer.bootstrap_dependencies(base / 'skill', runtime)
            self.assertEqual((runtime / 'unique.txt').read_text(), 'preserve')
            self.assertEqual(executable.read_text(), 'old Python 3.10 fixture')
            with installer._operation_lock(base / '.runtime.bootstrap.lock', 'bootstrap'):
                pass

    def test_real_python_invocation_is_measured_without_installing_packages(self):
        selected = installer.probe_python(sys.executable)
        self.assertTrue(selected['ok'])
        self.assertEqual(selected['version'], list(sys.version_info[:3]))
        self.assertFalse(selected['venv_verified'])

    def test_real_offline_venv_probe_checks_pip_and_removes_temporary_environment(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(tempfile, 'tempdir', temporary):
            selected = installer.probe_python(sys.executable, need_venv=True)
            self.assertTrue(selected['ok'], selected)
            self.assertTrue(selected['venv_verified'])
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_image_runtime_with_matching_requirements_is_reused_without_pip_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill, runtime = root / 'skill', root / 'runtime'
            requirements = skill / 'connectors/workbuddy/requirements.txt'
            requirements.parent.mkdir(parents=True)
            requirements.write_text('requests>=2.25.0,<3\nPillow>=13,<14\n')
            python = runtime / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            python.parent.mkdir(parents=True)
            python.write_text('synthetic interpreter; subprocess is mocked')
            (runtime / 'pyvenv.cfg').write_text('synthetic fixture')
            (runtime / '.greybox-image-runtime.json').write_text(json.dumps({
                'requirements_sha256': hashlib.sha256(requirements.read_bytes()).hexdigest()}))
            resolved = {'python': '3.12.14', 'requests': '2.32.5', 'Pillow': '13.0.0'}
            with (patch.object(installer, 'probe_python', return_value={'ok': True}),
                  patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(resolved))) as run):
                result = installer.bootstrap_dependencies(skill, runtime)
            self.assertEqual(result['status'], 'reused')
            self.assertEqual(result['dependency_versions'], resolved)
            self.assertEqual(run.call_count, 1)
            self.assertNotIn('pip', run.call_args.args[0])

    def test_new_failed_image_runtime_is_removed_without_touching_existing_sibling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill, runtime = root / 'skill', root / 'runtime'
            requirements = skill / 'connectors/workbuddy/requirements.txt'
            requirements.parent.mkdir(parents=True)
            requirements.write_text('requests\n')
            sibling = root / 'last-working'
            sibling.mkdir()
            (sibling / 'unique.txt').write_text('keep')
            def failed_create(*args, **kwargs):
                runtime.mkdir()
                (runtime / 'incomplete').write_text('partial')
                raise subprocess.CalledProcessError(-6, 'venv')
            with (patch.object(installer, 'select_python', return_value={'path': sys.executable}),
                  patch.object(installer.subprocess, 'run', side_effect=failed_create)):
                with self.assertRaisesRegex(ValueError, 'bootstrap failed'):
                    installer.bootstrap_dependencies(skill, runtime)
            self.assertFalse(runtime.exists())
            self.assertEqual((sibling / 'unique.txt').read_text(), 'keep')
            with installer._operation_lock(root / '.runtime.bootstrap.lock', 'bootstrap'):
                pass

    def test_real_offline_missing_pip_is_repaired_without_clearing_existing_files(self):
        for explicit in (None, sys.executable):
            with self.subTest(explicit=bool(explicit)), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                skill, runtime = root / 'skill', root / 'runtime'
                requirements = skill / 'connectors/workbuddy/requirements.txt'
                requirements.parent.mkdir(parents=True)
                requirements.write_text('')  # No third-party downloads in this regression.
                subprocess.run([sys.executable, '-I', '-B', '-m', 'venv', '--without-pip', str(runtime)],
                               check=True, capture_output=True, timeout=60)
                executable = runtime / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
                missing = subprocess.run([str(executable), '-I', '-B', '-m', 'pip', '--version'], capture_output=True)
                self.assertNotEqual(missing.returncode, 0)
                site = Path(subprocess.run([str(executable), '-I', '-B', '-c',
                                          'import sysconfig; print(sysconfig.get_path("purelib"))'],
                                         check=True, capture_output=True, text=True).stdout.strip())
                # Local import fixtures keep the runtime smoke probe fully offline;
                # venv/ensurepip/pip itself executes for real.
                (site / 'requests.py').write_text('class Session:\n    def close(self): pass\n')
                (site / 'PIL.py').write_text('# offline decoder fixture\n')
                (runtime / 'unique-user-file.txt').write_text('preserve')
                with (patch.dict(os.environ, {'PIP_NO_INDEX': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1'}),
                      patch.object(installer, 'select_python', wraps=installer.select_python) as select):
                    result = installer.bootstrap_dependencies(skill, runtime, python_executable=explicit,
                                                              configured_python=sys.executable)
                self.assertEqual(result['status'], 'ready')
                self.assertEqual(select.call_count, 1)
                self.assertEqual(select.call_args.args[0], explicit)
                self.assertTrue(select.call_args.kwargs['need_venv'])
                subprocess.run([str(executable), '-I', '-B', '-m', 'pip', '--version'],
                               check=True, capture_output=True, timeout=15)
                self.assertEqual((runtime / 'unique-user-file.txt').read_text(), 'preserve')
                with patch.object(installer, 'select_python', side_effect=AssertionError('ready runtime must be reused')):
                    self.assertEqual(installer.bootstrap_dependencies(skill, runtime)['status'], 'reused')
                with installer._operation_lock(root / '.runtime.bootstrap.lock', 'bootstrap'):
                    pass

    def test_failed_existing_environment_repair_preserves_files_and_reports_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill, runtime = root / 'skill', root / 'runtime'
            requirements = skill / 'connectors/workbuddy/requirements.txt'
            requirements.parent.mkdir(parents=True)
            requirements.write_text('requests\n')
            executable = runtime / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            executable.parent.mkdir(parents=True)
            executable.write_text('mock interpreter')
            (runtime / 'pyvenv.cfg').write_text('fixture')
            (runtime / 'unique.txt').write_text('preserve')
            with (patch.object(installer, 'select_python', return_value={'path': sys.executable}),
                  patch.object(installer, 'probe_python', return_value={'ok': True}),
                  patch.object(installer.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 1),
                                                                        subprocess.CalledProcessError(-6, 'venv')])):
                with self.assertRaisesRegex(ValueError, 'new private runtime path'):
                    installer.bootstrap_dependencies(skill, runtime)
            self.assertEqual((runtime / 'unique.txt').read_text(), 'preserve')
            self.assertTrue((runtime / 'pyvenv.cfg').exists())
            with installer._operation_lock(root / '.runtime.bootstrap.lock', 'bootstrap'):
                pass

    def test_lux_reuses_runtime_without_install_or_account_calls(self):
        selected = {'path': sys.executable, 'ok': True}
        response = subprocess.CompletedProcess([], 0, json.dumps({'ok': True, 'python': sys.executable}), '')
        with patch.object(host_setup.subprocess, 'run', return_value=response) as run:
            result, actual = host_setup.prepare_lux(ROOT, installer, None, selected)
        self.assertEqual(actual, selected)
        self.assertEqual(result['status'], 'reused')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][-2:], ['--prepare-runtime', 'check'])

    def test_lux_missing_runtime_uses_recovered_interpreter_only_for_dependency_setup(self):
        current, recovered = {'path': '/managed/python'}, {'path': '/working/python', 'recovered': True}
        responses = [subprocess.CompletedProcess([], 1, json.dumps({'ok': False, 'error': {'code': 'DEPENDENCY_SETUP_REQUIRED'}}), ''),
                     subprocess.CompletedProcess([], 0, json.dumps({'ok': True, 'python': sys.executable}), '')]
        with (patch.object(installer, 'select_python', return_value=recovered) as select,
              patch.object(host_setup.subprocess, 'run', side_effect=responses) as run):
            result, chosen = host_setup.prepare_lux(ROOT, installer, None, current)
        self.assertEqual(chosen, recovered)
        self.assertEqual(result['status'], 'ready')
        self.assertFalse(result['provider_calls'])
        self.assertTrue(select.call_args.kwargs['need_venv'])
        self.assertEqual(run.call_args_list[1].args[0][0], '/working/python')
        self.assertEqual(run.call_args_list[1].args[0][-2:], ['--prepare-runtime', 'install'])
        self.assertEqual(run.call_args_list[0].kwargs['timeout'], 60)
        self.assertEqual(run.call_args_list[1].kwargs['timeout'], 960)


if __name__ == '__main__':
    unittest.main()
