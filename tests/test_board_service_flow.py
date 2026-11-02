"""One prepared page through the real Images adapter with synthetic HTTP only."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art/runtime'))
from greybox import core, image_jobs, image_adapters, reference_boards as boards
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None


@unittest.skipIf(Image is None, 'Board service flow requires Pillow')
class BoardServiceFlow(unittest.TestCase):
    def test_nine_subjects_use_one_post_and_one_receipt_for_nine_crops(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            Image.new('RGB', (32, 32), 'blue').save(project / 'concept.png')
            views = [dict(asset_id=f'prop-{i}', view_id='front', role='front', projected_aspect=1,
                          simple_shape_validated=True, min_subject_long_edge_px=150,
                          min_subject_short_edge_px=120) for i in range(9)]
            spec = {'schema': 1, 'kind': 'reference-board-prepare-input',
                    'plan': {'schema': 1, 'kind': 'reference-board-plan-input', 'channel_size': [1536, 1024],
                             'size_source_ref': 'synthetic channel fixture', 'views': views},
                    'images': [{'path': 'concept.png', 'sha256': core.file_hash(project / 'concept.png')}],
                    'objects': [dict(asset_id=x['asset_id'], view_id='front', category='prop',
                                     function='A separate collectible', appearance=f'color pattern {i}',
                                     structure='A complete rounded box with an open handle') for i, x in enumerate(views)],
                    'capabilities': {'edit': True, 'max_references': 2, 'source_ref': 'synthetic API fixture'}}
            prepared = boards.prepare(spec, project, 'prepared')
            self.assertEqual(len(prepared['prepared']), 1)
            request = core.read(project / prepared['prepared'][0]['request']['path'])
            output = Image.new('RGB', (1536, 1024), 'white')
            draw = ImageDraw.Draw(output)
            for i in range(9):
                x, y = (i % 3) * 512 + 100, (i // 3) * 341 + 80
                draw.rectangle([x, y, x + 159, y + 159], fill=(30 + i * 20, 80, 100))
            encoded = io.BytesIO()
            output.save(encoded, format='PNG')

            class Opener:
                def __init__(self): self.calls = []
                def open(self, req, timeout):
                    self.calls.append(req)
                    return io.BytesIO(json.dumps({'data': [{'b64_json': base64.b64encode(encoded.getvalue()).decode()}]}).encode())

            opener = Opener()
            image_jobs.configure('fixture', {'kind': 'openai', 'base_url': 'https://example.invalid/v1',
                                            'model': 'synthetic-image-model', 'credential_env': 'BOARD_SYNTHETIC_KEY'}, project / 'profiles')
            with patch.dict(os.environ, {'BOARD_SYNTHETIC_KEY': 'synthetic-only'}), \
                    patch.object(image_adapters.request, 'build_opener', return_value=opener):
                job = image_jobs.submit('fixture', request, project / 'job', config_dir=project / 'profiles',
                                        base=project, background=False,
                                        authorization={'source_ref': 'synthetic fixture; no paid authority'})
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    image_jobs.submit('fixture', request, project / 'job', config_dir=project / 'profiles',
                                      base=project, background=False, authorization={'source_ref': 'synthetic'})
            self.assertEqual(job['state'], 'downloaded')
            self.assertEqual(len(opener.calls), 1)
            post = opener.calls[0]
            self.assertTrue(post.full_url.endswith('/images/edits'))
            self.assertEqual(post.data.count(b'name="image[]"'), 2)
            self.assertIn(request['prompt'].encode(), post.data)
            for ref in request['images']:
                self.assertIn((project / ref['path']).read_bytes(), post.data)
            result = job['outputs'][0]
            receipt = core.read(result['receipt']['path'])
            self.assertEqual(receipt['actual_input_image_sha256'], [x['sha256'] for x in request['images']])
            for i in range(9):
                x, y = (i % 3) * 512 + 100, (i // 3) * 341 + 80
                crop = dict(schema=1, kind='reference-board-crop-request', asset_id=f'prop-{i}',
                            view_id='front', role='front', selected_concept_sha256=spec['images'][0]['sha256'],
                            board={'path': result['path'], 'sha256': result['sha256']}, generation_receipt=result['receipt'],
                            roi=[x-10, y-10, x+170, y+170], padding=40,
                            min_subject_long_edge_px=150, min_subject_short_edge_px=120,
                            output=f'crops/prop-{i}.png', receipt_output=f'crops/prop-{i}.json')
                cropped = boards.crop(crop, project)
                self.assertTrue(boards.validate_crop_receipt(cropped['board_crop_receipt'], project)['ok'])
            self.assertEqual(len(list((project / 'job').glob('receipt-*.json'))), 1)


if __name__ == '__main__':
    unittest.main()
