"""Prefix active-key quota engine: pure functions over ordered write records.

A record is a mapping with keys: seq, key, value, deleted, level.
The append-only LSM-style log keeps every write; the live view is derived from
the highest-seq record per key. Compaction removes only superseded history and
must never change the live view (occupancy), mirroring the workshop rule
"合并搬表也不改占用".
"""
from collections import OrderedDict
def under_prefix(key,prefix):
    return key.startswith(prefix)
def latest_records(records):
    """Return dict key -> winning record (highest seq)."""
    latest={}
    for r in records:
        cur=latest.get(r['key'])
        if cur is None or r['seq']>cur['seq']:latest[r['key']]=r
    return latest
def live_snapshot(records):
    """Ordered key->value for non-tombstone winners."""
    snap=OrderedDict()
    for key in sorted(latest_records(records)):
        r=latest_records(records)[key]
        if not r['deleted']:snap[key]=r['value']
    return snap
def count_prefix(live,prefix):
    return sum(1 for key in live if under_prefix(key,prefix))
def occupancy(live,limits):
    """Every prefix layer counts; nested prefixes each get their own row."""
    return [{'prefix':p,'limit_value':lim,'used':count_prefix(live,p),'remaining':lim-count_prefix(live,p)} for p,lim in limits]
def project(live,operations):
    """Apply an ordered batch onto the live view and return the projected view."""
    projected=dict(live)
    for op in operations:
        if op['op']=='delete':projected.pop(op['key'],None)
        else:projected[op['key']]=op['value']
    return dict(sorted(projected.items()))
def evaluate(live,operations,limits):
    """Admission decision. Limits are (prefix, limit_value) pairs.

    Batch is admitted only when every prefix layer stays within its limit once
    the whole batch is applied. Overwrites reuse the existing slot, so an
    already-live key never costs an extra slot.
    """
    projected=project(live,operations)
    before=occupancy(live,limits);after=occupancy(projected,limits)
    breaches=[row for row in after if row['remaining']<0]
    return {'admitted':not breaches,'projected':projected,'before':before,'after':after,
            'breaches':[{'prefix':b['prefix'],'limit_value':b['limit_value'],'used':b['used']} for b in breaches]}
def compact(records):
    """Drop superseded rows; tombstones stay (workshop tiers keep tombstones).

    Returns (kept, removed_count). Kept winners move to level 0. The live
    snapshot of kept rows must equal the input live snapshot; callers assert.
    """
    latest=latest_records(records)
    keep_seqs={r['seq'] for r in latest.values()}
    kept=[dict(r,level=0) for r in records if r['seq'] in keep_seqs]
    return kept,len(records)-len(kept)
