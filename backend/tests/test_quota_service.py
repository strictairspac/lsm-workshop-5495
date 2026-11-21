import os,sys,unittest,threading,time,tempfile
sys.path.insert(0,os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError
from src.config.database import Base
import src.models.dataset,src.models.config,src.models.trial,src.models.user,src.models.audit,src.models.quota
from src.models.quota import QuotaSite
from src.schemas.quota import SiteInput,LimitInput,BatchInput,QuotaEntry
from src.services import quota as svc
from fastapi import HTTPException
def entry(op,key,value=None):return QuotaEntry(op=op,key=key,value=value)
class QuotaServiceTests(unittest.TestCase):
    def setUp(self):
        # File-backed SQLite gives each thread its own connection with real
        # lock-wait semantics; busy_timeout mirrors InnoDB row-lock waiting.
        fd,self.db_path=tempfile.mkstemp(suffix='.db');os.close(fd);os.unlink(self.db_path)
        self.engine=create_engine(f'sqlite:///{self.db_path}',connect_args={'timeout':10})
        @event.listens_for(self.engine,'connect')
        def _pragma(dbapi_conn,_):dbapi_conn.execute('PRAGMA busy_timeout=10000')
        Base.metadata.create_all(self.engine)
        self.Session=sessionmaker(self.engine,expire_on_commit=False)
        self.db=self.Session()
        self.site=svc.create_site(self.db,SiteInput(code='north-01',name='北岭站点',description='测试'))
        self.sid=self.site['id']
        svc.set_limit(self.db,self.sid,LimitInput(prefix='s-',limit_value=4))
        svc.set_limit(self.db,self.sid,LimitInput(prefix='s-a/',limit_value=2))
        svc.set_limit(self.db,self.sid,LimitInput(prefix='s-b/',limit_value=2))
    def tearDown(self):
        self.db.close();self.engine.dispose()
        try:os.unlink(self.db_path)
        except OSError:pass
    def submit(self,token,ops):return svc.submit_batch(self.db,self.sid,BatchInput(token=token,operations=ops))
    def test_accept_and_occupancy_nested(self):
        r=self.submit('tok-000001',[entry('put','s-a/1','v1'),entry('put','s-b/1','v2')])
        self.assertEqual(r['status'],'accepted')
        usage=svc.site_dict(self.db,self.db.get(QuotaSite,self.sid))
        rows={x['prefix']:x for x in usage['occupancy']}
        self.assertEqual(rows['s-']['used'],2);self.assertEqual(rows['s-a/']['used'],1);self.assertEqual(rows['s-b/']['used'],1)
        self.assertEqual(svc.key_values(self.db,self.sid)['values'],{'s-a/1':'v1','s-b/1':'v2'})
    def test_reject_leaves_whole_batch_untouched(self):
        self.submit('tok-000002',[entry('put','s-a/1','v'),entry('put','s-a/2','v')])
        before=svc.key_values(self.db,self.sid)
        r=self.submit('tok-000003',[entry('put','s-b/1','v'),entry('put','s-a/3','v')])
        self.assertEqual(r['status'],'rejected');self.assertIn('s-a/',r['reason'])
        self.assertEqual(svc.key_values(self.db,self.sid),before)
        self.assertEqual(svc.site_dict(self.db,self.db.get(QuotaSite,self.sid))['live_count'],2)
    def test_overwrite_does_not_consume_slot(self):
        self.submit('tok-000004',[entry('put','s-a/1','old')])
        r=self.submit('tok-000005',[entry('put','s-a/1','new'),entry('put','s-a/2','x')])
        self.assertEqual(r['status'],'accepted')
        self.assertEqual(svc.key_values(self.db,self.sid,prefix='s-a/')['values'],{'s-a/1':'new','s-a/2':'x'})
    def test_replay_same_token_is_idempotent(self):
        first=self.submit('tok-dup-001',[entry('put','s-b/1','v')])
        second=self.submit('tok-dup-001',[entry('put','s-b/1','v')])
        self.assertEqual(first['id'],second['id']);self.assertEqual(second['status'],'accepted')
        self.assertEqual(len(svc.logs(self.db,self.sid)),1)
        overflow=[entry('put',f's-a/{i}','v') for i in range(1,6)]
        rejected=self.submit('tok-dup-rej',overflow)
        self.assertEqual(rejected['status'],'rejected')
        replay=self.submit('tok-dup-rej',overflow)
        self.assertEqual(replay['id'],rejected['id']);self.assertEqual(replay['status'],'rejected')
    def test_replay_after_interruption_recovers_verdict(self):
        # Simulate a client retry: same token after the first request committed.
        r1=self.submit('tok-interrupt',[entry('put','s-b/2','v')])
        db2=self.Session()
        r2=svc.submit_batch(db2,self.sid,BatchInput(token='tok-interrupt',operations=[entry('put','s-b/2','v')]))
        self.assertEqual(r1['id'],r2['id']);self.assertEqual(len(svc.logs(self.db,self.sid)),1)
        db2.close()
    def test_limit_cannot_drop_below_usage(self):
        self.submit('tok-000006',[entry('put','s-a/1','v'),entry('put','s-a/2','v')])
        with self.assertRaises(HTTPException) as cm:svc.set_limit(self.db,self.sid,LimitInput(prefix='s-a/',limit_value=1))
        self.assertEqual(cm.exception.status_code,422)
    def test_compaction_does_not_change_occupancy(self):
        self.submit('tok-000007',[entry('put','k/1','old')])
        self.submit('tok-000008',[entry('put','k/1','new'),entry('put','k/2','v')])
        self.submit('tok-000009',[entry('delete','k/2')])
        before=svc.key_values(self.db,self.sid)
        log_count_before=len(svc.logs(self.db,self.sid))
        c=svc.compact_site(self.db,self.sid)
        self.assertEqual(c['live_before'],c['live_after'])
        self.assertEqual(svc.key_values(self.db,self.sid),before)
        self.assertLess(len(svc.logs(self.db,self.sid)),log_count_before)
        kept=svc.logs(self.db,self.sid)
        self.assertTrue(any(r['deleted'] for r in kept))
        # Compaction keeps original winning seqs (gaps are fine); new writes
        # continue from the site counter without colliding with kept seqs.
        r=self.submit('tok-000010',[entry('put','k/3','v')])
        self.assertEqual(r['status'],'accepted')
        rows=svc.logs(self.db,self.sid)
        seqs=[r['seq'] for r in rows]
        self.assertEqual(len(seqs),len(set(seqs)))
        self.assertEqual(max(seqs),self.db.get(QuotaSite,self.sid).next_seq)
    def test_last_slot_serialized_across_sessions(self):
        # With the outer limit at 4, fill 3 then race two one-key batches.
        self.submit('tok-000011',[entry('put','s-a/1','v'),entry('put','s-a/2','v'),entry('put','s-b/1','v')])
        results=[]
        barrier=threading.Barrier(2)
        def worker(token,key):
            barrier.wait()
            # Retry on SQLite lock conflicts; on MySQL the FOR UPDATE row lock
            # blocks in-driver, so the same serialization holds in production.
            for attempt in range(50):
                db=self.Session()
                try:
                    results.append(svc.submit_batch(db,self.sid,BatchInput(token=token,operations=[entry('put',key,'v')]))['status'])
                    return
                except OperationalError:
                    db.rollback();time.sleep(0.02)
                finally:db.close()
            results.append('lock-retry-exhausted')
        t1=threading.Thread(target=worker,args=('tok-race-1','s-b/2'))
        t2=threading.Thread(target=worker,args=('tok-race-2','s-c/1'))
        t1.start();t2.start();t1.join();t2.join()
        self.assertEqual(sorted(results),['accepted','rejected'])
        self.assertEqual(svc.site_dict(self.db,self.db.get(QuotaSite,self.sid))['live_count'],4)
    def test_disjoint_prefix_batches_both_confirmed(self):
        r1=self.submit('tok-disj-1',[entry('put','s-a/1','v'),entry('put','s-a/2','v')])
        r2=self.submit('tok-disj-2',[entry('put','s-b/1','v'),entry('put','s-b/2','v')])
        self.assertEqual([r1['status'],r2['status']],['accepted','accepted'])
if __name__=='__main__':unittest.main()
