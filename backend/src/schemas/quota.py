from typing import Literal
from pydantic import BaseModel,Field,model_validator
class SiteInput(BaseModel):
    code:str=Field(min_length=2,max_length=64,pattern=r'^[A-Za-z0-9][A-Za-z0-9_.\-]*$')
    name:str=Field(min_length=2,max_length=120)
    description:str=Field(default='',max_length=2000)
class LimitInput(BaseModel):
    prefix:str=Field(min_length=1,max_length=64)
    limit_value:int=Field(ge=0,le=100000)
class QuotaEntry(BaseModel):
    op:Literal['put','delete']
    key:str=Field(min_length=1,max_length=64)
    value:str|None=Field(default=None,max_length=200)
    @model_validator(mode='after')
    def check_value(self):
        if self.op=='put' and self.value is None:raise ValueError('put 操作必须包含字符串 value')
        return self
class BatchInput(BaseModel):
    token:str=Field(min_length=8,max_length=80)
    operations:list[QuotaEntry]=Field(min_length=1,max_length=2000)
