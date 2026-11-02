"""One local setup path. No generation, account probes, engine migration or task-ledger writes."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

from . import core, host


def installer_module():
    spec = importlib.util.spec_from_file_location('_greybox_host_installer', host.SKILL / 'scripts/install.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def project_root(project, engine=None):
    """Bounded inspection of the supplied directory and two child levels, excluding links/caches."""
    folder = Path(project).expanduser().absolute()
    if not folder.is_dir():
        raise ValueError('Project directory does not exist: ' + str(folder))

    def identify(path):
        result = []
        if (path / 'project.godot').is_file():
            result.append(('godot', path))
        if (path / 'Assets').is_dir() and (path / 'ProjectSettings/ProjectVersion.txt').is_file():
            result.append(('unity', path))
        return [row for row in result if engine is None or row[0] == engine]

    matches = identify(folder)
    if not matches:
        excluded = {'node_modules', 'vendor', 'Library', 'Temp', 'Logs', 'assets', 'Assets', 'build', 'dist', '__pycache__'}
        queue = [(folder, 0)]
        inspected = 0
        while queue:
            current, depth = queue.pop(0)
            if depth >= 2:
                continue
            for child in sorted(current.iterdir()):
                if child.name.startswith('.') or child.name in excluded or child.is_symlink() or not child.is_dir():
                    continue
                inspected += 1
                if inspected > 128:
                    raise ValueError('Project search exceeded 128 directories; pass the actual engine project root')
                found = identify(child)
                matches.extend(found)
                if not found:
                    queue.append((child, depth + 1))
    if len(matches) != 1:
        choices = ', '.join(kind + ':' + str(path) for kind, path in matches) or 'none found'
        raise ValueError('Engine project is ambiguous or missing (' + choices + '); pass its exact --project and --engine')
    kind, path = matches[0]
    return {'engine': kind, 'path': str(path), 'input_path': str(folder), 'native_invocation_verified': False}


def native_image_binding(report, selected_host, session_id):
    if report is None or not session_id:
        return None
    from .overview import check_host_capabilities
    checked = check_host_capabilities(report, required_operations=['image_generate'],
                                      expected_host=selected_host, expected_session=session_id)
    binding = checked.get('bindings', {}).get('image_generate', {})
    if binding.get('kind') in {'host_tool', 'mcp'} and binding.get('verification') == 'invocation_verified':
        return binding
    return None


def spatial_root(project):
    """A Blender workspace need not contain a game project or a future output file."""
    path = Path(project).expanduser().absolute()
    if path.is_file():
        core.require(path.suffix.lower() == '.blend', 'Spatial source must be an existing .blend file')
        return {'engine': 'blender', 'path': str(path.parent), 'input_path': str(path),
                'source': str(path), 'native_invocation_verified': False}
    core.require(path.is_dir(), 'Spatial workspace must be an existing directory or .blend source')
    return {'engine': 'blender', 'path': str(path), 'input_path': str(path),
            'source': None, 'native_invocation_verified': False}


def prepare_lux(root, installer, explicit_python, selected):
    """Use only the pinned bridge's dependency entrypoint. Never log in or call a provider."""
    entrypoint = root / 'runtime/greybox/lux.py'

    def invoke(executable, action):
        try:
            result = subprocess.run([str(executable), '-I', '-B', str(entrypoint), '--prepare-runtime', action],
                                    # Match lux._runtime_python: pip gets 900 seconds
                                    # plus time for venv setup and worker cleanup.
                                    capture_output=True, text=True, timeout=960 if action == 'install' else 60, check=False)
            data = json.loads(result.stdout)
            if isinstance(data, dict) and result.returncode == 0 and data.get('ok') and Path(data.get('python', '')).is_file():
                return data
            code = data.get('error', {}).get('code') if isinstance(data, dict) and isinstance(data.get('error'), dict) else None
            return {'ok': False, 'code': code or 'DEPENDENCY_SETUP_FAILED'}
        except (OSError, ValueError, subprocess.SubprocessError):
            return {'ok': False, 'code': 'DEPENDENCY_SETUP_FAILED'}

    existing = invoke(selected['path'], 'check')
    if existing['ok']:
        return {**existing, 'status': 'reused', 'scope': 'lux-dependencies-only', 'provider_calls': False}, selected
    if existing['code'] not in {'DEPENDENCY_SETUP_REQUIRED', 'DEPENDENCY_BOOTSTRAP_FAILED'}:
        raise ValueError('Lux runtime check failed: ' + existing['code'] + '; preserve its cache and resolve that diagnostic')
    recovered = installer.select_python(explicit=explicit_python, configured=selected['path'], need_venv=True)
    result = invoke(recovered['path'], 'install')
    if not result['ok']:
        raise ValueError('Lux runtime preparation failed: ' + result['code'] + '; no provider operation was submitted')
    return {**result, 'status': 'ready', 'scope': 'lux-dependencies-only', 'provider_calls': False}, recovered


def setup(selected_host='auto', config_dir=None, project=None, engine=None, scope='art',
          executables=None, image_profile=None, image_config_dir=None, capability_report=None,
          session_id=None, runtime=None, connector_dir=None, skill_root=None, operation=None):
    core.require(scope in {'art', 'greybox', 'runtime', 'spatial'}, 'Choose art, greybox, spatial or runtime setup scope')
    core.require(runtime in {None, 'image', 'lux'}, 'Choose only the runtime needed by the current operation')
    core.require(scope not in {'greybox', 'spatial'} or runtime is None, 'Greybox/spatial setup does not prepare image or supplier runtimes')
    core.require(operation in {None, 'create', 'edit', 'review'}, 'Unknown spatial operation')
    core.require(scope == 'spatial' or operation is None, 'Operation applies only to spatial setup')
    core.require(scope != 'spatial' or engine in {None, 'blender'}, 'Spatial setup currently binds the Blender authoring carrier')
    core.require(scope != 'runtime' or runtime is not None, 'Runtime scope needs the selected --runtime image or lux')
    root = Path(skill_root or host.SKILL).expanduser().absolute()
    private = host.config_root(config_dir)
    core.require(not private.resolve().is_relative_to(root.resolve()), 'Keep host configuration outside the installed skill')
    installer = installer_module()
    identity = installer.package_identity(root)  # Refuse altered/unverified packages before any writes.
    selected_host = installer.resolve_host(selected_host, config_dir=private)
    old, profile_path = host._load(selected_host, private)
    project_info = (spatial_root(project) if scope == 'spatial' else project_root(project, engine)) if project is not None else None
    if scope in {'greybox', 'spatial'} and project_info is None:
        raise ValueError(scope.capitalize() + ' setup requires --project pointing at the existing native project or spatial workspace')
    engine = project_info['engine'] if project_info else engine
    native = native_image_binding(capability_report, selected_host, session_id) if scope == 'art' else None
    bindings = dict(executables or {})
    selected = installer.select_python(explicit=bindings.get('python'), configured=old.get('executables', {}).get('python'))
    effective_profile = image_profile if image_profile is not None else old.get('image_profile')
    prepared = None
    if runtime == 'lux':
        prepared, selected = prepare_lux(root, installer, bindings.get('python'), selected)
    elif runtime == 'image' or (scope == 'art' and effective_profile and not native):
        prepared = installer.bootstrap_dependencies(root, private / 'runtimes/image',
                                                    python_executable=bindings.get('python'), configured_python=selected['path'])
        selected = {**selected, 'path': prepared['python']}
    bindings['python'] = selected['path']
    configuration = host.configure(selected_host, bindings, image_profile, private, image_config_dir,
                                   connector_dir, root)
    with host._locked(private):
        profile, _ = host._load(selected_host, private)
        previous = profile.get('skill_identity')
        if previous and previous != identity:
            profile['previous_skill_identity'] = previous
        profile['skill_identity'] = identity
        if prepared:
            profile.setdefault('runtimes', {})['lux' if runtime == 'lux' else 'image'] = prepared
        host._write(profile_path, profile)
    verification = host.verify(selected_host, private, capability_report, session_id, scope, engine, operation=operation)
    return {'ok': verification['ok'], 'kind': 'host-setup', 'host': selected_host, 'scope': scope,
            'execution': 'cli', 'skill_identity': identity, 'project': project_info,
            'python_selection': selected, 'runtime': prepared, 'connector': configuration['connector'],
            'verification': verification, 'command_prefix': [selected['path'], str(root / 'scripts/greybox.py')],
            'next': 'Continue the current task using this command prefix and resolved project path. Preserve its original decisions, references and recovery IDs.',
            'production_ready': False, 'provider_calls': False,
            'readiness_scope': 'Local package/runtime bindings only; native operation and current session evidence remain separate'}
