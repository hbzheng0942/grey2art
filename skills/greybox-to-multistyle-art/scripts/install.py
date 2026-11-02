#!/usr/bin/env python3
"""Verify and atomically install this small source skill; preserve previous installs outside host discovery."""
from __future__ import annotations
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

sys.dont_write_bytecode = True

NAME = 'greybox-to-multistyle-art'
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
HOSTS = ('codex', 'claude-code', 'workbuddy')


def ensure_directory(path):
    """Preserve the host mkdir broker; tolerate EEXIST only for a directory."""
    path = Path(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError as error:
        if error.errno != errno.EEXIST or not path.is_dir():
            raise


def default_config_dir(home=None, environ=None):
    home, env = Path(home or Path.home()), os.environ if environ is None else environ
    if env.get('GREYBOX_CONFIG_HOME'):
        return Path(env['GREYBOX_CONFIG_HOME']).expanduser().absolute()
    if os.name == 'nt':
        return Path(env.get('LOCALAPPDATA', str(home / 'AppData/Local'))) / 'greybox-art'
    return Path(env.get('XDG_CONFIG_HOME', str(home / '.config'))) / 'greybox-art'


def resolve_host(selected='auto', home=None, config_dir=None, environ=None, executable=None):
    """Resolve one host from explicit intent or actual local evidence, never install all."""
    if selected in HOSTS:
        return selected
    if selected not in (None, 'auto'):
        raise ValueError('Unknown host: ' + str(selected))
    home, env = Path(home or Path.home()), os.environ if environ is None else environ
    declared = env.get('GREYBOX_HOST')
    if declared:
        if declared not in HOSTS:
            raise ValueError('GREYBOX_HOST must name codex, claude-code or workbuddy')
        return declared
    active = []
    if env.get('CODEX_THREAD_ID'):
        active.append('codex')
    if env.get('CLAUDECODE') == '1':
        active.append('claude-code')
    if Path(executable or sys.executable).absolute().is_relative_to(home / '.workbuddy'):
        active.append('workbuddy')
    if len(set(active)) == 1:
        return active[0]
    candidates = set(active)
    for name, dirname in (('codex', '.codex'), ('claude-code', '.claude'), ('workbuddy', '.workbuddy')):
        if (home / dirname / 'skills').is_dir():
            candidates.add(name)
    if config_dir:
        for name in HOSTS:
            profile = Path(config_dir) / 'hosts' / (name + '.json')
            if profile.is_file():
                data = json.loads(profile.read_text(encoding='utf-8'))
                if data.get('schema') == 1 and data.get('kind') == 'greybox-host-profile' and data.get('host') == name:
                    candidates.add(name)
    if len(candidates) == 1:
        return next(iter(candidates))
    detail = ', '.join(sorted(candidates)) if candidates else 'none found'
    raise ValueError('Host is ambiguous or unknown (' + detail + '); select --host explicitly. No host was installed or configured.')


def package_identity(root, manifest=None):
    root = Path(root).expanduser().absolute()
    if manifest is None:
        manifest, _ = verified_files(root)
    return {'version': manifest['version'], 'manifest_sha256': hashlib.sha256((root / 'MANIFEST.json').read_bytes()).hexdigest(),
            'skill_root': str(root)}


def python_candidates(configured=None, home=None, environ=None):
    """Existing interpreters only; no downloads, shell aliases or executable guesses."""
    home, env = Path(home or Path.home()), os.environ if environ is None else environ
    candidates = [configured, sys.executable]
    candidates.extend(shutil.which(name, path=env.get('PATH', '')) for name in ('python3', 'python'))
    if sys.platform == 'darwin':
        candidates.extend(('/opt/homebrew/bin/python3', '/usr/local/bin/python3'))
    candidates.extend(sorted((home / '.workbuddy/binaries/python/versions').glob('*/bin/python3'), reverse=True))
    if os.name == 'nt':
        root = Path(env.get('LOCALAPPDATA', str(home / 'AppData/Local')))
        candidates.extend(sorted((root / 'Programs/Python').glob('Python*/python.exe'), reverse=True))
    seen, result = set(), []
    for candidate in candidates:
        if candidate:
            path = Path(candidate).expanduser().absolute()
            if path.is_file() and path.resolve() not in seen:
                seen.add(path.resolve())
                result.append(path)
    return result[:8]


def probe_python(executable, need_venv=False):
    """Actually invoke Python, and only when needed exercise venv/ensurepip offline."""
    path = Path(executable).expanduser().absolute()
    result = {'path': str(path), 'ok': False}
    try:
        run = subprocess.run([str(path), '-I', '-B', '-c',
                              'import json,sys; print(json.dumps(list(sys.version_info[:3])))'],
                             capture_output=True, text=True, timeout=15, check=False)
        version = json.loads(run.stdout) if run.returncode == 0 else []
        if not isinstance(version, list) or tuple(version) < (3, 10):
            return {**result, 'reason': 'python-version-or-invocation-failed'}
        result['version'] = version
        if need_venv:
            with tempfile.TemporaryDirectory(prefix='greybox-python-probe-') as temporary:
                directory = Path(temporary) / 'environment'
                run = subprocess.run([str(path), '-I', '-B', '-m', 'venv', str(directory)],
                                     capture_output=True, text=True, timeout=60, check=False)
                if run.returncode:
                    return {**result, 'reason': 'venv-ensurepip-failed', 'exit_code': run.returncode}
                python = directory / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
                run = subprocess.run([str(python), '-I', '-B', '-m', 'pip', '--version'],
                                     capture_output=True, text=True, timeout=15, check=False)
                if run.returncode:
                    return {**result, 'reason': 'venv-pip-unavailable', 'exit_code': run.returncode}
        return {**result, 'ok': True, 'venv_verified': need_venv}
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        # Do not leak installer/index output or credentials into portable reports.
        return {**result, 'reason': 'python-probe-failed'}


def select_python(explicit=None, configured=None, need_venv=False, home=None, environ=None):
    candidates = [Path(explicit).expanduser().absolute()] if explicit else python_candidates(configured, home, environ)
    attempts = []
    for path in candidates:
        result = probe_python(path, need_venv)
        attempts.append(result)
        if result['ok']:
            return {**result, 'attempts': attempts, 'recovered': len(attempts) > 1}
    mode = 'explicit interpreter; no fallback was selected' if explicit else 'existing interpreter candidates'
    raise ValueError('No usable Python 3.10+ in ' + mode + ': ' + json.dumps(attempts))


def verified_files(source):
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Package source must be a regular directory')
    manifest_path = source / 'MANIFEST.json'
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Package manifest must be a small regular file')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (not isinstance(manifest, dict) or manifest.get('name') != NAME or manifest.get('schema') != 1
            or not isinstance(manifest.get('version'), str) or not manifest['version'].strip()
            or not isinstance(manifest.get('files'), list)):
        raise ValueError('Not a supported greybox-to-multistyle-art package')
    files, seen, total = [], set(), 0
    for item in manifest['files']:
        if (not isinstance(item, dict) or not isinstance(item.get('path'), str)
                or type(item.get('bytes')) is not int or item['bytes'] < 0
                or not isinstance(item.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])):
            raise ValueError('Invalid package file declaration')
        name = item['path']
        rel = PurePosixPath(name)
        if (rel.is_absolute() or name != rel.as_posix() or name in ('', '.', 'MANIFEST.json')
                or '..' in rel.parts or '\\' in name or ':' in name or name in seen):
            raise ValueError('Unsafe or duplicate manifest path: ' + name)
        path = source.joinpath(*rel.parts)
        if any(p.is_symlink() for p in [path, *list(path.parents)[:len(rel.parts)-1]]):
            raise ValueError('Symlink not permitted: ' + name)
        if not path.is_file():
            raise ValueError('Missing package file: ' + name)
        total += item['bytes']
        if total > MAX_PACKAGE_BYTES:
            raise ValueError('Source skill exceeds the small-package limit; do not install projects or generated assets')
        if path.stat().st_size != item['bytes']:
            raise ValueError('Package checksum mismatch: ' + name)
        payload = path.read_bytes()
        if len(payload) != item['bytes'] or hashlib.sha256(payload).hexdigest() != item['sha256']:
            raise ValueError('Package checksum mismatch: ' + name)
        files.append((rel, path))
        seen.add(name)
    for required in ['SKILL.md', 'scripts/greybox.py', 'runtime/greybox/cli.py']:
        if required not in seen:
            raise ValueError('Incomplete package: ' + required)
    return manifest, files


def _present(path):
    return path.exists() or path.is_symlink()


def _recognizable_install(destination):
    """Identify an old skill without requiring locally edited files to verify."""
    if destination.is_symlink():
        return 'symlink-' + hashlib.sha256(os.readlink(destination).encode()).hexdigest()[:12]
    if not destination.is_dir():
        raise ValueError('Refusing to replace an unknown non-skill destination')
    skill = destination / 'SKILL.md'
    recognized = False
    if skill.is_file() and not skill.is_symlink():
        with skill.open(encoding='utf-8') as handle:
            header = handle.read(65536)
        if header.startswith('---'):
            frontmatter = header.split('---', 2)
            recognized = len(frontmatter) > 2 and bool(re.search(
                r'(?m)^name:\s*[\"\']?' + re.escape(NAME) + r'[\"\']?\s*$', frontmatter[1]))
    old_manifest = destination / 'MANIFEST.json'
    version, digest = 'local', 'unmanifested'
    if old_manifest.is_file() and not old_manifest.is_symlink() and old_manifest.stat().st_size <= 2 * 1024 * 1024:
        try:
            payload = old_manifest.read_bytes()
            document = json.loads(payload)
            if document.get('name') == NAME and document.get('schema') == 1:
                recognized = True
                version = str(document.get('version', 'local'))
                digest = hashlib.sha256(payload).hexdigest()[:12]
        except (ValueError, OSError, AttributeError):
            pass
    if not recognized:
        raise ValueError('Refusing to replace an unknown non-skill directory')
    return re.sub(r'[^A-Za-z0-9._-]', '-', version)[:72] + '-' + digest


def _same_install(destination, manifest):
    if destination.is_symlink() or not destination.is_dir():
        return False
    try:
        previous, _ = verified_files(destination)
        return previous == manifest
    except (ValueError, OSError, KeyError, TypeError):
        return False


def _backup_root(destination):
    root = destination.parent.parent / 'skill-backups' / NAME
    # Backups must never re-enter the host's skill discovery tree via links.
    if root.resolve().is_relative_to(destination.parent.resolve()):
        raise ValueError('Skill backups must be outside the host skills directory')
    return root


def install(source, destination, replace=False):
    source = Path(source).expanduser().absolute()
    destination = Path(destination).expanduser().absolute()
    manifest, files = verified_files(source)
    if destination.name != NAME:
        raise ValueError('Destination directory must be named ' + NAME)
    if source == destination:
        return {'status': 'already-installed', 'path': str(destination), 'version': manifest['version'],
                'copiedBytes': 0, 'identity': package_identity(destination, manifest)}
    ensure_directory(destination.parent)
    backups = _backup_root(destination)
    ensure_directory(backups)
    lock = backups / '.install.lock'
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError('Another install owns the skill lock; inspect its process before retrying') from None
    stage, previous = None, None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(str(os.getpid()))
        if _same_install(destination, manifest):
            return {'status': 'already-installed', 'path': str(destination), 'version': manifest['version'],
                    'copiedBytes': 0, 'previous': None, 'identity': package_identity(destination, manifest)}
        if _present(destination):
            if not replace:
                raise ValueError('Installation already exists; use --replace to preserve it outside host skill discovery')
            identity = _recognizable_install(destination)
            previous = backups / (identity + '-' + uuid.uuid4().hex[:12])
        stage = Path(tempfile.mkdtemp(prefix='.' + NAME + '-install-', dir=destination.parent))
        for rel, original in files:
            target = stage.joinpath(*rel.parts)
            ensure_directory(target.parent)
            shutil.copy2(original, target)
        shutil.copy2(source / 'MANIFEST.json', stage / 'MANIFEST.json')
        staged_manifest, _ = verified_files(stage)
        if staged_manifest != manifest:
            raise ValueError('Source manifest changed while staging; preserve the existing installation')
        copied_bytes = sum(item['bytes'] for item in manifest['files']) + (stage / 'MANIFEST.json').stat().st_size
        if previous is not None:
            # rename a symlink itself or the old source directory; never follow,
            # copy, normalize or modify an old link target or edited install.
            os.replace(destination, previous)
        try:
            os.replace(stage, destination)
        except BaseException:
            if previous is not None and _present(previous) and not _present(destination):
                os.replace(previous, destination)
            raise
        return {'status': 'installed', 'path': str(destination), 'version': manifest['version'],
                'copiedBytes': copied_bytes,
                'previous': str(previous) if previous is not None else None,
                'identity': package_identity(destination, manifest),
                'next': 'Run host and project preflight; backups are outside host skill discovery.'}
    finally:
        try:
            if stage is not None and stage.exists():
                shutil.rmtree(stage)
        finally:
            lock.unlink()


def host_skills_dir(host, home=None, explicit=None, config_dir=None, environ=None):
    """Explicit destination wins; WorkBuddy discovery uses existing local evidence."""
    if explicit is not None:
        return Path(explicit).expanduser().absolute()
    home, env = Path(home or Path.home()), os.environ if environ is None else environ
    if config_dir:
        profile = Path(config_dir) / 'hosts' / (host + '.json')
        if profile.is_file():
            data = json.loads(profile.read_text(encoding='utf-8'))
            identity = data.get('skill_identity', {})
            root = Path(identity.get('skill_root', '/__missing_greybox_skill__'))
            if data.get('schema') == 1 and data.get('kind') == 'greybox-host-profile' and data.get('host') == host and identity:
                if (root.is_absolute() and root.name == NAME and root.is_dir()
                        and (root / 'MANIFEST.json').is_file()
                        and json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8')).get('name') == NAME):
                    return root.parent
                raise ValueError('Recorded canonical skill path is missing or invalid; preserve its profile and choose --skills-dir explicitly')
    if host == 'codex':
        return Path(env['CODEX_HOME']).expanduser().absolute() / 'skills' if env.get('CODEX_HOME') else home / '.codex/skills'
    if host == 'claude-code':
        return home / '.claude/skills'
    if host == 'workbuddy':
        existing = home / '.workbuddy/skills'
        if existing.is_dir():
            return existing
        raise ValueError('WorkBuddy skills directory was not found; provide --skills-dir explicitly. A connector is optional.')
    raise ValueError('Select --host or provide --skills-dir')


def rollback(destination, backup):
    """Swap an existing preserved install back without copying either tree."""
    destination, backup = Path(destination).expanduser().absolute(), Path(backup).expanduser().absolute()
    if destination.name != NAME:
        raise ValueError('Destination directory must be named ' + NAME)
    backups = _backup_root(destination)
    if backup.parent.resolve() != backups.resolve() or not _present(backup) or backup.name.startswith('.'):
        raise ValueError('Rollback must name a preserved backup for this exact host skill destination')
    _recognizable_install(backup)
    ensure_directory(backups)
    lock = backups / '.install.lock'
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError('Another install owns the skill lock; inspect its process before retrying') from None
    current = None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(str(os.getpid()))
        if _present(destination):
            current = backups / (_recognizable_install(destination) + '-' + uuid.uuid4().hex[:12])
            os.replace(destination, current)
        try:
            os.replace(backup, destination)
        except BaseException:
            if current is not None and _present(current) and not _present(destination):
                os.replace(current, destination)
            raise
        return {'status': 'rolled-back', 'path': str(destination), 'preserved': str(current) if current else None,
                'copiedBytes': 0, 'next': 'Restart host discovery and refresh only the affected runtime bindings.'}
    finally:
        lock.unlink()


def bootstrap_dependencies(skill_root, runtime_dir, python_executable=None, configured_python=None):
    """Optional private venv. Never copy it into the skill or run global pip."""
    skill_root, runtime_dir = Path(skill_root).absolute(), Path(runtime_dir).expanduser().absolute()
    if runtime_dir.resolve().is_relative_to(skill_root.resolve()):
        raise ValueError('Choose a runtime directory outside the installed skill')
    if runtime_dir.is_symlink():
        raise ValueError('Runtime directory must not be a symlink; choose a private environment path')
    ensure_directory(runtime_dir.parent)
    lock = runtime_dir.parent / ('.' + runtime_dir.name + '.bootstrap.lock')
    created = not runtime_dir.exists()
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError('Another bootstrap owns the runtime lock; inspect its process before retrying') from None
    try:
        os.close(fd)
        executable = runtime_dir / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if runtime_dir.exists() and ((runtime_dir / 'pyvenv.cfg').is_symlink()
                                     or not (runtime_dir / 'pyvenv.cfg').is_file()):
            raise ValueError('Runtime directory already contains non-venv files; choose an empty path')
        requirements = skill_root / 'connectors/workbuddy/requirements.txt'
        digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
        receipt = runtime_dir / '.greybox-image-runtime.json'
        probe = ("import json,sys,requests,PIL; requests.Session().close(); "
                 "print(json.dumps({'python':sys.version.split()[0],"
                 "'requests':getattr(requests,'__version__',None),"
                 "'Pillow':getattr(PIL,'__version__',None)}))")

        def versions(result):
            # Older/import-only probes and test fixtures may not expose versions.
            # Unknown stays null; a successful import is not a pinned resolution.
            try:
                value = json.loads(result.stdout)
            except (ValueError, TypeError, AttributeError):
                value = {}
            return {key: value.get(key) if isinstance(value, dict)
                    and isinstance(value.get(key), str) else None
                    for key in ('python', 'requests', 'Pillow')}

        if executable.is_file() and receipt.is_file():
            previous = json.loads(receipt.read_text(encoding='utf-8'))
            checked = (subprocess.run([str(executable), '-I', '-B', '-c', probe], capture_output=True, timeout=30)
                       if previous.get('requirements_sha256') == digest else None)
            if checked is not None and checked.returncode == 0:
                return {'status': 'reused', 'python': str(executable), 'runtime_dir': str(runtime_dir),
                        'dependency_versions': versions(checked),
                        'requirements_sha256': digest, 'scope': 'Private image HTTP/decoder runtime; no provider calls'}
        selected = None
        pip_ready = False
        if executable.is_file():
            try:
                pip_ready = subprocess.run([str(executable), '-I', '-B', '-m', 'pip', '--version'],
                                           capture_output=True, timeout=15, check=False).returncode == 0
            except (OSError, subprocess.SubprocessError):
                pass  # Probe another complete interpreter before one bounded repair.
        if python_executable or not pip_ready:
            selected = select_python(python_executable, configured_python, need_venv=True)
            # venv without --clear repairs its interpreter/ensurepip in place.
            # Never delete an existing environment or its unrelated user files.
            subprocess.run([selected['path'], '-I', '-B', '-m', 'venv', str(runtime_dir)], check=True, capture_output=True, timeout=60)
            subprocess.run([str(executable), '-I', '-B', '-m', 'pip', '--version'],
                           check=True, capture_output=True, timeout=15)
        subprocess.run([str(executable), '-I', '-B', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-r',
                        str(requirements)], check=True, capture_output=True, timeout=300)
        checked = subprocess.run([str(executable), '-I', '-B', '-c', probe], check=True, capture_output=True, timeout=30)
        resolved = versions(checked)
        receipt.write_text(json.dumps({'requirements_sha256': digest, 'dependency_versions': resolved}) + '\n', encoding='utf-8')
        return {'status': 'ready', 'python': str(executable), 'runtime_dir': str(runtime_dir),
                'dependency_versions': resolved,
                'requirements_sha256': digest, 'interpreter_selection': selected,
                'scope': 'Private user runtime; requests/Pillow only. No engine, assets or service credentials installed.'}
    except (subprocess.SubprocessError, OSError):
        if created and runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        raise ValueError('Private runtime bootstrap failed; existing environments were preserved. '
                         'Check package-index connectivity; for a broken environment select a complete Python 3.10+ '
                         'with --python and use a new private runtime path (--bootstrap PATH). '
                         'Do not clear the existing directory or repeat an unchanged failing setup.') from None
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--host', choices=(*HOSTS, 'auto'), help='Install for one host; auto uses current session or existing local host evidence')
    parser.add_argument('--home', type=Path, help='Resolve host user skill locations under this home; useful for managed deployments')
    parser.add_argument('--skills-dir', type=Path,
                        help='Explicit destination for your chosen agent; no implicit Codex/WorkBuddy installation')
    parser.add_argument('--replace', action='store_true', help='Preserve the old skill or link outside host discovery, then replace atomically')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--rollback', type=Path, metavar='BACKUP', help='Restore one preserved host install, preserving the current install in turn')
    parser.add_argument('--bootstrap', type=Path, metavar='RUNTIME_DIR', help='Install optional image HTTP/decoder dependencies into this private external venv')
    parser.add_argument('--python', dest='python_executable', type=Path, help='Explicit complete Python for --bootstrap; no automatic interpreter fallback')
    parser.add_argument('--connector-dir', type=Path, help='Generate a local WorkBuddy CLI connector referencing this install; no global config changes')
    parser.add_argument('--config-dir', type=Path, help='Existing private host bindings, used to reuse the canonical installed path')
    args = parser.parse_args()
    if args.config_dir is None:
        args.config_dir = default_config_dir(args.home)
    if not args.verify_only and args.skills_dir is None and args.host is None:
        args.verify_only = True
    if sys.version_info < (3, 10):
        parser.error('Python 3.10 or newer is required')
    try:
        if args.host == 'auto':
            args.host = resolve_host(args.host, args.home, args.config_dir)
        if args.connector_dir and args.host != 'workbuddy':
            raise ValueError('--connector-dir requires --host workbuddy')
        if args.rollback and (args.verify_only or args.bootstrap or args.connector_dir):
            raise ValueError('--rollback cannot be combined with verification, bootstrap or connector generation')
        if args.verify_only:
            manifest, files = verified_files(args.source)
            result = {'status': 'verified', 'version': manifest['version'], 'files': len(files)}
            if args.skills_dir is None:
                result['next'] = 'Read SKILL.md directly, or install with --skills-dir for your chosen agent; no files were installed.'
        else:
            skills_dir = host_skills_dir(args.host, args.home, args.skills_dir, args.config_dir)
            destination = skills_dir / NAME
            result = rollback(destination, args.rollback) if args.rollback else install(args.source, destination, args.replace)
            if args.bootstrap:
                result['runtime'] = bootstrap_dependencies(destination, args.bootstrap, python_executable=args.python_executable)
            if args.connector_dir:
                if args.host != 'workbuddy':
                    raise ValueError('--connector-dir requires --host workbuddy')
                sys.path.insert(0, str(destination / 'runtime'))
                from greybox.host import render_workbuddy_connector
                result['connector'] = render_workbuddy_connector(args.connector_dir, destination)
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=True), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
