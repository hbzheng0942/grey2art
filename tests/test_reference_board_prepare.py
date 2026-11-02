"""Offline preparation behavior; synthetic images never certify artistic quality."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art/runtime'))
from greybox import core, image_jobs, reference_boards as boards
try:
    from PIL import Image
except ImportError:
    Image = None


class PlanningDiagnostics(unittest.TestCase):
    def test_actual_aspect_and_short_edge_allow_a_pair_before_single_fallback(self):
        spec = {'schema': 1, 'kind': 'reference-board-plan-input', 'channel_size': [1536, 1024],
                'size_source_ref': 'synthetic actual size', 'views': [
                    {'asset_id': 'counter', 'view_id': 'front', 'role': 'front', 'projected_aspect': 1.19,
                     'min_subject_long_edge_px': 512, 'min_subject_short_edge_px': 420}]}
        result = boards.plan(spec)
        diagnostic = result['diagnostics'][0]
        two = next(c for c in diagnostic['candidates'] if c['grid'] == [2, 2])
        self.assertEqual(two['estimated_subject_size'], [487, 409])
        self.assertIn('subject_short_edge', two['failures'])
        self.assertEqual(diagnostic['selected'], [2, 1])
        pair = next(c for c in diagnostic['candidates'] if c['grid'] == [2, 1])
        self.assertTrue(pair['passes'])
        self.assertEqual(result['summary']['estimated_generation_calls'], 1)
        # 409px is the height limit, not a universal long-edge limit.
        spec['views'][0].update(projected_aspect=1.4, min_subject_short_edge_px=128)
        result = boards.plan(spec)
        self.assertEqual(result['boards'][0]['grid'], [2, 2])
        self.assertEqual(result['boards'][0]['slots'][0]['estimated_subject_size'], [573, 409])


@unittest.skipIf(Image is None, 'Optional Pillow unavailable')
class BoardPreparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        Image.new('RGB', (40, 40), (70, 140, 190)).save(self.project / 'style.png')
        self.spec = self.make_spec(9)

    def ref(self, name):
        return {'path': name, 'sha256': core.file_hash(self.project / name)}

    def make_spec(self, count):
        rows = []
        objects = []
        for i in range(count):
            aid = f'object-{i}'
            rows.append({'asset_id': aid, 'view_id': 'front', 'role': 'front', 'projected_aspect': 1,
                         'simple_shape_validated': True, 'min_subject_long_edge_px': 150,
                         'min_subject_short_edge_px': 120})
            objects.append({'asset_id': aid, 'view_id': 'front', 'category': 'prop',
                            'function': 'Independent gameplay prop', 'appearance': f'blue ceramic design {i}',
                            'structure': 'Complete rounded box with open handle; nominal width 1.50 m'})
        return {'schema': 1, 'kind': 'reference-board-prepare-input', 'purpose': 'modeling',
                'plan': {'schema': 1, 'kind': 'reference-board-plan-input', 'channel_size': [1536, 1024],
                         'size_source_ref': 'synthetic observed output', 'views': rows},
                'images': [self.ref('style.png')], 'objects': objects,
                'capabilities': {'edit': True, 'max_references': 2, 'source_ref': 'synthetic host tool schema'},
                'parameters': {}}

    def prepare(self, spec=None, folder='prepared'):
        return boards.prepare(spec or self.spec, self.project, folder)

    def request(self, result, page=0):
        return core.read(self.project / result['prepared'][page]['request']['path'])

    def prompt_subjects(self, result, page=0):
        request = self.request(result, page)
        prompt_file = self.project / result['prepared'][page]['prompt']['path']
        self.assertEqual(request['prompt'], prompt_file.read_text(encoding='utf-8'))
        return [json.loads(line.split(': ', 1)[1]) for line in request['prompt'].splitlines()
                if line.startswith('Slot ')]

    def masters(self, identities):
        self.spec.setdefault('image_roles', [{'role': 'style'}])
        for i, (asset_id, view_id) in enumerate(identities):
            name = f'master-{len(self.spec["images"])}.png'
            Image.new('RGB', (40, 40), (20 + len(self.spec['images']), 80 + i, 160)).save(self.project / name)
            self.spec['images'].append(self.ref(name))
            self.spec['image_roles'].append({'role': 'design_master', 'asset_id': asset_id, 'view_id': view_id})

    def test_nine_objects_become_one_edit_request_with_ordered_actual_inputs(self):
        result = self.prepare()
        self.assertEqual(len(result['prepared']), 1)
        page = result['prepared'][0]
        request = self.request(result)
        self.assertEqual(request['operation'], 'edit')
        self.assertEqual(request['images'][0], self.spec['images'][0])
        self.assertEqual(request['images'][1], page['guide'])
        self.assertEqual(len(page['slots']), 9)
        for i in range(9):
            self.assertIn(f'"asset_id": "object-{i}"', request['prompt'])
        self.assertIn('nominal width 1.50 m', request['prompt'])
        self.assertEqual(request['parameters'], {})  # native tools need no invented size parameter
        image_jobs.configure('synthetic', {'kind': 'openai', 'base_url': 'https://example.invalid/v1',
                             'model': 'synthetic-model', 'credential_env': 'SYNTHETIC_IMAGE_KEY'}, self.project / 'profiles')
        validated = image_jobs.validate('synthetic', request, config_dir=self.project / 'profiles', base=self.project)
        self.assertEqual(validated['input_image_sha256'], [r['sha256'] for r in request['images']])
        self.assertFalse(validated['network'])

    def test_capacity_failure_does_not_drop_inputs_and_explicit_no_guide_works(self):
        self.spec['capabilities']['max_references'] = 1
        with self.assertRaisesRegex(ValueError, 'capacity'):
            self.prepare()
        self.assertFalse((self.project / 'prepared').exists())
        self.spec['capabilities']['layout_guide'] = False
        result = self.prepare()
        self.assertNotIn('guide', result['prepared'][0])
        self.assertEqual(self.request(result)['images'], self.spec['images'])
        self.assertIn('3 column by 3 row', self.request(result)['prompt'])

    def test_global_master_count_is_not_the_per_page_reference_limit(self):
        self.spec = self.make_spec(2)
        for row in self.spec['plan']['views']:
            row['requires_single'] = True
        self.masters([('object-0', 'front'), ('object-1', 'front')])
        self.spec['capabilities']['max_references'] = 3
        result = self.prepare()
        self.assertEqual(len(result['prepared']), 2)
        for i, page in enumerate(result['prepared']):
            request = self.request(result, i)
            self.assertEqual(request['images'], [self.spec['images'][0], self.spec['images'][i + 1], page['guide']])
            self.assertEqual([role['role'] for role in page['input_roles']], ['style', 'design_master', 'layout_guide'])

    def test_nine_masters_split_into_compact_pages_without_omitting_a_master(self):
        self.masters([(f'object-{i}', 'front') for i in range(9)])
        self.spec['capabilities']['max_references'] = 4  # style + two masters + guide
        result = self.prepare()
        self.assertEqual([len(page['slots']) for page in result['prepared']], [2, 2, 2, 2, 1])
        self.assertEqual(result['summary']['estimated_generation_calls'], 5)
        self.assertEqual(result['summary']['single_boards'], 1)
        actual_master_hashes = []
        for i, page in enumerate(result['prepared']):
            request = self.request(result, i)
            self.assertLessEqual(len(request['images']), 4)
            self.assertEqual(request['images'][0], self.spec['images'][0])
            self.assertEqual(request['images'][-1], page['guide'])
            actual_master_hashes += [r['sha256'] for r, role in zip(request['images'], page['input_roles']) if role['role'] == 'design_master']
            self.assertTrue(all(min(slot['estimated_subject_size']) >= 409 for slot in page['slots']))
        self.assertEqual(actual_master_hashes, [r['sha256'] for r in self.spec['images'][1:]])
        layout = core.read(self.project / result['layout']['path'])
        self.assertEqual([board['grid'] for board in layout['boards']], [[2, 1]] * 4 + [[1, 1]])
        self.assertEqual(len(layout['reference_capacity_adjustments']), 1)

    def test_alias_master_is_retained_for_the_canonical_generated_view(self):
        self.spec = self.make_spec(2)
        for row in self.spec['plan']['views']:
            row['model_source'] = 'same-approved-design'
        self.spec['objects'][1] = dict(self.spec['objects'][0], asset_id='object-1')
        self.masters([('object-1', 'front')])
        self.spec['capabilities']['max_references'] = 3
        result = self.prepare()
        self.assertEqual(len(result['prepared'][0]['slots']), 1)
        self.assertEqual(result['prepared'][0]['slots'][0]['asset_id'], 'object-0')
        self.assertEqual(self.request(result)['images'][1], self.spec['images'][1])
        self.assertIn('alias shares the exact model with object-0 / front', self.request(result)['prompt'])

    def test_one_over_budget_view_does_not_block_independent_ready_views(self):
        self.spec = self.make_spec(2)
        self.masters([('object-0', 'front'), ('object-0', 'front'), ('object-1', 'front')])
        self.spec['capabilities']['max_references'] = 3
        result = self.prepare()
        self.assertEqual(len(result['prepared']), 1)
        self.assertEqual(result['prepared'][0]['slots'][0]['asset_id'], 'object-1')
        self.assertEqual(result['unresolved'][0]['asset_id'], 'object-0')
        self.assertEqual(result['unresolved'][0]['required_references'], 4)
        self.assertEqual(self.request(result)['images'][1], self.spec['images'][3])

    def test_impossible_view_does_not_block_ready_pages(self):
        bad = dict(self.spec['plan']['views'][0], asset_id='too-thin', projected_aspect=20,
                   min_subject_long_edge_px=1000, min_subject_short_edge_px=100)
        self.spec['plan']['views'].append(bad)
        self.spec['objects'].append(dict(self.spec['objects'][0], asset_id='too-thin'))
        result = self.prepare()
        self.assertEqual(len(result['prepared']), 1)
        self.assertEqual(result['unresolved'][0]['asset_id'], 'too-thin')
        self.assertEqual(result['summary']['estimated_generation_calls'], 1)

    def test_exploration_purpose_does_not_relax_declared_pixels_or_nine_grid_qualification(self):
        self.spec['purpose'] = 'exploration'
        for row in self.spec['plan']['views']:
            row.update(min_subject_long_edge_px=512, min_subject_short_edge_px=420, simple_shape_validated=False)
        result = self.prepare()
        self.assertEqual(len(result['prepared']), 5)
        self.assertEqual([len(page['slots']) for page in result['prepared']], [2, 2, 2, 2, 1])
        self.assertTrue(all(slot['requirements']['min_subject_short_edge_px'] == 420
                            for page in result['prepared'] for slot in page['slots']))
        self.assertEqual(self.request(result)['purpose'], 'reference-exploration')

    def test_same_asset_multiple_views_keep_distinct_descriptions(self):
        self.spec = self.make_spec(1)
        self.spec['plan']['views'].append(dict(self.spec['plan']['views'][0], view_id='back', role='back'))
        self.spec['objects'].append(dict(self.spec['objects'][0], view_id='back', appearance='red back panel with hidden latch'))
        result = self.prepare()
        text = self.request(result)['prompt']
        self.assertIn('blue ceramic design 0', text)
        self.assertIn('red back panel with hidden latch', text)
        self.assertEqual([slot['view_id'] for slot in result['prepared'][0]['slots']], ['front', 'back'])

    def test_only_identical_explicit_model_sources_deduplicate(self):
        self.spec = self.make_spec(2)
        for row in self.spec['plan']['views']:
            row['model_source'] = 'canonical-model-revision-one'
        self.spec['objects'][1] = dict(self.spec['objects'][0], asset_id='object-1')
        result = self.prepare()
        self.assertEqual(len(result['prepared'][0]['slots']), 1)
        self.assertEqual(result['aliases'][0]['source_asset_id'], 'object-0')
        changed = copy.deepcopy(self.spec)
        changed['objects'][1]['structure'] = 'different front opening'
        result = self.prepare(changed, folder='changed')
        self.assertEqual(len(result['prepared'][0]['slots']), 2)
        self.assertEqual(result['aliases'], [])
        self.assertEqual(len(result['model_source_conflicts']), 1)

    def test_animal_species_and_skeletal_pose_are_explicit(self):
        self.spec = self.make_spec(1)
        animal = self.spec['objects'][0]
        animal['category'] = 'animal'
        with self.assertRaisesRegex(ValueError, 'species'):
            self.prepare()
        animal['species'] = 'puppy dog'
        animal['modeling_contract'] = {'category': 'animal', 'use': 'skeletal_animation', 'pose': 'T',
                                       'pose_details': 'legs separated'}
        with self.assertRaisesRegex(ValueError, 'anatomy'):
            self.prepare()
        animal['modeling_contract']['pose'] = 'natural_stance'
        result = self.prepare()
        self.assertIn('puppy dog', self.request(result)['prompt'])
        self.assertIn('natural_stance', self.request(result)['prompt'])

    def test_design_master_role_binds_exact_asset_view(self):
        self.spec = self.make_spec(1)
        self.spec['image_roles'] = [{'role': 'design_master', 'asset_id': 'object-0', 'view_id': 'front'}]
        result = self.prepare()
        self.assertIn('exact design master for object-0 / front', self.request(result)['prompt'])
        self.spec['image_roles'][0]['asset_id'] = 'not-planned'
        with self.assertRaisesRegex(ValueError, 'bind'):
            self.prepare(folder='bad')

    def test_identity_master_from_an_unplanned_source_view_reaches_every_explicit_target(self):
        self.spec = self.make_spec(1)
        self.spec['plan']['views'][0]['requires_single'] = True
        self.spec['plan']['views'].append(dict(self.spec['plan']['views'][0], view_id='left', role='left'))
        self.spec['objects'].append(dict(self.spec['objects'][0], view_id='left', role='left',
                                         appearance='The same blue ceramic object seen from the left'))
        Image.new('RGB', (40, 40), (110, 80, 160)).save(self.project / 'rear-master.png')
        self.spec['images'].append(self.ref('rear-master.png'))
        self.spec['image_roles'] = [{'role': 'style'}, {'role': 'identity_master', 'asset_id': 'object-0',
            'source_view_id': 'rear_three_quarter', 'target_view_ids': ['front', 'left']}]
        self.spec['capabilities']['max_references'] = 3
        result = self.prepare()
        self.assertEqual(len(result['prepared']), 2)
        self.assertNotIn('rear_three_quarter', [row['view_id'] for row in self.spec['plan']['views']])
        for index, page in enumerate(result['prepared']):
            request = self.request(result, index)
            self.assertEqual(request['images'], [*self.spec['images'], page['guide']])
            self.assertEqual([role['role'] for role in page['input_roles']], ['style', 'identity_master', 'layout_guide'])
            self.assertIn('actual source view rear_three_quarter', request['prompt'])
            self.assertIn('target views ' + page['slots'][0]['view_id'], request['prompt'])
            self.assertIn('source view is not a label for the requested output view', request['prompt'])

    def test_identity_master_capacity_never_drops_the_master_or_blocks_other_assets(self):
        self.spec = self.make_spec(2)
        for row in self.spec['plan']['views']:
            row['requires_single'] = True
        Image.new('RGB', (40, 40), (110, 80, 160)).save(self.project / 'rear-master.png')
        self.spec['images'].append(self.ref('rear-master.png'))
        self.spec['image_roles'] = [{'role': 'style'}, {'role': 'identity_master', 'asset_id': 'object-0',
            'source_view_id': 'rear', 'target_view_ids': ['front']}]
        result = self.prepare()
        self.assertEqual([slot['asset_id'] for page in result['prepared'] for slot in page['slots']], ['object-1'])
        self.assertEqual(result['unresolved'][0]['asset_id'], 'object-0')
        self.assertEqual(result['unresolved'][0]['required_references'], 3)
        self.assertEqual(self.request(result)['images'], [self.spec['images'][0], result['prepared'][0]['guide']])
        self.spec['capabilities']['layout_guide'] = False
        result = self.prepare(folder='without-guide')
        self.assertEqual(result['unresolved'], [])
        self.assertEqual(self.request(result)['images'], self.spec['images'])

    def test_identity_master_target_binding_and_source_identity_are_not_inferred(self):
        self.spec = self.make_spec(1)
        self.spec['image_roles'] = [{'role': 'identity_master', 'asset_id': 'object-0',
                                    'source_view_id': 'rear', 'target_view_ids': ['front']}]
        self.assertIn('identity master', self.request(self.prepare())['prompt'])
        for change in ({'target_view_ids': []}, {'target_view_ids': ['front', 'front']},
                       {'target_view_ids': ['left']}, {'asset_id': 'another-object'}, {'source_view_id': ''}):
            invalid = copy.deepcopy(self.spec)
            invalid['image_roles'][0].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'identity_master'):
                self.prepare(invalid, folder='invalid')

    def test_identity_master_source_review_rejects_failed_unclear_wrong_and_stale_evidence(self):
        self.spec = self.make_spec(1)
        role = {'role': 'identity_master', 'asset_id': 'object-0', 'source_view_id': 'rear',
                'target_view_ids': ['front']}
        self.spec['image_roles'] = [role]
        review = {'image_sha256': self.spec['images'][0]['sha256'], 'asset_id': 'object-0', 'view_id': 'rear',
                  'status': 'pass', 'observation': 'The ceramic body and open handle are complete and separated.',
                  'source_ref': 'synthetic pixel inspection, not actual production qualification'}
        core.write(self.project / 'master-review.json', review)
        role['source_review'] = self.ref('master-review.json')
        self.assertEqual(len(self.prepare()['prepared']), 1)
        for change in ({'status': 'fail'}, {'status': 'unclear'}, {'verdict': 'fail'},
                       {'image_sha256': 'a' * 64}, {'asset_id': 'another-asset'}, {'view_id': 'front'},
                       {'observation': ''}, {'source_ref': ''}):
            rejected = dict(review, **change)
            core.write(self.project / 'master-review.json', rejected)
            role['source_review'] = self.ref('master-review.json')
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'source review'):
                self.prepare(folder='rejected')
        core.write(self.project / 'master-review.json', review)
        role['source_review'] = self.ref('master-review.json')
        core.write(self.project / 'master-review.json', dict(review, observation='Changed after binding'))
        with self.assertRaisesRegex(ValueError, 'changed|hash'):
            self.prepare(folder='stale')

    def test_identity_master_review_accepts_verdict_only_but_never_an_absent_result(self):
        self.spec = self.make_spec(1)
        role = {'role': 'identity_master', 'asset_id': 'object-0', 'source_view_id': 'rear',
                'target_view_ids': ['front']}
        self.spec['image_roles'] = [role]
        review = {'image_sha256': self.spec['images'][0]['sha256'], 'asset_id': 'object-0', 'view_id': 'rear',
                  'verdict': 'pass', 'observation': 'The full body and handle gaps remain visible.',
                  'source_ref': 'synthetic observed review'}
        core.write(self.project / 'review.json', review)
        role['source_review'] = self.ref('review.json')
        self.assertEqual(len(self.prepare()['prepared']), 1)
        review.pop('verdict')
        core.write(self.project / 'review.json', review)
        role['source_review'] = self.ref('review.json')
        with self.assertRaisesRegex(ValueError, 'source review must pass'):
            self.prepare(folder='without-result')

    def test_identity_master_for_an_alias_stays_bound_to_the_canonical_view(self):
        self.spec = self.make_spec(2)
        for row in self.spec['plan']['views']:
            row['model_source'] = 'one-approved-model'
        self.spec['objects'][1] = dict(self.spec['objects'][0], asset_id='object-1')
        self.spec['image_roles'] = [{'role': 'identity_master', 'asset_id': 'object-1',
                                    'source_view_id': 'rear', 'target_view_ids': ['front']}]
        result = self.prepare()
        self.assertEqual(result['prepared'][0]['slots'][0]['asset_id'], 'object-0')
        self.assertEqual(len(result['prepared'][0]['slots']), 1)
        self.assertEqual(self.request(result)['images'][0], self.spec['images'][0])
        self.assertIn('identity master for object-1 from actual source view rear', self.request(result)['prompt'])

    def test_prepare_derives_projection_dimensions_and_compacts_wide_pairs_safely(self):
        self.spec = self.make_spec(2)
        for row in self.spec['plan']['views']:
            row.pop('projected_aspect')
            row.update(projected_dimensions={'width': 1.58, 'height': 1, 'source_ref': 'synthetic side projection'},
                       simple_shape_validated=False, min_subject_long_edge_px=620, min_subject_short_edge_px=390)
        result = self.prepare()
        layout = core.read(self.project / result['layout']['path'])
        self.assertEqual(layout['boards'][0]['grid'], [1, 2])
        for slot in layout['boards'][0]['slots']:
            self.assertEqual(slot['estimated_subject_size'], [647, 409])
            self.assertTrue(boards._passes(*slot['estimated_subject_size'], slot['requirements']))

    def test_actual_prompt_carries_frozen_projection_evidence_and_all_pixel_requirements(self):
        self.spec = self.make_spec(1)
        planned = self.spec['plan']['views'][0]
        planned.update(projected_aspect=1.58,
                       projected_dimensions={'width': 1.15, 'height': .73, 'source_ref': 'measured-side-projection-17'},
                       min_subject_long_edge_px=620, min_subject_short_edge_px=390,
                       critical_feature_fraction_of_short_edge=.08, min_feature_px=31)
        result = self.prepare()
        subject, = self.prompt_subjects(result)
        self.assertAlmostEqual(subject['projected_aspect'], 1.15 / .73)
        self.assertEqual(subject['projected_dimensions'], planned['projected_dimensions'])
        self.assertEqual(subject['pixel_requirements'], {
            'min_subject_long_edge_px': 620, 'min_subject_short_edge_px': 390,
            'critical_feature_fraction_of_short_edge': .08, 'min_feature_px': 31})
        self.assertEqual(subject['estimated_subject_size'], result['prepared'][0]['slots'][0]['estimated_subject_size'])
        self.assertIn('nominal width 1.50 m', subject['structure'])
        self.assertNotIn('measured-side-projection-17', subject['appearance'])
        prompt = self.request(result)['prompt']
        self.assertIn('view-specific projection estimates', prompt)
        self.assertIn('not nominal 3D world dimensions', prompt)
        self.assertIn('without stretching', prompt)

    def test_handwritten_subject_fields_cannot_override_frozen_projection_or_pixel_values(self):
        self.spec = self.make_spec(1)
        description = self.spec['objects'][0]
        description.update(projected_aspect=99,
                           projected_dimensions={'width': 99, 'height': 1, 'source_ref': 'invented-object-source'},
                           projection_source_ref='invented-object-source', pixel_requirements={'min_feature_px': 1},
                           requirements={'min_subject_long_edge_px': 1}, estimated_subject_size=[1, 1],
                           min_subject_long_edge_px=1, min_subject_short_edge_px=1,
                           critical_feature_fraction_of_short_edge=.001, min_feature_px=1)
        result = self.prepare()
        subject, = self.prompt_subjects(result)
        slot = result['prepared'][0]['slots'][0]
        self.assertEqual(subject['projected_aspect'], 1)
        self.assertNotIn('projected_dimensions', subject)
        self.assertNotIn('projection_source_ref', subject)
        self.assertNotIn('requirements', subject)
        self.assertEqual(subject['pixel_requirements'], slot['requirements'])
        self.assertEqual(subject['estimated_subject_size'], slot['estimated_subject_size'])
        for key in boards._requirements(self.spec['plan']['views'][0]):
            self.assertNotIn(key, subject)
        self.assertNotIn('invented-object-source', self.request(result)['prompt'])

    def test_actual_multiview_prompts_keep_their_own_projection_and_compacted_occupancy(self):
        self.spec = self.make_spec(1)
        front = self.spec['plan']['views'][0]
        front.update(requires_single=True,
                     projected_aspect=.5,
                     projected_dimensions={'width': 1, 'height': 2, 'source_ref': 'front-projection'})
        side = dict(front, view_id='left', role='left', projected_aspect=2,
                    projected_dimensions={'width': 2, 'height': 1, 'source_ref': 'left-projection'})
        self.spec['plan']['views'].append(side)
        self.spec['objects'].append(dict(self.spec['objects'][0], view_id='left', role='left'))
        result = self.prepare()
        self.assertEqual(len(result['prepared']), 2)
        for index, planned in enumerate((front, side)):
            subject, = self.prompt_subjects(result, index)
            self.assertEqual(subject['view_id'], planned['view_id'])
            self.assertEqual(subject['projected_aspect'], planned['projected_aspect'])
            self.assertEqual(subject['projected_dimensions'], planned['projected_dimensions'])
            self.assertEqual(subject['estimated_subject_size'], result['prepared'][index]['slots'][0]['estimated_subject_size'])

    def test_explicit_placeholder_fields_are_blocked_but_descriptive_prose_is_allowed(self):
        self.spec = self.make_spec(1)
        for field in ('appearance', 'structure'):
            for text in ('Placeholder', ' TODO ', 'TBD.', '[TODO]: design the handle'):
                invalid = copy.deepcopy(self.spec)
                invalid['objects'][0][field] = text
                with self.subTest(field=field, text=text), self.assertRaisesRegex(ValueError, 'placeholder'):
                    self.prepare(invalid, folder='invalid')
        invalid = copy.deepcopy(self.spec)
        invalid['objects'][0]['modeling_contract'] = {'category': 'prop', 'use': 'static', 'structure': 'TBD'}
        with self.assertRaisesRegex(ValueError, 'placeholder'):
            self.prepare(invalid, folder='invalid')
        self.spec['objects'][0]['appearance'] = 'A blue ceramic box replacing the old greybox placeholder; its label reads TODO.'
        self.spec['objects'][0]['structure'] = 'A complete hollow body; TBD is intentional printed lettering, not missing geometry.'
        self.assertEqual(len(self.prepare()['prepared']), 1)

    def test_bad_or_changed_inputs_and_output_escape_are_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec['images'][0]['sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'changed|hash'):
            self.prepare(spec)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            self.prepare(folder='../escape')
        self.spec['objects'].append(self.spec['objects'][0])
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            self.prepare()

    def test_existing_preparation_is_immutable_and_identical_rerun_is_noop(self):
        first = self.prepare()
        manifest = self.project / first['manifest']['path']
        before = manifest.stat().st_mtime_ns
        self.assertEqual(first, self.prepare())
        self.assertEqual(manifest.stat().st_mtime_ns, before)
        self.spec['objects'][0]['appearance'] = 'new visual design'
        with self.assertRaisesRegex(ValueError, 'different content'):
            self.prepare()
        self.assertEqual(manifest.stat().st_mtime_ns, before)

    def test_one_page_cannot_request_multiple_outputs(self):
        self.spec['parameters']['n'] = 2
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            self.prepare()

    def test_cli_writes_preparation_outside_installation(self):
        core.write(self.project / 'input.json', self.spec)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = boards.main(['prepare', '--file', 'input.json', '--project', str(self.project), '--output-dir', 'prepared'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['kind'], 'reference-board-preparation')


if __name__ == '__main__':
    unittest.main()
