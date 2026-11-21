"""Acceptance script for the prefix active-key quota spec.

Each section maps to one clause of the workshop requirement. Runs against a
file-backed SQLite database; the same service code runs on MySQL in the
container with InnoDB row locks.
"""
import os,sys,tempfile
sys.path.insert(0,os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.config.database import Base
import src.models.dataset,src.models.config,src.models.trial,src.models.user,src.models.audit,src.models.quota
from src.models.quota import QuotaSite
from src.schemas.quota import SiteInput,LimitInput,BatchInput,QuotaEntry
from src.services import quota as svc
from fastapi import HTTPException

def E(op,key,value=None):return QuotaEntry(op=op,key=key,value=value)
def occ(db,sid):
    s=svc.site_dict(db,db.get(QuotaSite,sid))
    return {r['prefix']:(r['used'],r['remaining']) for r in s['occupancy']},s['live_count']

def main():
    fd,path=tempfile.mkstemp(suffix='.db');os.close(fd)
    engine=create_engine(f'sqlite:///{path}');Base.metadata.create_all(engine)
    Session=sessionmaker(engine,expire_on_commit=False)
    db=Session()
    # 页面能设限：站点 + 嵌套三层前缀限额
    sid=svc.create_site(db,SiteInput(code='spec-demo',name='需求验收站'))['id']
    svc.set_limit(db,sid,LimitInput(prefix='dev/',limit_value=6))
    svc.set_limit(db,sid,LimitInput(prefix='dev/a/',limit_value=3))
    svc.set_limit(db,sid,LimitInput(prefix='dev/a/temp/',limit_value=2))
    # 前缀嵌套时各层都计数
    b1=svc.submit_batch(db,sid,BatchInput(token='spec-batch-0001',operations=[
        E('put','dev/a/temp/1','v'),E('put','dev/a/temp/2','v'),E('put','dev/a/other','v')]))
    assert b1['status']=='accepted'
    o,live=occ(db,sid)
    assert o['dev/']==(3,3) and o['dev/a/']==(3,0) and o['dev/a/temp/']==(2,0),o
    # 批次删旧补新，按整批写完的活键数判定
    b2=svc.submit_batch(db,sid,BatchInput(token='spec-batch-0002',operations=[
        E('delete','dev/a/temp/1'),E('put','dev/a/temp/3','v')]))
    assert b2['status']=='accepted'  # 删1补1，dev/a/temp/ 仍为2，dev/a/ 仍为3
    assert 'dev/a/temp/1' not in svc.key_values(db,sid)['values']
    # 覆盖不另占名额：temp 已满2，覆盖其中一个仍放行
    b3=svc.submit_batch(db,sid,BatchInput(token='spec-batch-0003',operations=[E('put','dev/a/temp/2','new')]))
    assert b3['status']=='accepted'
    assert svc.key_values(db,sid,prefix='dev/a/temp/')['values']['dev/a/temp/2']=='new'
    # 拒绝就整批不变：试图在已满的 dev/a/ 新增键（即使同批先删别的层）
    before=svc.key_values(db,sid)
    b4=svc.submit_batch(db,sid,BatchInput(token='spec-batch-0004',operations=[
        E('put','dev/x','v'),E('put','dev/a/boom','v')]))
    assert b4['status']=='rejected' and 'dev/a/' in b4['reason']
    assert svc.key_values(db,sid)==before,'拒绝后键值必须完全不变'
    # 重试同批不重复占名额（确认中断后恢复原判定）
    b4r=svc.submit_batch(db,sid,BatchInput(token='spec-batch-0004',operations=[
        E('put','dev/x','v'),E('put','dev/a/boom','v')]))
    assert b4r['id']==b4['id'] and b4r['status']=='rejected'
    accepted=svc.submit_batch(db,sid,BatchInput(token='spec-batch-0003',operations=[E('put','dev/a/temp/2','new')]))
    assert accepted['id']==b3['id']  # 已接收批次重试也不重复写
    # 前缀互不相交的批次照常确认
    b5=svc.submit_batch(db,sid,BatchInput(token='spec-batch-0005',operations=[
        E('put','dev/b/1','v'),E('put','dev/b/2','v'),E('put','dev/b/3','v')]))
    assert b5['status']=='accepted'
    # 合并搬表也不改占用
    pre=svc.key_values(db,sid);pre_logs=len(svc.logs(db,sid))
    c=svc.compact_site(db,sid)
    assert c['live_before']==c['live_after']==pre['live_count']
    assert svc.key_values(db,sid)==pre
    assert len(svc.logs(db,sid))<pre_logs  # 历史行被清理，墓碑保留
    # 合并后仍可继续写入且序号不冲突；dev/ 已满6，先删后补才放行
    b6=svc.submit_batch(db,sid,BatchInput(token='spec-batch-0006',operations=[E('put','dev/c/1','v')]))
    assert b6['status']=='rejected'
    b7=svc.submit_batch(db,sid,BatchInput(token='spec-batch-0007',operations=[
        E('delete','dev/b/3'),E('put','dev/c/1','v')]))
    assert b7['status']=='accepted'
    seqs=[r['seq'] for r in svc.logs(db,sid)]
    assert len(seqs)==len(set(seqs))
    # 再查键值和剩余名额
    final=svc.key_values(db,sid)
    o2,live2=occ(db,sid)
    assert final['live_count']==live2==6,final
    assert o2['dev/']==(6,0)  # 满员，剩余 0
    print('OCCUPANCY:',o2)
    print('LIVE KEYS:',jsonish(final['values']))
    print('COMPACTION:',c['rows_before'],'->',c['rows_after'],'tombstones kept:',c['detail']['tombstones_kept'])
    print('ALL SPEC CHECKS PASSED')
    db.close();engine.dispose();os.unlink(path)

def jsonish(d):return {k:d[k] for k in sorted(d)}
if __name__=='__main__':main()
