import os,sys,unittest,threading
sys.path.insert(0,os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
from src.services import quota_engine as eng
LIMITS=[('station-',6),('station-a/',2),('station-b/',2)]
class EngineTests(unittest.TestCase):
    def test_nested_prefixes_each_count(self):
        live={'station-a/1':'v','station-a/2':'v','station-b/1':'v'}
        rows={r['prefix']:r for r in eng.occupancy(live,LIMITS)}
        self.assertEqual(rows['station-']['used'],3)
        self.assertEqual(rows['station-a/']['used'],2)
        self.assertEqual(rows['station-b/']['used'],1)
    def test_overwrite_costs_no_extra_slot(self):
        live={'station-a/1':'old'}
        ops=[{'op':'put','key':'station-a/1','value':'new'},{'op':'put','key':'station-a/2','value':'x'}]
        d=eng.evaluate(live,ops,LIMITS)
        self.assertTrue(d['admitted'])
        self.assertEqual(d['projected']['station-a/1'],'new')
        self.assertEqual(d['after'][1]['used'],2)
    def test_last_slot_rejected_when_outer_breached(self):
        live={f'station-a/{i}':'v' for i in range(1,3)}|{f'station-b/{i}':'v' for i in range(1,3)}|{'station-c/1':'v','station-c/2':'v'}
        d=eng.evaluate(live,[{'op':'put','key':'station-c/3','value':'x'}],LIMITS)
        self.assertFalse(d['admitted'])
        self.assertEqual(d['breaches'][0]['prefix'],'station-')
    def test_inner_prefix_breach_rejects_whole_batch(self):
        live={'station-a/1':'v','station-a/2':'v'}
        ops=[{'op':'put','key':'station-b/1','value':'x'},{'op':'put','key':'station-a/3','value':'x'}]
        d=eng.evaluate(live,ops,LIMITS)
        self.assertFalse(d['admitted'])
        self.assertEqual(d['breaches'][0]['prefix'],'station-a/')
    def test_delete_then_add_same_prefix_keeps_count(self):
        live={'station-a/1':'v','station-a/2':'v'}
        ops=[{'op':'delete','key':'station-a/1'},{'op':'put','key':'station-a/3','value':'x'}]
        d=eng.evaluate(live,ops,LIMITS)
        self.assertTrue(d['admitted'])
        self.assertEqual({r['prefix']:r['used'] for r in d['after']}['station-a/'],2)
        self.assertNotIn('station-a/1',d['projected'])
    def test_disjoint_prefix_batches_both_fit(self):
        live={}
        d1=eng.evaluate(live,[{'op':'put','key':f'station-a/{i}','value':'x'} for i in range(1,3)],LIMITS)
        d2=eng.evaluate(live,[{'op':'put','key':f'station-b/{i}','value':'x'} for i in range(1,3)],LIMITS)
        self.assertTrue(d1['admitted'] and d2['admitted'])
    def test_compact_keeps_tombstones_and_live_view(self):
        records=[{'seq':1,'key':'k1','value':'old','deleted':False,'level':0,'batch_id':1},
                 {'seq':2,'key':'k1','value':'new','deleted':False,'level':0,'batch_id':2},
                 {'seq':3,'key':'k2','value':'v','deleted':False,'level':0,'batch_id':2},
                 {'seq':4,'key':'k2','value':None,'deleted':True,'level':0,'batch_id':3}]
        before=eng.live_snapshot(records)
        kept,removed=eng.compact(records)
        self.assertEqual(removed,2)
        self.assertEqual(eng.live_snapshot(kept),before)
        self.assertTrue(any(r['deleted'] for r in kept))
        self.assertTrue(all(r['level']==0 for r in kept))
if __name__=='__main__':unittest.main()
