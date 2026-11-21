from fastapi import HTTPException
from sqlalchemy import select,update
from ..models.quota import QuotaSite,PrefixLimit,WriteBatch,KeyWriteLog,QuotaCompaction
from . import quota_engine as eng
def _lock_site(db,site_id):
    """Load and lock the site row as the transaction's first statement.

    MySQL/InnoDB REPEATABLE READ: a later FOR UPDATE cannot refresh the
    transaction's read view, so the locking read must come first; the waiter
    then takes its snapshot after the holder commits and sees its writes.
    SQLite (tests): a no-op UPDATE takes the reserved write lock; conflicts
    surface as OperationalError and callers retry in a fresh transaction.
    """
    if db.bind.dialect.name=='mysql':
        site=db.scalar(select(QuotaSite).where(QuotaSite.id==site_id).with_for_update())
    else:
        site=db.get(QuotaSite,site_id)
        if site is not None:
            db.execute(update(QuotaSite).where(QuotaSite.id==site_id).values(next_seq=site.next_seq))
    if site is None:raise HTTPException(404,'站点不存在')
    return site
def _load(db,model,ident):
    x=db.get(model,ident)
    if not x:raise HTTPException(404,'站点不存在')
    return x
def _records(db,site_id):
    rows=db.scalars(select(KeyWriteLog).where(KeyWriteLog.site_id==site_id).order_by(KeyWriteLog.seq)).all()
    return [{'seq':r.seq,'key':r.key,'value':r.value,'deleted':r.deleted,'level':r.level,'batch_id':r.batch_id} for r in rows]
def _limits(db,site_id):
    return [(x.prefix,x.limit_value) for x in db.scalars(select(PrefixLimit).where(PrefixLimit.site_id==site_id).order_by(PrefixLimit.prefix))]
def _usage(db,site):
    live=eng.live_snapshot(_records(db,site.id))
    return {'live_count':len(live),'occupancy':eng.occupancy(live,_limits(db,site.id))}
def site_dict(db,x):
    u=_usage(db,x)
    return {'id':x.id,'code':x.code,'name':x.name,'description':x.description,'next_seq':x.next_seq,**u}
def list_sites(db):
    return [site_dict(db,x) for x in db.scalars(select(QuotaSite).order_by(QuotaSite.id))]
def create_site(db,data):
    if db.scalar(select(QuotaSite).where(QuotaSite.code==data.code)):raise HTTPException(409,'站点编码已存在')
    x=QuotaSite(**data.model_dump());db.add(x);db.commit();db.refresh(x);return site_dict(db,x)
def list_limits(db,site_id):
    _load(db,QuotaSite,site_id)
    rows=db.scalars(select(PrefixLimit).where(PrefixLimit.site_id==site_id).order_by(PrefixLimit.prefix)).all()
    live=eng.live_snapshot(_records(db,site_id))
    return [{'id':r.id,'prefix':r.prefix,'limit_value':r.limit_value,'used':eng.count_prefix(live,r.prefix),'remaining':r.limit_value-eng.count_prefix(live,r.prefix)} for r in rows]
def set_limit(db,site_id,data):
    site=_lock_site(db,site_id)
    existing=db.scalar(select(PrefixLimit).where(PrefixLimit.site_id==site_id,PrefixLimit.prefix==data.prefix))
    live=eng.live_snapshot(_records(db,site_id));used=eng.count_prefix(live,data.prefix)
    if data.limit_value<used:raise HTTPException(422,f'新限额 {data.limit_value} 低于当前已占用 {used}，拒绝调整')
    if existing:
        existing.limit_value=data.limit_value;out=existing
    else:
        out=PrefixLimit(site_id=site_id,prefix=data.prefix,limit_value=data.limit_value);db.add(out)
    db.commit();db.refresh(out)
    return {'id':out.id,'prefix':out.prefix,'limit_value':out.limit_value,'used':used,'remaining':out.limit_value-used}
def delete_limit(db,site_id,limit_id):
    site=_lock_site(db,site_id)
    row=db.get(PrefixLimit,limit_id)
    if not row or row.site_id!=site_id:raise HTTPException(404,'前缀限额不存在')
    db.delete(row);db.commit();return {'deleted':limit_id}
def _batch_dict(b,projected):
    return {'id':b.id,'token':b.token,'status':b.status,'reason':b.reason,'operation_count':len(b.operations),'operations':b.operations,'projected':projected,'created_at':str(b.created_at)}
def list_batches(db,site_id):
    _load(db,QuotaSite,site_id)
    return [_batch_dict(b,b.projected) for b in db.scalars(select(WriteBatch).where(WriteBatch.site_id==site_id).order_by(WriteBatch.id.desc()))]
def submit_batch(db,site_id,data):
    """Atomic admit-or-reject. One row lock per site serializes contenders so
    only one batch can take the last slot; disjoint-prefix batches both pass."""
    site=_lock_site(db,site_id)
    dup=db.scalar(select(WriteBatch).where(WriteBatch.site_id==site_id,WriteBatch.token==data.token))
    if dup is not None:
        # Idempotent replay: return the original verdict, do not reserve again.
        return _batch_dict(dup,dup.projected)
    ops=[m.model_dump() for m in data.operations]
    records=_records(db,site_id);live=eng.live_snapshot(records)
    decision=eng.evaluate(live,ops,_limits(db,site_id))
    batch=WriteBatch(site_id=site_id,token=data.token,operations=ops,projected=decision['projected'])
    if not decision['admitted']:
        batch.status='rejected'
        b=decision['breaches'][0]
        batch.reason=f"前缀 {b['prefix']} 活键将达 {b['used']}，超过名额 {b['limit_value']}（整批不变）"
        db.add(batch);db.commit();db.refresh(batch);return _batch_dict(batch,decision['projected'])
    batch.status='accepted';batch.reason=None;db.add(batch);db.flush()
    seq=site.next_seq
    new_logs=[]
    for op in ops:
        seq+=1
        new_logs.append(KeyWriteLog(site_id=site_id,seq=seq,key=op['key'],value=None if op['op']=='delete' else op['value'],deleted=op['op']=='delete',batch_id=batch.id,level=0))
    site.next_seq=seq;db.add_all(new_logs)
    # Key values and occupancy become effective together: single commit.
    db.commit();db.refresh(batch)
    return _batch_dict(batch,decision['projected'])
def key_values(db,site_id,prefix=None):
    site=_load(db,QuotaSite,site_id)
    live=eng.live_snapshot(_records(db,site_id))
    if prefix is not None:live={k:v for k,v in live.items() if eng.under_prefix(k,prefix)}
    return {'site_id':site.id,'prefix':prefix,'live_count':len(live),'values':live}
def logs(db,site_id):
    site=_load(db,QuotaSite,site_id)
    rows=db.scalars(select(KeyWriteLog).where(KeyWriteLog.site_id==site_id).order_by(KeyWriteLog.seq)).all()
    return [{'id':r.id,'seq':r.seq,'key':r.key,'value':r.value,'deleted':r.deleted,'level':r.level,'batch_id':r.batch_id} for r in rows]
def compact_site(db,site_id):
    """Rewrite the LSM-style log keeping only winning records. Tombstones are
    retained; occupancy is asserted unchanged before/after the rewrite."""
    site=_lock_site(db,site_id)
    records=_records(db,site_id)
    before_live=eng.live_snapshot(records)
    kept,removed=eng.compact(records)
    after_live=eng.live_snapshot(kept)
    assert after_live==before_live,'合并不得改变活键占用'
    db.execute(KeyWriteLog.__table__.delete().where(KeyWriteLog.site_id==site_id))
    db.flush()
    db.add_all([KeyWriteLog(site_id=site_id,seq=r['seq'],key=r['key'],value=r['value'],deleted=r['deleted'],batch_id=r['batch_id'],level=0) for r in kept])
    detail={'removed_superseded':removed,'kept':len(kept),'tombstones_kept':sum(1 for r in kept if r['deleted']),'levels_after':[len(kept)],'policy':'只清理被更高序号覆盖的历史行；墓碑保留；活键快照与占用前后完全一致。'}
    rec=QuotaCompaction(site_id=site_id,rows_before=len(records),rows_after=len(kept),live_before=len(before_live),live_after=len(after_live),detail=detail)
    db.add(rec);db.commit();db.refresh(rec)
    return {'id':rec.id,'rows_before':rec.rows_before,'rows_after':rec.rows_after,'live_before':rec.live_before,'live_after':rec.live_after,'detail':rec.detail}
def compactions(db,site_id):
    _load(db,QuotaSite,site_id)
    return [{'id':r.id,'rows_before':r.rows_before,'rows_after':r.rows_after,'live_before':r.live_before,'live_after':r.live_after,'detail':r.detail,'created_at':str(r.created_at)} for r in db.scalars(select(QuotaCompaction).where(QuotaCompaction.site_id==site_id).order_by(QuotaCompaction.id.desc()))]
