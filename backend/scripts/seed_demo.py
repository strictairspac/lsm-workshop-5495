from sqlalchemy import select
from src.config.database import Base,engine,Session
from src.models.user import User
from src.models.dataset import Dataset
from src.models.config import Config
from src.models.trial import Trial
from src.models.audit import Audit
from src.models.quota import QuotaSite,PrefixLimit,WriteBatch,KeyWriteLog
from src.services import quota_engine
from src.utils.password import hash_password
DEMO=[{'op':'put','key':'sensor-01','value':'18.2'},{'op':'put','key':'sensor-02','value':'19.1'},{'op':'put','key':'sensor-03','value':'22.4'},{'op':'put','key':'sensor-04','value':'17.0'},{'op':'put','key':'sensor-01','value':'18.8'},{'op':'delete','key':'sensor-02'},{'op':'put','key':'sensor-05','value':'21.6'},{'op':'put','key':'sensor-06','value':'20.3'},{'op':'delete','key':'sensor-03'},{'op':'put','key':'sensor-07','value':'23.0'},{'op':'put','key':'sensor-01','value':'19.0'},{'op':'put','key':'sensor-08','value':'18.9'}]
def seed():
    Base.metadata.create_all(engine)
    with Session() as db:
        for role in ('admin','operator','viewer'):
            email=role+'@beiling.test'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,role=role,password_hash=hash_password('EdgeStore!17')))
        sets=[('北岭站点-早班写入','sensor-01重复写，sensor-02与sensor-03墓碑删除；12条操作，最终6个存活键。',DEMO),('旧值复活回归集','先将旧值刷入深层，再写墓碑；最终合并必须防止旧值复活。',[{'op':'put','key':'sensor-a','value':'old'},{'op':'put','key':'sensor-b','value':'b'},{'op':'put','key':'sensor-c','value':'c'},{'op':'put','key':'sensor-d','value':'d'},{'op':'delete','key':'sensor-a'},{'op':'put','key':'sensor-e','value':'e'}]),('全部删除边界集','两个已写入键随后全部删除，最终应是空字典。',[{'op':'put','key':'x','value':'1'},{'op':'put','key':'y','value':'2'},{'op':'delete','key':'x'},{'op':'delete','key':'y'}])]
        for name,desc,entries in sets:
            if not db.scalar(select(Dataset).where(Dataset.name==name)):db.add(Dataset(name=name,description=desc,entries=entries))
        configs=[('小内存-完整合并',2,2,3,True),('保留层级观测',2,3,3,False),('宽缓冲-完整合并',4,2,4,True)]
        for name,limit,trigger,depth,final in configs:
            if not db.scalar(select(Config).where(Config.name==name)):db.add(Config(name=name,memtable_limit=limit,l0_trigger=trigger,max_levels=depth,final_compaction=final))
        seed_quota(db)
        db.commit()
        return {name:db.query(model).count() for name,model in [('users',User),('datasets',Dataset),('configs',Config),('trials',Trial)]}
def seed_quota(db):
    """Prefix quota demo: nested prefixes each count; idempotent via natural keys."""
    site=db.scalar(select(QuotaSite).where(QuotaSite.code=='beiling-north'))
    if not site:
        site=QuotaSite(code='beiling-north',name='北岭站点-活键名额',description='嵌套前缀各层计数的演示站点：station-* 全站 12 个活键，station-a/* 与 station-b/* 各 4 个。')
        db.add(site);db.flush()
        db.add_all([PrefixLimit(site_id=site.id,prefix='station-',limit_value=12),PrefixLimit(site_id=site.id,prefix='station-a/',limit_value=4),PrefixLimit(site_id=site.id,prefix='station-b/',limit_value=4)])
        ops=[{'op':'put','key':f'station-a/sensor-{i}','value':f'{20+i}.0'} for i in range(1,4)]+[{'op':'put','key':'station-b/sensor-1','value':'24.0'}]
        batch=WriteBatch(site_id=site.id,token='seed-beiling-north-0001',status='accepted',operations=ops,projected=quota_engine.project({},ops))
        db.add(batch);db.flush()
        for seq,op in enumerate(ops,1):
            db.add(KeyWriteLog(site_id=site.id,seq=seq,key=op['key'],value=op['value'],deleted=False,batch_id=batch.id,level=0))
        site.next_seq=len(ops)
if __name__=='__main__':print(seed())
