"""Offline regional/account routing guards; no real credential or service call."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art/runtime'))
from greybox import account_profiles as accounts, core, provider_adapter, suppliers, provider_credentials
from greybox.providers import meshy, tripo, rodin, hitem3d
from test_meshy_tripo import FakeAPI, mesh_request, mesh_task, TASK


def profile(provider='meshy', system=None, suffix='TEAM'):
    item = {'account_system': system or ('public' if provider in {'rodin','hitem3d'} else 'cn'),
            'account_ref': 'team-main', 'wallet': provider + '-team'}
    if provider == 'hitem3d':
        item['credential_envs'] = ['HITEM3D_'+suffix+'_CLIENT_ID', 'HITEM3D_'+suffix+'_CLIENT_SECRET']
    else:
        item['credential_env'] = provider.upper()+'_'+suffix+'_API_KEY'
    return item


class AccountProfiles(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        storage = patch.object(provider_credentials, 'store_path', return_value=Path(temporary.name) / 'credentials/providers.json')
        storage.start()
        self.addCleanup(storage.stop)

    def test_fixed_regional_hosts_and_no_fallback(self):
        for provider, module in [('meshy',meshy),('tripo',tripo),('rodin',rodin),('hitem3d',hitem3d)]:
            for system, endpoint in accounts.ENDPOINTS[provider].items():
                p = profile(provider, system)
                api = module._client({'account_profile': p})
                self.assertEqual(api.base_url, endpoint)
                self.assertEqual(len(api.allowed_hosts), 1)
                if provider != 'hitem3d': self.assertEqual(api.credential_env, p['credential_env'])
                else: self.assertEqual(api.credential_provider.credential_envs, tuple(p['credential_envs']))
        for provider in ('rodin','hitem3d'):
            with self.assertRaisesRegex(ValueError, 'account system'):
                accounts.validate(provider, profile(provider, 'cn'))
        with self.assertRaisesRegex(ValueError, 'host overrides'):
            accounts.validate('meshy', dict(profile(), api_base='https://other.example'))

    def test_secret_env_names_not_values_and_no_global_env_mutation(self):
        original = dict(os.environ)
        p = profile()
        with patch.dict(os.environ, {'MESHY_API_KEY': 'synthetic-default'}, clear=True):
            result = provider_adapter.dispatch('meshy', 'capabilities', {'account_profile': p})
            self.assertFalse(result['configured'])
            self.assertEqual(result['required_env'], [p['credential_env']])
            self.assertEqual(result['api_base'], 'https://api.meshy.cn')
            self.assertEqual(dict(os.environ), {'MESHY_API_KEY':'synthetic-default'})
        self.assertEqual(dict(os.environ), original)
        for invalid in ('PATH', 'RODIN_OTHER_KEY', 'secret-value-with-dashes', 'MESHY_BAD\nNAME'):
            with self.assertRaises(ValueError):
                accounts.validate('meshy', dict(p, credential_env=invalid))

    def test_hitem_token_uses_only_explicit_env_pair(self):
        p = profile('hitem3d')
        env = dict(zip(p['credential_envs'], ['synthetic-id', 'synthetic-secret']))
        calls = []
        class Auth:
            def __init__(self, *args, **kwargs):
                calls.append((args, kwargs['credential_provider']()))
            def request(self, *args, **kwargs):
                return {'code':200,'data':{'accessToken':'synthetic-token','tokenType':'Bearer'}}
        with patch.dict(os.environ, env, clear=True), patch.object(hitem3d,'ApiClient',Auth):
            token=hitem3d._Token(p['credential_envs'])
            self.assertEqual(token(),'synthetic-token');self.assertEqual(token(),'synthetic-token')
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0][0],'https://api.hitem3d.ai')

    def test_submit_returns_profile_bound_recovery_and_digest(self):
        request=dict(mesh_request(),account_profile=profile())
        result=meshy.dispatch('submit',request,FakeAPI([{'result':TASK}]))
        expected=accounts.profile_digest('meshy',profile())
        self.assertEqual(result['account_profile_sha256'],expected)
        self.assertEqual(result['recovery']['account_profile_sha256'],expected)
        self.assertEqual(result['recovery']['account_profile'],profile())
        self.assertNotIn('account_profile_sha256',request)  # no caller mutation
        validated=meshy.dispatch('validate',request,FakeAPI([]))
        other=meshy.dispatch('validate',dict(request,account_profile=profile(system='international')),FakeAPI([]))
        self.assertNotEqual(validated['request_digest'],other['request_digest'])

    def test_status_and_fetch_cannot_switch_profile_or_borrow_legacy_recovery(self):
        accepted=accounts.bind_request('meshy','submit',dict(mesh_request(),account_profile=profile()))
        submitted=meshy.dispatch('submit',accepted,FakeAPI([{'result':TASK}]))
        context={'task_id':TASK,'accepted_request':accepted,'recovery':submitted['recovery']}
        result=meshy.dispatch('status',context,FakeAPI([mesh_task(status='IN_PROGRESS')]))
        self.assertEqual(result['account_profile'],profile())
        changed=dict(context,account_profile=profile(system='international'))
        for method in ('status','fetch'):
            client=FakeAPI([])
            with self.assertRaisesRegex(ValueError,'switch'):
                meshy.dispatch(method,changed,client)
            self.assertFalse(client.calls)
        with self.assertRaisesRegex(ValueError,'original accepted_request'):
            meshy.dispatch('status',dict(context,accepted_request=mesh_request(),account_profile=profile()),FakeAPI([]))
        with self.assertRaisesRegex(ValueError,'original account binding'):
            meshy.dispatch('status',dict(context,recovery={'provider':'meshy','task_id':TASK}),FakeAPI([]))
        with self.assertRaisesRegex(ValueError,'digest changed'):
            accounts.bind_request('meshy','account',{'account_profile':profile(),'account_profile_sha256':'a'*64})

    def test_old_direct_api_calls_keep_legacy_behavior(self):
        self.assertEqual(meshy._client().base_url,'https://api.meshy.ai')
        self.assertNotIn('account_profile',meshy.dispatch('capabilities',{}))
        self.assertTrue(meshy.dispatch('status',{'task_id':TASK,'accepted_request':mesh_request()},FakeAPI([mesh_task()]))['ok'])

    def test_registry_injection_cannot_override_frozen_profile(self):
        p=profile()
        bound=accounts.inject_registry('meshy','submit',mesh_request(),p)
        self.assertEqual(bound['account_profile'],p)
        with self.assertRaises(ValueError):
            accounts.inject_registry('meshy','submit',dict(mesh_request(),account_profile=profile(system='international')),p)
        with self.assertRaises(ValueError):
            accounts.inject_registry('meshy','submit',dict(mesh_request(),account_profile=p),None)

    def test_quote_wallet_mismatch_rejected(self):
        request=accounts.bind_request('meshy','quote',{'account_profile':profile()})
        with self.assertRaisesRegex(ValueError,'Quote wallet'):
            accounts.bind_result('meshy',request,{'pricing':{'wallet':'another-account'}})


class AccountRegistry(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.project=Path(self.temp.name)
        path=self.project/'evidence.txt';path.write_text('synthetic evidence, no account service called')
        self.p=profile()
        self.sha=accounts.profile_digest('meshy',self.p)
        self.record={'state':'verified','checked_at':'2020-01-01T00:00:00Z','evidence':{'path':'evidence.txt','sha256':core.file_hash(path)},'account_profile_sha256':self.sha}
        self.provider={'id':'meshy','label':'Meshy','configured':True,'desired':True,'binding':{'kind':'builtin_api'},'operations':['image_to_3d'],
                       'account_profile':self.p,'verification':{'connection':copy.deepcopy(self.record),'operations':{'image_to_3d':copy.deepcopy(self.record)}}}
        self.registry={'schema':1,'kind':'supplier-registry','providers':[self.provider]}

    def test_readiness_is_bound_to_profile_digest(self):
        self.assertTrue(suppliers.inventory(self.registry,self.project)['suppliers'][0]['execution_ready'])
        previous=suppliers.registry_digest(self.registry)
        self.p['account_system']='international'
        row=suppliers.inventory(self.registry,self.project)['suppliers'][0]
        self.assertFalse(row['connection_verified']);self.assertFalse(row['operations_verified'])
        self.assertNotEqual(previous,suppliers.registry_digest(self.registry))
        self.provider['verification']['connection']['account_profile_sha256']=accounts.profile_digest('meshy',self.p)
        row=suppliers.inventory(self.registry,self.project)['suppliers'][0]
        self.assertTrue(row['connection_verified']);self.assertFalse(row['execution_ready'])

    def test_builtin_invocation_injects_approved_registry_profile(self):
        with patch.object(provider_adapter,'dispatch',side_effect=lambda p,m,r:r):
            result=suppliers.invoke_adapter(self.registry,'meshy','capabilities',{},base=self.project)
        self.assertEqual(result['account_profile'],self.p)
        self.assertEqual(result['account_profile_sha256'],self.sha)
        with self.assertRaises(ValueError):
            suppliers.invoke_adapter(self.registry,'meshy','capabilities',{'account_profile':profile(system='international')},base=self.project)

    def test_pricing_must_name_the_profile_wallet(self):
        source={'path':'evidence.txt','sha256':core.file_hash(self.project/'evidence.txt'),'checked_at':'2020-01-01T00:00:00Z'}
        pricing={'kind':'rate_card_estimate','source':source,'quoted_at':'2020-01-01T00:00:00Z','unit_credits':1,'wallet':'wrong'}
        op={'id':'make','asset_id':'gate','provider':'meshy','operation':'image_to_3d','model_version':'meshy-7.1','parameters':{},'rationale':'synthetic','pricing':pricing}
        portfolio={'schema':1,'kind':'supplier-portfolio','registry_sha256':suppliers.registry_digest(self.registry),'recommendation_rationale':'synthetic',
                   'required_assets':['gate'],'recommended_option':'one','options':[{'id':'one','rationale':'synthetic','assets':[{'asset_id':'gate','route':'generated','rationale':'synthetic','operation_ids':['make']}],'operations':[op]}]}
        with self.assertRaisesRegex(ValueError,'pricing wallet'):
            suppliers.validate_portfolio(portfolio,self.registry,self.project,enforce_image_policy=False)
        pricing['wallet']=self.p['wallet']
        self.assertTrue(suppliers.validate_portfolio(portfolio,self.registry,self.project,enforce_image_policy=False)['ok'])


if __name__=='__main__':unittest.main()
