import os,sys,unittest,tempfile
sys.path.insert(0,os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.config.database import Base,get_db
from src.main import app
import src.models.dataset,src.models.config,src.models.trial,src.models.user,src.models.audit,src.models.quota
from src.models.user import User
from src.middlewares import audit as audit_mw
from src.utils.password import hash_password
class QuotaApiTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session=sessionmaker(self.engine,expire_on_commit=False)
        with self.Session() as db:
            for role in ('admin','operator','viewer'):
                db.add(User(email=f'{role}@beiling.test',role=role,password_hash=hash_password('pw-12345')))
            db.commit()
        def override_get_db():
            db=self.Session()
            try:yield db
            finally:db.close()
        app.dependency_overrides[get_db]=override_get_db
        # The audit middleware opens its own global Session; point it at the test engine.
        self._orig_audit_session=audit_mw.Session;audit_mw.Session=self.Session
        self.client=TestClient(app)
        self.tokens={}
        for role in ('admin','operator','viewer'):
            r=self.client.post('/auth/login',json={'email':f'{role}@beiling.test','password':'pw-12345'})
            self.tokens[role]=r.json()['token']
    def tearDown(self):
        app.dependency_overrides.clear();audit_mw.Session=self._orig_audit_session
    def h(self,role):return {'Authorization':'Bearer '+self.tokens[role]}
    def test_viewer_cannot_write_but_can_read(self):
        r=self.client.post('/quota/sites',json={'code':'north-api','name':'北岭接口站','description':'x'},headers=self.h('viewer'))
        self.assertEqual(r.status_code,403)
        r=self.client.post('/quota/sites',json={'code':'north-api','name':'北岭接口站','description':'x'},headers=self.h('operator'))
        self.assertEqual(r.status_code,201);sid=r.json()['id']
        r=self.client.get(f'/quota/sites/{sid}/limits',headers=self.h('viewer'))
        self.assertEqual(r.status_code,200)
    def test_end_to_end_batch_admit_reject_quota_and_keys(self):
        sid=self.client.post('/quota/sites',json={'code':'e2e-site','name':'端到端站','description':''},headers=self.h('admin')).json()['id']
        self.client.put(f'/quota/sites/{sid}/limits',json={'prefix':'p-','limit_value':2},headers=self.h('admin'))
        self.client.put(f'/quota/sites/{sid}/limits',json={'prefix':'p-a/','limit_value':1},headers=self.h('admin'))
        ok=self.client.post(f'/quota/sites/{sid}/batches',json={'token':'api-token-0001','operations':[{'op':'put','key':'p-a/1','value':'v'}]},headers=self.h('operator'))
        self.assertEqual(ok.status_code,201);self.assertEqual(ok.json()['status'],'accepted')
        # Whole batch rejected: inner prefix would exceed its limit.
        bad=self.client.post(f'/quota/sites/{sid}/batches',json={'token':'api-token-0002','operations':[{'op':'put','key':'p-b/1','value':'v'},{'op':'put','key':'p-a/2','value':'v'}]},headers=self.h('operator'))
        self.assertEqual(bad.json()['status'],'rejected')
        keys=self.client.get(f'/quota/sites/{sid}/keys',headers=self.h('viewer')).json()
        self.assertEqual(keys['values'],{'p-a/1':'v'});self.assertEqual(keys['live_count'],1)
        site=self.client.get('/quota/sites',headers=self.h('admin')).json()[0]
        rows={x['prefix']:x for x in site['occupancy']}
        self.assertEqual(rows['p-']['remaining'],1);self.assertEqual(rows['p-a/']['remaining'],0)
        # Replay with the same token returns the original rejected verdict.
        replay=self.client.post(f'/quota/sites/{sid}/batches',json={'token':'api-token-0002','operations':[{'op':'put','key':'p-b/1','value':'v'},{'op':'put','key':'p-a/2','value':'v'}]},headers=self.h('operator'))
        self.assertEqual(replay.json()['status'],'rejected')
        self.assertEqual(len(self.client.get(f'/quota/sites/{sid}/batches',headers=self.h('admin')).json()),2)
        # Overwrite takes no extra slot; compaction preserves occupancy.
        self.client.post(f'/quota/sites/{sid}/batches',json={'token':'api-token-0003','operations':[{'op':'put','key':'p-a/1','value':'v2'}]},headers=self.h('operator'))
        c=self.client.post(f'/quota/sites/{sid}/compact',headers=self.h('admin'))
        self.assertEqual(c.json()['live_before'],c.json()['live_after'])
        self.assertEqual(self.client.get(f'/quota/sites/{sid}/keys',headers=self.h('viewer')).json()['values'],{'p-a/1':'v2'})
    def test_validation_errors(self):
        r=self.client.post('/quota/sites',json={'code':'x','name':'北岭接口站','description':''},headers=self.h('admin'))
        self.assertEqual(r.status_code,422)
        r=self.client.post('/quota/sites/999/batches',json={'token':'api-token-zzzz','operations':[{'op':'put','key':'k','value':'v'}]},headers=self.h('admin'))
        self.assertEqual(r.status_code,404)
if __name__=='__main__':unittest.main()
