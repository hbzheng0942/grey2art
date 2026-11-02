"""Real public CLI, approved ledgers, processes and loopback fault injection.

No cloud, paid task, production credential or native host tool is involved.
"""
from collections import Counter
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/greybox-to-multistyle-art'
sys.path[:0] = [str(ROOT / 'tests'), str(SKILL / 'runtime')]
from greybox import core, image_jobs, supplier_jobs, suppliers
import test_supplier_jobs_r3 as supplier_fixture

try:
    from PIL import Image
except ImportError:
    Image = None


class LoopbackImages:
    def __init__(self, output, slow_response=False, trickle=False):
        self.output, self.slow_response, self.trickle = str(output), slow_response, trickle
        self.events, self.tasks = [], {}
        self.maximum = 0
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self, value, drip=False):
                raw = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                try:
                    if drip:
                        for byte in raw:
                            self.wfile.write(bytes([byte])); self.wfile.flush()
                            time.sleep(.03)
                    else:
                        self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                name, now = value['name'], time.time()
                with owner.lock:
                    identity = str(len(owner.tasks) + 1)
                    owner.tasks[identity] = {'name': name, 'done': now + (.4 if name == 'fast' else 2.5), 'polls': 0}
                    owner.events.append(('created', name, now))
                    owner.maximum = max(owner.maximum, sum(t['done'] > now for t in owner.tasks.values()))
                if owner.slow_response:
                    time.sleep(.8)
                self.answer({'state': 'submitted', 'provider_task_id': identity})

            def do_GET(self):
                identity = self.path.strip('/')
                with owner.lock:
                    task = owner.tasks[identity]
                    task['polls'] += 1
                    drip = owner.trickle and task['polls'] == 1
                    state = 'succeeded' if time.time() >= task['done'] else 'running'
                    owner.events.append(('queried', task['name'], time.time()))
                result = {'state': state, 'provider_task_id': identity}
                if state == 'succeeded':
                    result['items'] = [{'path': owner.output}]
                self.answer(result, drip)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)


class SupplierCLIIntegration(unittest.TestCase):
    def test_public_cli_uses_actual_approved_supplier_run(self):
        fixture = supplier_fixture.SupplierJobTests('test_submit_reservation_is_persisted_before_any_command')
        fixture.setUp()
        try:
            adapter = fixture.project / 'actual-command-adapter.py'
            adapter.write_text('''import json,sys
from pathlib import Path
r=json.load(sys.stdin)
result={'schema':1,'provider':r['provider'],'method':r['method'],'ok':True}
if r['method']=='submit': result['task_id']='original-'+r['request']['operation']
elif r['method']=='status': result['state']='succeeded'
else:
    output=Path(r['request']['output_dir']); output.mkdir(parents=True,exist_ok=True)
    file=output/'fixture.glb'; file.write_bytes(''' + repr(supplier_fixture.synthetic_glb()) + ''')
    result['artifacts']=[{'path':str(file),'role':'model'}]
print(json.dumps(result))
''')
            for provider in fixture.registry['providers']:
                provider['binding'].update(argv=[sys.executable, '-B', str(adapter)], adapter_path=str(adapter), sha256=core.file_hash(adapter))
            fixture.portfolio['registry_sha256'] = suppliers.registry_digest(fixture.registry)
            fixture.selection['registry_sha256'] = suppliers.registry_digest(fixture.registry)
            fixture.rebind_portfolio()
            fixture.prepare()
            queue = fixture.project / 'queue.json'
            core.write(queue, {'schema': 1, 'kind': 'greybox-execution-queue',
                'pools': {'shared': {'capacity': 2, 'source_ref': 'synthetic-shared-capacity'}},
                'sources': [{'kind': 'supplier', 'path': str(fixture.run),
                             'pools': {'character-vendor': 'shared', 'environment-vendor': 'shared'}}],
                'limits': {'poll_interval': .02, 'tick_interval': .01}})
            result = subprocess.run([sys.executable, '-B', str(SKILL / 'scripts/greybox.py'),
                'executor', 'run', '--file', str(queue), '--state-dir', str(fixture.project / 'execution'), '--max-seconds', '8'],
                capture_output=True, text=True, timeout=12)
            self.assertEqual(result.returncode, 2, result.stderr)
            summary = json.loads(result.stdout)
            ledger = core.read(fixture.run / 'supplier-run.json')
            self.assertEqual(summary['phase'], 'blocked', {'summary': summary,
                'errors': {key: row.get('execution_error') for key, row in ledger['operations'].items() if row.get('execution_error')}})
            self.assertEqual(ledger['operations']['hero-model']['state'], 'ready')
            self.assertEqual(ledger['operations']['environment-model']['state'], 'ready')
            self.assertEqual(ledger['operations']['hero-rig']['state'], 'preflight_blocked')
            self.assertIn('Rig submission needs completed GLB review', ledger['operations']['hero-rig']['execution_error']['local_reason'])
            self.assertEqual(len(ledger['reservations']), 3)
            self.assertEqual(summary['pools']['shared']['occupied'], 0)
        finally:
            fixture.tearDown()


@unittest.skipIf(Image is None, 'Pillow needed for actual image output decoding')
class ImageCLIIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='execution-public-cli-')
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'EXECUTION_SYNTHETIC_AUTH': 'not-a-provider-key'})
        self.env.start()
        self.output = self.root / 'fixture.png'
        Image.new('RGB', (32, 32), 'white').save(self.output)
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=3)
        self.env.stop()
        self.temp.cleanup()

    def configure(self, provider):
        source = self.root / 'adapter.py'
        source.write_text('''import json,sys,urllib.request
r=json.load(sys.stdin)
base=''' + repr(provider.base) + '''
if r['action']=='submit':
    req=urllib.request.Request(base,data=json.dumps({'name':r['request']['prompt']}).encode(),method='POST')
else: req=urllib.request.Request(base+'/'+r['task_id'])
with urllib.request.urlopen(req,timeout=2) as response: print(response.read().decode())
''')
        image_jobs.configure('fixture', {'kind': 'custom', 'credential_env': 'EXECUTION_SYNTHETIC_AUTH',
            'capabilities': {'generate': True, 'edit': False, 'max_references': 0, 'parameters': []},
            'adapter': {'source': str(source), 'sha256': core.file_hash(source), 'argv': [sys.executable, '-B', '{adapter}'],
                        'documentation': {'source_ref': 'synthetic-loopback-protocol'}}}, self.root / 'config')

    def queue(self, names, **limits):
        sources = []
        for name in names:
            folder = self.root / name
            image_jobs.reserve('fixture', {'operation': 'generate', 'prompt': name, 'images': [], 'parameters': {}}, folder,
                config_dir=self.root / 'config', authorization={'source_ref': 'synthetic-only'})
            sources.append({'kind': 'image', 'path': str(folder), 'pools': {'fixture': 'shared'}})
        queue = self.root / 'queue.json'
        core.write(queue, {'schema': 1, 'kind': 'greybox-execution-queue',
            'pools': {'shared': {'capacity': 2, 'source_ref': 'synthetic-capacity'}}, 'sources': sources,
            'limits': {'poll_interval': .04, 'retry_interval': .05, 'tick_interval': .01, 'status_timeout': .7, **limits}})
        return queue

    def launch(self, queue):
        process = subprocess.Popen([sys.executable, '-B', str(SKILL / 'scripts/executor.py'), 'run',
            '--file', str(queue), '--state-dir', str(self.root / 'execution'), '--max-seconds', '7'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.processes.append(process)
        return process

    def test_public_cli_finishes_real_pixels_despite_all_first_polls_trickling(self):
        provider = LoopbackImages(self.output, trickle=True)
        try:
            self.configure(provider)
            queue = self.queue(['fast', 'slow', 'next'])
            process = self.launch(queue)
            time.sleep(1.2)  # No agent/model dispatch or status nudges while runner works.
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            summary = json.loads(stdout)
            self.assertEqual(summary['phase'], 'complete', summary)
            self.assertEqual(provider.maximum, 2)
            self.assertEqual(Counter(name for event, name, at in provider.events if event == 'created'), {'fast': 1, 'slow': 1, 'next': 1})
            created_next = next(at for event, name, at in provider.events if (event, name) == ('created', 'next'))
            slow_done = next(task['done'] for task in provider.tasks.values() if task['name'] == 'slow')
            self.assertLess(created_next, slow_done)
            for name in ['fast', 'slow', 'next']:
                self.assertEqual(image_jobs.status(self.root / name, remote=False)['state'], 'downloaded')
        finally:
            provider.close()

    def test_restart_after_server_accepts_before_id_is_saved_recovers_original(self):
        provider = LoopbackImages(self.output, slow_response=True)
        try:
            self.configure(provider)
            queue = self.queue(['fast'], submit_timeout=3)
            first = self.launch(queue)
            deadline = time.monotonic() + 4
            while not provider.tasks and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(provider.tasks)
            before = core.read(self.root / 'fast/job.json')
            self.assertEqual(before['state'], 'submitting')
            self.assertIsNone(before.get('provider_task_id'))
            first.kill(); first.communicate(timeout=2)
            second = self.launch(queue)
            stdout, stderr = second.communicate(timeout=10)
            self.assertEqual(second.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout)['phase'], 'complete')
            after = core.read(self.root / 'fast/job.json')
            self.assertEqual(after['state'], 'downloaded')
            self.assertEqual(after['provider_task_id'], '1')
            self.assertEqual(len(provider.tasks), 1)
        finally:
            provider.close()


@unittest.skipIf(Image is None, 'Pillow needed for native fixture pixels')
class NativeCLIIntegration(unittest.TestCase):
    def test_native_claim_and_late_original_result_settle_through_public_cli(self):
        with tempfile.TemporaryDirectory(prefix='execution-native-cli-') as temporary:
            root = Path(temporary)
            output = root / 'synthetic-output.png'
            Image.new('RGB', (24, 24), 'white').save(output)
            request_file = root / 'request.json'
            core.write(request_file, {'tool_arguments': {'prompt': 'Synthetic concept fixture'}, 'images': []})
            job = root / 'native-job'
            queue_file = root / 'queue.json'
            state_dir = root / 'execution'

            def command(*args, expected=0):
                result = subprocess.run([sys.executable, '-B', str(SKILL / 'scripts/executor.py'), *map(str, args)],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, expected, result.stderr or result.stdout)
                return json.loads(result.stdout)

            command('native-reserve', '--file', request_file, '--job-dir', job,
                    '--tool', 'fixture-native', '--source-ref', 'synthetic-authorized-request')
            core.write(queue_file, {'schema': 1, 'kind': 'greybox-execution-queue',
                'pools': {'shared': {'capacity': 1, 'source_ref': 'synthetic-capacity'}},
                'sources': [{'kind': 'native', 'path': str(job), 'pools': {'fixture-native': 'shared'}}]})
            claimed = command('claim', '--file', queue_file, '--state-dir', state_dir)
            self.assertTrue(claimed['claimed'])
            ticket_path = Path(claimed['ticket_path'])
            ticket = core.read(ticket_path)
            interrupted = root / 'interrupted.json'
            core.write(interrupted, {'ok': False, 'error': {'code': 'SYNTHETIC_CONTROLLER_LOST',
                'category': 'timeout', 'acceptance': 'unknown'}})
            command('record', '--ticket', ticket_path, '--file', interrupted, expected=2)
            self.assertEqual(core.read(job / 'job.json')['state'], 'unknown')
            actual = root / 'original-result.json'
            core.write(actual, {'state': 'succeeded', 'action_id': ticket['lease']['id'],
                'attempt_id': ticket['attempt_id'], 'request_hash': ticket['request_hash'],
                'actual_arguments': ticket['tool_arguments'], 'source_ref': 'synthetic-original-tool-return',
                'output_path': str(output)})
            settled = command('native-settle', '--job-dir', job, '--file', actual)
            self.assertEqual(core.read(job / 'job.json')['state'], 'ready')
            self.assertTrue(settled['capacity']['released'])
            self.assertFalse(command('claim', '--file', queue_file, '--state-dir', state_dir)['claimed'])


if __name__ == '__main__':
    unittest.main()
