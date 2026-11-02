import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art/runtime'))
from greybox import board_native as native, core, reference_boards as boards, cli
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None


@unittest.skipIf(Image is None, 'Native board pixel checks require Pillow')
class NativeBoards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name).resolve()
        self.refs = []
        for name, color in [('style', 'blue'), ('layout', 'gray')]:
            path = self.project / (name + '.png')
            Image.new('RGB', (256, 256), color).save(path)
            self.refs.append({'path': path.name, 'sha256': core.file_hash(path)})
        self.request = {'operation': 'edit', 'prompt': 'ONE board: puppy dog, basin, cabinet. Keep all nine requested subjects.',
                        'images': self.refs, 'parameters': {}, 'purpose': 'modeling-reference'}
        self.binding = {'schema': 1, 'kind': 'reference-board-native-binding', 'host': 'codex',
                        'tool': 'image_gen.imagegen', 'source_ref': 'synthetic tool schema, no actual invocation',
                        'input_transport': 'local_paths', 'max_references': 2,
                        'image_argument': 'referenced_image_paths', 'fixed_arguments': {'transparent_background': False}}
        core.write(self.project / 'request.json', self.request)
        self.save_binding()

    def save_binding(self):
        core.write(self.project / 'binding.json', self.binding)

    def prepare(self, output='dispatch.json'):
        self.save_binding()
        return native.prepare(self.request, self.binding, self.project, output,
                              request_path='request.json', binding_path='binding.json')

    def dispatch(self):
        return core.read(self.project / 'dispatch.json')

    def output(self):
        path = self.project / 'board.png'
        im = Image.new('RGB', (768, 384), 'white')
        draw = ImageDraw.Draw(im)
        draw.rectangle([80, 80, 239, 239], fill='blue')
        draw.rectangle([464, 80, 623, 239], fill='red')
        im.save(path)
        return path

    def test_codex_preserves_prompt_order_and_does_not_claim_invocation(self):
        result = self.prepare()
        d = self.dispatch()
        self.assertFalse(result['invocation_recorded'])
        self.assertFalse(result['submission'])
        self.assertEqual(d['tool_arguments']['prompt'], self.request['prompt'])
        self.assertEqual(d['tool_arguments']['referenced_image_paths'], [str(self.project / r['path']) for r in self.refs])
        stamp = (self.project / 'dispatch.json').stat().st_mtime_ns
        self.prepare()
        self.assertEqual(stamp, (self.project / 'dispatch.json').stat().st_mtime_ns)

    def test_workbuddy_local_and_explicit_url_in_deferred_envelope(self):
        self.binding.update(host='workbuddy', tool='DeferExecuteTool', input_transport='mixed',
                            image_arguments=['image1', 'image2', 'image3'],
                            arguments_container='params', envelope_arguments={'toolName': 'ImageGen'},
                            uploads=[dict(self.refs[1], url='https://example.com/real-upload.png', source_ref='synthetic upload fixture')])
        self.binding.pop('image_argument')
        self.binding.pop('fixed_arguments')
        self.prepare()
        args = self.dispatch()['tool_arguments']
        self.assertEqual(args['toolName'], 'ImageGen')
        self.assertEqual(args['params']['image1'], str(self.project / 'style.png'))
        self.assertEqual(args['params']['image2'], 'https://example.com/real-upload.png')
        self.assertEqual(args['params']['prompt'], self.request['prompt'])

    def test_claude_requires_an_explicit_actual_tool_binding(self):
        self.binding.update(host='claude-code', tool='actual-installed-plugin.image', image_argument='images')
        self.prepare()
        self.assertEqual(self.dispatch()['tool'], 'actual-installed-plugin.image')
        self.binding.pop('source_ref')
        with self.assertRaisesRegex(ValueError, 'schema|capability'):
            self.prepare('other.json')

    def test_capacity_and_unsupported_parameters_fail_before_output(self):
        self.binding['max_references'] = 1
        with self.assertRaisesRegex(ValueError, 'capacity'):
            self.prepare()
        self.assertFalse((self.project / 'dispatch.json').exists())
        self.binding['max_references'] = 2
        self.request['parameters']['quality'] = 'high'
        core.write(self.project / 'request.json', self.request)
        with self.assertRaisesRegex(ValueError, 'parameter'):
            self.prepare()

    def test_no_input_collision_overwrite_or_fake_upload(self):
        self.binding['fixed_arguments']['prompt'] = 'replace'
        with self.assertRaisesRegex(ValueError, 'collides'):
            self.prepare()
        self.binding['fixed_arguments'].pop('prompt')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            self.prepare('style.png')
        self.binding.update(input_transport='https_urls', uploads=[])
        with self.assertRaisesRegex(ValueError, 'every reference'):
            self.prepare()

    def test_transparency_and_multiple_outputs_are_rejected_before_invocation(self):
        for values in [{'transparent_background': True}, {'background': 'transparent'}, {'n': 2}]:
            self.binding['fixed_arguments'] = values
            with self.assertRaisesRegex(ValueError, 'opaque white'):
                self.prepare()
            self.assertFalse((self.project / 'dispatch.json').exists())

    def test_record_rejects_omitted_reordered_or_changed_actual_inputs(self):
        self.prepare()
        dispatch = self.dispatch()
        actual = copy.deepcopy(dispatch['tool_arguments'])
        actual['referenced_image_paths'].reverse()
        with self.assertRaisesRegex(ValueError, 'Actual native arguments'):
            native.record(dispatch, actual, self.output(), 'job', self.project, source_ref='synthetic actual call')
        self.assertFalse((self.project / 'job').exists())
        Image.new('RGB', (256, 256), 'green').save(self.project / 'style.png')
        with self.assertRaisesRegex(ValueError, 'changed|hash'):
            native.record(dispatch, dispatch['tool_arguments'], self.output(), 'job', self.project, source_ref='synthetic actual call')

    def test_single_shared_native_receipt_supports_multiple_strict_crops(self):
        self.prepare()
        dispatch = self.dispatch()
        recorded = native.record(dispatch, dispatch['tool_arguments'], self.output(), 'job', self.project,
                                 source_ref='synthetic invocation fixture; no host call')
        outputs = []
        for aid, roi in [('first', [32, 32, 288, 288]), ('second', [416, 32, 672, 288])]:
            request = {'schema': 1, 'kind': 'reference-board-crop-request', 'asset_id': aid,
                       'view_id': 'front', 'role': 'front', 'selected_concept_sha256': self.refs[0]['sha256'],
                       'board': {'path': 'board.png', 'sha256': core.file_hash(self.project / 'board.png')},
                       'generation_receipt': recorded['receipt'], 'roi': roi, 'padding': 16,
                       'min_subject_long_edge_px': 128, 'min_subject_short_edge_px': 128,
                       'output': aid + '.png', 'receipt_output': aid + '.crop.json'}
            result = boards.crop(request, self.project)
            self.assertTrue(boards.validate_crop_receipt(result['board_crop_receipt'], self.project)['ok'])
            outputs.append(result['image']['sha256'])
        self.assertNotEqual(*outputs)
        self.assertEqual(len(list((self.project / 'job').glob('receipt*.json'))), 1)

    def test_unified_cli_maps_native_request_and_exposes_boards_help(self):
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            result = cli.main(['boards', 'native', '--project', str(self.project), '--file', 'request.json',
                               '--binding', 'binding.json', '--host', 'codex', '--output', 'dispatch.json'])
        self.assertEqual(result, 0)
        self.assertFalse(json.loads(stream.getvalue())['invocation_recorded'])


if __name__ == '__main__':
    unittest.main()
