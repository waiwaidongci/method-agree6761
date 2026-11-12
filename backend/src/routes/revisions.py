from fastapi import APIRouter,Depends
from src.config.database import get_db
from src.utils.auth import current_user,editor
from src.schemas.revision import RevisionInput
from src.controllers.revision_controller import preview_revision,confirm_revision,list_revisions
router=APIRouter(prefix="/datasets")
@router.get("/{dataset_id}/revisions")
def revisions(dataset_id:int,db=Depends(get_db),user=Depends(current_user)):return list_revisions(db,dataset_id)
@router.post("/{dataset_id}/revisions/preview")
def preview(dataset_id:int,data:RevisionInput,db=Depends(get_db),user=Depends(editor)):return preview_revision(db,dataset_id,data)
@router.post("/{dataset_id}/revisions/confirm",status_code=201)
def confirm(dataset_id:int,data:RevisionInput,db=Depends(get_db),user=Depends(editor)):return confirm_revision(db,dataset_id,data,user)
