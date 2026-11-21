from datetime import datetime
from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,JSON,Integer,Boolean,DateTime,ForeignKey,UniqueConstraint,func
from ..config.database import Base
class QuotaSite(Base):
    __tablename__='quota_sites'
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(64),unique=True)
    name:Mapped[str]=mapped_column(String(120))
    description:Mapped[str]=mapped_column(String(2000),default='')
    next_seq:Mapped[int]=mapped_column(Integer,default=0)
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
class PrefixLimit(Base):
    __tablename__='prefix_limits'
    __table_args__=(UniqueConstraint('site_id','prefix',name='uq_prefix_limit'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    site_id:Mapped[int]=mapped_column(ForeignKey('quota_sites.id'))
    prefix:Mapped[str]=mapped_column(String(64))
    limit_value:Mapped[int]=mapped_column(Integer)
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
class WriteBatch(Base):
    __tablename__='write_batches'
    __table_args__=(UniqueConstraint('site_id','token',name='uq_batch_token'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    site_id:Mapped[int]=mapped_column(ForeignKey('quota_sites.id'))
    token:Mapped[str]=mapped_column(String(80))
    status:Mapped[str]=mapped_column(String(20))
    reason:Mapped[str|None]=mapped_column(String(500),nullable=True)
    operations:Mapped[list]=mapped_column(JSON)
    projected:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
class KeyWriteLog(Base):
    __tablename__='key_write_logs'
    id:Mapped[int]=mapped_column(primary_key=True)
    site_id:Mapped[int]=mapped_column(ForeignKey('quota_sites.id'),index=True)
    seq:Mapped[int]=mapped_column(Integer)
    key:Mapped[str]=mapped_column(String(64),index=True)
    value:Mapped[str|None]=mapped_column(String(200),nullable=True)
    deleted:Mapped[bool]=mapped_column(Boolean,default=False)
    batch_id:Mapped[int]=mapped_column(ForeignKey('write_batches.id'))
    level:Mapped[int]=mapped_column(Integer,default=0)
class QuotaCompaction(Base):
    __tablename__='quota_compactions'
    id:Mapped[int]=mapped_column(primary_key=True)
    site_id:Mapped[int]=mapped_column(ForeignKey('quota_sites.id'))
    rows_before:Mapped[int]=mapped_column(Integer)
    rows_after:Mapped[int]=mapped_column(Integer)
    live_before:Mapped[int]=mapped_column(Integer)
    live_after:Mapped[int]=mapped_column(Integer)
    detail:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
