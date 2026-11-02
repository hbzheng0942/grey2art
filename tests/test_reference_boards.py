import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art/runtime'))
from greybox import core, modeling_refs, reference_boards as boards
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None


class ReferenceBoardPlanning(unittest.TestCase):
    def spec(self, aspect=1, **options):
        return {'schema': 1, 'kind': 'reference-board-plan-input', 'channel_size': [1536, 1536],
                'size_source_ref': 'synthetic actual channel size', 'views': [dict(asset_id='fence', view_id='front', role='front', projected_aspect=aspect, **options)]}

    def test_long_subject_uses_full_width_instead_of_nine_small_cells(self):
        result = boards.plan(self.spec(8, min_subject_long_edge_px=1024, min_subject_short_edge_px=128))
        board = result['boards'][0]
        self.assertEqual(board['template'], 'horizontal_strips')
        self.assertEqual(board['slots'][0]['estimated_subject_size'], [1228, 153])
        self.assertEqual(result['unresolved'], [])
        self.assertLess(int((1536 / 3 * .8) / 8), 128)

    def test_four_templates_and_no_unvalidated_nine_grid(self):
        self.assertEqual(boards.plan(self.spec())['boards'][0]['grid'], [2, 2])
        self.assertEqual(boards.plan(self.spec(.125))['boards'][0]['template'], 'vertical_columns')
        self.assertEqual(boards.plan(self.spec(requires_single=True))['boards'][0]['template'], 'single')
        self.assertEqual(boards.plan(self.spec(simple_shape_validated=True, min_subject_long_edge_px=350))['boards'][0]['grid'], [3, 3])

    def test_impossible_effective_pixels_are_not_fixed_by_single_or_upscale(self):
        spec = self.spec(20, min_subject_long_edge_px=1000, min_subject_short_edge_px=100)
        result = boards.plan(spec)
        self.assertFalse(result['boards'])
        self.assertEqual(len(result['unresolved']), 1)
        spec = self.spec(8, critical_feature_fraction_of_short_edge=.01, min_feature_px=12)
        self.assertEqual(len(boards.plan(spec)['unresolved']), 1)

    def test_order_and_multiview_identity_are_preserved(self):
        spec = self.spec(8)
        spec['views'] += [dict(spec['views'][0], view_id='back', role='back'), dict(spec['views'][0], asset_id='hero', requires_single=True)]
        result = boards.plan(spec)
        self.assertEqual([s['view_id'] for s in result['boards'][0]['slots']], ['front', 'back'])
        self.assertEqual(result, boards.plan(spec))

    def test_regular_pairs_fill_an_earlier_compatible_page_without_relaxing_dog_pixels(self):
        spec = self.spec()
        spec['channel_size'] = [1536, 1024]
        spec['views'] = [
            dict(asset_id='dog', view_id='rear', role='three_quarter', projected_aspect=1,
                 min_subject_long_edge_px=560, min_subject_short_edge_px=460),
            dict(asset_id='dog', view_id='side', role='left', projected_aspect=1.58,
                 min_subject_long_edge_px=620, min_subject_short_edge_px=390,
                 critical_feature_fraction_of_short_edge=.08, min_feature_px=31),
            dict(asset_id='dog', view_id='front', role='front', projected_aspect=.8,
                 min_subject_long_edge_px=430, min_subject_short_edge_px=340)]
        result = boards.plan(spec)
        self.assertEqual(result['summary']['estimated_generation_calls'], 2)
        self.assertEqual([board['grid'] for board in result['boards']], [[2, 1], [1, 2]])
        self.assertEqual([slot['view_id'] for slot in result['boards'][0]['slots']], ['rear', 'front'])
        self.assertEqual([slot['estimated_subject_size'] for slot in result['boards'][0]['slots']],
                         [[614, 614], [614, 768]])
        self.assertEqual(result['boards'][1]['slots'][0]['estimated_subject_size'], [647, 409])
        requirements = {(row['asset_id'], row['view_id']): boards._requirements(row) for row in spec['views']}
        for board in result['boards']:
            for slot in board['slots']:
                self.assertEqual(slot['requirements'], requirements[boards._identity(slot)])
                self.assertTrue(boards._passes(*slot['estimated_subject_size'], slot['requirements']))
        side = result['diagnostics'][1]
        two_columns = next(candidate for candidate in side['candidates'] if candidate['grid'] == [2, 1])
        self.assertFalse(two_columns['passes'])  # 614x388 does not become 620x390.
        self.assertIn('subject_short_edge', two_columns['failures'])

    def test_interleaved_subject_can_fill_an_earlier_page_without_delaying_priority(self):
        spec = self.spec(8)
        first = spec['views'][0]
        spec['views'] += [dict(first, asset_id='hero', requires_single=True),
                          dict(first, asset_id='second-fence')]
        result = boards.plan(spec)
        self.assertEqual(len(result['boards']), 2)
        self.assertEqual([slot['asset_id'] for slot in result['boards'][0]['slots']], ['fence', 'second-fence'])
        self.assertEqual(result['boards'][1]['slots'][0]['asset_id'], 'hero')

    def test_evidenced_dimensions_derive_width_over_height_and_allow_rounded_legacy_ratio(self):
        spec = self.spec()
        row = spec['views'][0]
        row.pop('projected_aspect')
        row['projected_dimensions'] = {'width': 1.15, 'height': .73, 'source_ref': 'synthetic measured projection'}
        result = boards.plan(spec)
        self.assertAlmostEqual(result['diagnostics'][0]['projected_aspect'], 1.15 / .73)
        self.assertEqual(result['diagnostics'][0]['projection_source_ref'], 'synthetic measured projection')
        row['projected_aspect'] = 1.58
        self.assertEqual(result['boards'], boards.plan(spec)['boards'])

    def test_dimensions_reject_inverted_or_unattributed_ratios(self):
        spec = self.spec(2.9)
        row = spec['views'][0]
        row['projected_dimensions'] = {'width': 1, 'height': 2.9, 'source_ref': 'synthetic front projection'}
        with self.assertRaisesRegex(ValueError, 'contradicts'):
            boards.plan(spec)
        row.pop('projected_aspect')
        for bad in ({'width': 1, 'height': 2.9},
                    {'width': True, 'height': 2.9, 'source_ref': 'synthetic'},
                    {'width': 1, 'height': 0, 'source_ref': 'synthetic'}):
            row['projected_dimensions'] = bad
            with self.subTest(dimensions=bad), self.assertRaises(ValueError):
                boards.plan(spec)

    def test_large_board_respects_modeling_master_limit_before_generation(self):
        spec = self.spec(requires_single=True, min_subject_long_edge_px=3000, min_subject_short_edge_px=3000)
        spec['channel_size'] = [4096, 4096]
        self.assertEqual(len(boards.plan(spec)['unresolved']), 1)
        spec['views'][0].update(min_subject_long_edge_px=2000, min_subject_short_edge_px=2000)
        result = boards.plan(spec)
        self.assertFalse(result['unresolved'])
        w, h = result['boards'][0]['slots'][0]['estimated_subject_size']
        self.assertLessEqual((w + 50) * (h + 50), boards.MAX_CROP_PIXELS)

    def test_stdlib_plan_cli_and_project_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            core.write(project / 'input.json', self.spec())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(boards.main(['plan', '--file', 'input.json', '--project', folder, '--output', 'layout.json']), 0)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(boards.main(['plan', '--file', 'input.json', '--project', folder, '--output', '../escape.json']), 2)
                self.assertEqual(boards.main(['plan', '--file', 'input.json', '--project', folder, '--output', 'input.json']), 2)

    def test_optional_dependency_failure_is_explicit(self):
        real_import = __import__
        def no_pillow(name, *args, **kwargs):
            if name == 'PIL': raise ImportError('synthetic missing dependency')
            return real_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=no_pillow):
            with self.assertRaisesRegex(ValueError, 'optional Pillow'):
                boards._pillow()


@unittest.skipIf(Image is None, 'Optional Pillow unavailable; planning still tested with stdlib')
class ReferenceBoardCrops(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        image = Image.new('RGB', (768, 384), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle([80, 80, 239, 239], fill=(50, 120, 180))
        draw.rectangle([464, 80, 623, 239], fill=(180, 80, 60))
        image.save(self.project / 'board.png')
        self.request = {'schema': 1, 'kind': 'reference-board-crop-request',
                        'selected_concept_sha256': 'a' * 64, 'board': self.ref('board.png'),
                        'asset_id': 'gate', 'view_id': 'front', 'role': 'front',
                        'roi': [32, 32, 288, 288], 'padding': 16,
                        'min_subject_long_edge_px': 128, 'min_subject_short_edge_px': 128,
                        'output': 'gate-v1.png', 'receipt_output': 'gate-v1.crop.json'}
        self.generation = {'schema': 1, 'kind': 'reference-image-generation-receipt', 'tool': 'synthetic-fixture-no-cloud',
                           'actual_input_image_sha256': ['a' * 64], 'output_sha256': self.request['board']['sha256'],
                           'invocation_recorded': True, 'source_ref': 'synthetic invocation fixture'}
        self.receipt()

    def ref(self, name):
        return {'path': name, 'sha256': core.file_hash(self.project / name)}

    def receipt(self):
        core.write(self.project / 'board.invocation.json', self.generation)
        self.request['generation_receipt'] = self.ref('board.invocation.json')

    def run_crop(self, request=None):
        return boards.crop(request or self.request, self.project)

    def test_roundtrip_binds_one_invocation_and_keeps_single_master_qa(self):
        result = self.run_crop()
        verified = boards.validate_crop_receipt(result['board_crop_receipt'], self.project, asset_id='gate', view_id='front', role='front', concept='a'*64)
        self.assertEqual(len(verified['dependencies']), 4)
        view = {'id': 'front', 'role': 'front', **{k: result[k] for k in ('image', 'origin', 'board_crop_receipt')}}
        review = {'actor': 'agent', 'note': 'synthetic fixture, not production aesthetic evidence', 'images_digest': core.digest([view]),
                  'criteria': {k: True for k in modeling_refs.CRITERIA}}
        package = {'schema': 1, 'kind': 'modeling-reference-package', 'policy': modeling_refs.POLICY,
                   'style_id': 'paper', 'selected_concept_sha256': 'a'*64,
                   'assets': [{'asset_id': 'gate', 'mode': 'single', 'views': [view], 'review': review}]}
        self.assertTrue(modeling_refs.validate_package(package, self.project)['ok'])
        review['criteria']['complete_silhouette'] = False
        with self.assertRaisesRegex(ValueError, 'checks'):
            modeling_refs.validate_package(package, self.project)

    def test_outside_or_truncated_silhouette_and_insufficient_pixels_rejected(self):
        for roi in ([-1, 0, 256, 256], [0, 0, 900, 300], [128, 32, 384, 288]):
            with self.assertRaisesRegex(ValueError, 'bounds|truncated'):
                self.run_crop(dict(self.request, roi=roi))
        with self.assertRaisesRegex(ValueError, 'pixel requirements'):
            self.run_crop(dict(self.request, min_subject_long_edge_px=200))
        self.assertFalse((self.project / self.request['output']).exists())

    def test_inspection_crop_preserves_pixels_but_cannot_qualify_as_a_master(self):
        request = dict(self.request, qualification_mode='inspection', min_subject_long_edge_px=200)
        result = self.run_crop(request)
        self.assertFalse(result['technical_pass'])
        verified = boards.validate_crop_receipt(result['board_crop_receipt'], self.project, require_qualified=False)
        self.assertFalse(verified['technical_pass'])
        self.assertIn('subject_pixels', {row['code'] for row in verified['qualification_failures']})
        with Image.open(self.project / result['image']['path']) as output, Image.open(self.project / 'board.png') as source:
            restored = output.crop((16, 16, 272, 272))
            self.assertEqual(restored.tobytes(), source.crop(tuple(request['roi'])).tobytes())
        with self.assertRaisesRegex(ValueError, 'inspection evidence only'):
            boards.validate_crop_receipt(result['board_crop_receipt'], self.project)
        view = {'id': 'front', 'role': 'front', **{k: result[k] for k in ('image', 'origin', 'board_crop_receipt')}}
        package = {'schema': 1, 'kind': 'modeling-reference-package', 'policy': modeling_refs.POLICY,
                   'style_id': 'paper', 'selected_concept_sha256': 'a' * 64,
                   'assets': [{'asset_id': 'gate', 'mode': 'single', 'views': [view], 'review': {
                       'actor': 'agent', 'note': 'synthetic inspection declaration', 'images_digest': core.digest([view]),
                       'criteria': {k: True for k in modeling_refs.CRITERIA}}}]}
        with self.assertRaisesRegex(ValueError, 'inspection evidence only'):
            modeling_refs.validate_package(package, self.project)
        source_review = {'image_sha256': result['image']['sha256'], 'asset_id': 'gate', 'view_id': 'front',
                         'verdict': 'pass', 'observation': 'Synthetic written pass cannot override insufficient pixels.',
                         'source_ref': 'synthetic inspection', 'board_crop_receipt': result['board_crop_receipt']}
        core.write(self.project / 'source-review.json', source_review)
        role = {'asset_id': 'gate', 'source_view_id': 'front', 'source_review': self.ref('source-review.json')}
        with self.assertRaisesRegex(ValueError, 'inspection evidence only'):
            boards._identity_master_review(role, result['image'], self.project, {})

    def test_identity_master_crop_receipt_cannot_certify_another_image(self):
        result = self.run_crop()
        image = self.ref('board.png')
        source_review = {'image_sha256': image['sha256'], 'asset_id': 'gate', 'view_id': 'front',
                         'verdict': 'pass', 'observation': 'Synthetic source review points at the wrong full-board image.',
                         'source_ref': 'synthetic inspection', 'board_crop_receipt': result['board_crop_receipt']}
        core.write(self.project / 'source-review.json', source_review)
        role = {'asset_id': 'gate', 'source_view_id': 'front', 'source_review': self.ref('source-review.json')}
        with self.assertRaisesRegex(ValueError, 'this exact source image'):
            boards._identity_master_review(role, image, self.project, {})

    def test_h3_review_keeps_large_board_and_small_master_separate(self):
        from greybox import pre_handoff
        image = Image.new('RGB', (4096, 2304), 'white')
        ImageDraw.Draw(image).rectangle([80, 80, 239, 239], fill=(50, 120, 180))
        image.save(self.project / 'board.png')
        self.request['board'] = self.ref('board.png')
        self.generation['output_sha256'] = self.request['board']['sha256']
        self.receipt()
        result = self.run_crop()
        view = {'id': 'front', 'role': 'front', **{k: result[k] for k in ('image', 'origin', 'board_crop_receipt')}}
        package = {'schema': 1, 'kind': 'modeling-reference-package', 'policy': modeling_refs.POLICY,
                   'style_id': 'paper', 'selected_concept_sha256': 'a'*64,
                   'assets': [{'asset_id': 'gate', 'mode': 'single', 'views': [view], 'review': {
                       'actor': 'agent', 'note': 'SYNTHETIC ONLY', 'images_digest': core.digest([view]),
                       'criteria': {k: True for k in modeling_refs.CRITERIA}}}]}
        core.write(self.project / 'refs.json', package)
        core.write(self.project / 'table.json', {'modeling_references': self.ref('refs.json')})
        stage = {'id': 'production_plan', 'scope': 'paper', 'consumes': {},
                 'evidence': [dict(self.ref('table.json'), role='production_table')]}
        inputs = pre_handoff.review_inputs({'stages': [stage]}, self.project, stage)
        board = next(a for a in inputs['artifacts'] if a['role'] == 'modeling_reference_board')
        self.assertEqual(board['dimensions'], [4096, 2304])
        self.assertTrue(any(a['role'] == 'modeling_reference' for a in inputs['artifacts']))

    def test_wrong_hash_and_wrong_board_invocation_rejected(self):
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.run_crop(dict(self.request, board={'path': 'board.png', 'sha256': 'b'*64}))
        self.generation['output_sha256'] = 'b'*64
        self.receipt()
        with self.assertRaisesRegex(ValueError, 'invocation'):
            self.run_crop()

    def test_source_overwrite_and_symlink_escape_rejected(self):
        for output in ('board.png', 'board.invocation.json', '../escaped.png'):
            with self.assertRaises(ValueError):
                self.run_crop(dict(self.request, output=output))
        (self.project / 'board-alias.png').hardlink_to(self.project / 'board.png')
        with self.assertRaisesRegex(ValueError, 'canonical'):
            self.run_crop(dict(self.request, output='board-alias.png'))

    def test_changed_board_invalidates_older_crop_even_if_new_receipt_is_written(self):
        result = self.run_crop()
        Image.new('RGB', (768, 384), 'white').save(self.project / 'board.png')
        with self.assertRaisesRegex(ValueError, 'changed'):
            boards.validate_crop_receipt(result['board_crop_receipt'], self.project)

    def test_recipe_and_output_pixels_are_replayed(self):
        result = self.run_crop()
        receipt_path = self.project / result['board_crop_receipt']['path']
        receipt = core.read(receipt_path)
        receipt['recipe']['roi'] = [416, 32, 672, 288]
        receipt['recipe_digest'] = core.digest(receipt['recipe'])
        core.write(receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, 'measurements|bytes'):
            boards.validate_crop_receipt(self.ref(receipt_path.name), self.project)

    def test_bad_item_does_not_modify_good_sibling_and_identical_rerun_is_noop(self):
        first = self.run_crop()
        image = self.project / first['image']['path']
        stat = image.stat()
        self.assertEqual(first, self.run_crop())
        self.assertEqual(stat.st_mtime_ns, image.stat().st_mtime_ns)
        bad = dict(self.request, asset_id='other', output='other-v1.png', receipt_output='other-v1.crop.json', roi=[500, 32, 756, 288])
        with self.assertRaisesRegex(ValueError, 'truncated'):
            self.run_crop(bad)
        self.assertEqual(core.file_hash(image), first['image']['sha256'])
        good = dict(bad, roi=[416, 32, 672, 288])
        second = self.run_crop(good)
        self.assertNotEqual(first['image']['sha256'], second['image']['sha256'])
        self.assertEqual(core.file_hash(image), first['image']['sha256'])
        changed = dict(self.request, roi=[416, 32, 672, 288])
        with self.assertRaisesRegex(ValueError, 'different content'):
            self.run_crop(changed)

    def test_exif_orientation_is_applied_before_roi_and_recorded(self):
        image = Image.new('RGB', (384, 512), 'white')
        ImageDraw.Draw(image).rectangle([80, 80, 239, 319], fill=(50, 120, 180))
        exif = image.getexif(); exif[274] = 6
        image.save(self.project / 'board.png', exif=exif)
        self.request['board'] = self.ref('board.png')
        self.generation['output_sha256'] = self.request['board']['sha256']; self.receipt()
        self.request['roi'] = [160, 32, 448, 288]
        result = self.run_crop()
        receipt = core.read(self.project / result['board_crop_receipt']['path'])
        self.assertEqual(receipt['source'], {'original_size': [384, 512], 'oriented_size': [512, 384], 'exif_orientation': 6})
        self.assertTrue(boards.validate_crop_receipt(result['board_crop_receipt'], self.project)['ok'])

    def test_truncated_image_rejected_before_any_write(self):
        path = self.project / 'board.png'; path.write_bytes(path.read_bytes()[:-1])
        self.request['board'] = self.ref('board.png')
        self.generation['output_sha256'] = self.request['board']['sha256']; self.receipt()
        with self.assertRaises(ValueError):
            self.run_crop()
        self.assertFalse((self.project / self.request['output']).exists())


if __name__ == '__main__':
    unittest.main()
