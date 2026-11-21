from fastapi import APIRouter,Depends
from ..config.database import get_db
from ..schemas.quota import SiteInput,LimitInput,BatchInput
from ..services.auth import current_user,writer
from ..services import quota as svc
router=APIRouter(prefix='/quota')
@router.get('/sites')
def sites(db=Depends(get_db),user=Depends(current_user)):return svc.list_sites(db)
@router.post('/sites',status_code=201)
def add_site(data:SiteInput,db=Depends(get_db),user=Depends(writer)):return svc.create_site(db,data)
@router.get('/sites/{site_id}/limits')
def limits(site_id:int,db=Depends(get_db),user=Depends(current_user)):return svc.list_limits(db,site_id)
@router.put('/sites/{site_id}/limits')
def put_limit(site_id:int,data:LimitInput,db=Depends(get_db),user=Depends(writer)):return svc.set_limit(db,site_id,data)
@router.delete('/sites/{site_id}/limits/{limit_id}')
def remove_limit(site_id:int,limit_id:int,db=Depends(get_db),user=Depends(writer)):return svc.delete_limit(db,site_id,limit_id)
@router.get('/sites/{site_id}/batches')
def batches(site_id:int,db=Depends(get_db),user=Depends(current_user)):return svc.list_batches(db,site_id)
@router.post('/sites/{site_id}/batches',status_code=201)
def add_batch(site_id:int,data:BatchInput,db=Depends(get_db),user=Depends(writer)):return svc.submit_batch(db,site_id,data)
@router.get('/sites/{site_id}/keys')
def keys(site_id:int,prefix:str|None=None,db=Depends(get_db),user=Depends(current_user)):return svc.key_values(db,site_id,prefix)
@router.get('/sites/{site_id}/logs')
def write_logs(site_id:int,db=Depends(get_db),user=Depends(current_user)):return svc.logs(db,site_id)
@router.post('/sites/{site_id}/compact')
def compact(site_id:int,db=Depends(get_db),user=Depends(writer)):return svc.compact_site(db,site_id)
@router.get('/sites/{site_id}/compactions')
def compact_history(site_id:int,db=Depends(get_db),user=Depends(current_user)):return svc.compactions(db,site_id)
