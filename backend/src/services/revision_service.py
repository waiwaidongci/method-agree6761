import hashlib,json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models import PairDataset,PairedReading,Instrument,DatasetRevision,ReadingCorrection
from src.utils.schema_upgrade import raise_revision_conflict

def correction_hash(dataset_id,reason,corrections):
    payload={"dataset_id":dataset_id,"reason":reason,"corrections":sorted([c.model_dump() for c in corrections],key=lambda c:c["sample_code"])}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def _load_parent(db,dataset_id,lock=False):
    q=select(PairDataset).where(PairDataset.id==dataset_id)
    if lock:q=q.with_for_update()
    parent=db.scalar(q)
    if not parent:raise HTTPException(404,"配对数据集不存在")
    return parent

def _validate_order(db,parent,data):
    ref=db.get(Instrument,parent.reference_id);candidate=db.get(Instrument,parent.candidate_id)
    rows=db.scalars(select(PairedReading).where(PairedReading.dataset_id==parent.id)).all()
    by_code={r.sample_code:r for r in rows}
    codes=[c.sample_code for c in data.corrections]
    if len(set(codes))!=len(codes):
        raise HTTPException(422,"更正清单中试片编号重复，整单退回；请合并为同一试片的一条更正")
    unknown=[code for code in codes if code not in by_code]
    if unknown:
        raise HTTPException(422,f"试片编号不属于本样本集：{', '.join(unknown[:8])}；整单退回")
    changes=[];noop_count=0
    for item in data.corrections:
        original=by_code[item.sample_code]
        new_ref=original.reference_value if item.reference_value is None else item.reference_value
        new_cand=original.candidate_value if item.candidate_value is None else item.candidate_value
        if not ref.lower<=new_ref<=ref.upper or not candidate.lower<=new_cand<=candidate.upper:
            raise HTTPException(422,f"试片 {item.sample_code} 的改值超出仪器登记量程（参考 {ref.lower}–{ref.upper}%、候选 {candidate.lower}–{candidate.upper}%），整单退回")
        if new_ref==original.reference_value and new_cand==original.candidate_value:
            noop_count+=1;continue
        changes.append({"sample_code":item.sample_code,"reference_before":original.reference_value,"reference_after":new_ref,
                        "candidate_before":original.candidate_value,"candidate_after":new_cand})
    if not changes:
        raise HTTPException(422,"所有改值与原始读数一致，没有可生成修订版的差异，整单退回")
    return changes,noop_count,len(rows)

def _ensure_current(parent,data):
    if parent.version!=data.base_version:
        raise HTTPException(409,f"过期更正：当前为第{parent.version}版，提交基于第{data.base_version}版；请以最新版本重新核对后再提交")

def preview_revision(db,dataset_id,data):
    parent=_load_parent(db,dataset_id)
    _ensure_current(parent,data)
    existing=db.scalar(select(DatasetRevision).where(DatasetRevision.parent_dataset_id==parent.id))
    if existing:
        new=db.get(PairDataset,existing.new_dataset_id)
        raise HTTPException(409,f"第{parent.version}版已存在后继修订版（{new.name if new else '#'+str(existing.new_dataset_id)}，版本v{new.version if new else '?'}）；同一版仅接纳一个后继版本")
    changes,noop_count,total=_validate_order(db,parent,data)
    return {"parent_dataset_id":parent.id,"parent_name":parent.name,"base_version":parent.version,
            "change_count":len(changes),"noop_count":noop_count,"row_count":total,
            "correction_hash":correction_hash(parent.id,data.reason,data.corrections),"changes":changes}

def confirm_revision(db,dataset_id,data,user):
    digest=correction_hash(dataset_id,data.reason,data.corrections)
    prior=db.scalar(select(DatasetRevision).where(DatasetRevision.correction_hash==digest))
    if prior:
        new=db.get(PairDataset,prior.new_dataset_id)
        return {"revision_id":prior.id,"new_dataset_id":prior.new_dataset_id,"new_name":new.name if new else "",
                "version":new.version if new else None,"idempotent_hit":True,"change_count":0,"noop_count":0}
    parent=_load_parent(db,dataset_id,lock=True)
    _ensure_current(parent,data)
    existing=db.scalar(select(DatasetRevision).where(DatasetRevision.parent_dataset_id==parent.id))
    if existing:
        new=db.get(PairDataset,existing.new_dataset_id)
        raise HTTPException(409,f"第{parent.version}版已存在后继修订版（{new.name if new else '#'+str(existing.new_dataset_id)}）；并发更正仅接纳一个后继版本，本单被拒绝")
    changes,noop_count,total=_validate_order(db,parent,data)
    base_name=parent.name
    suffix=f" · 修订v{parent.version+1}"
    name=base_name if base_name.endswith(suffix) else base_name+suffix
    if db.scalar(select(PairDataset).where(PairDataset.name==name)):
        name=f"{base_name} · 修订v{parent.version+1}（{digest[:8]}）"
    new_dataset=PairDataset(name=name,reference_id=parent.reference_id,candidate_id=parent.candidate_id,
                            source_file=parent.source_file,note=parent.note,version=parent.version+1,revision_of_id=parent.id)
    db.add(new_dataset);db.flush()
    change_map={c["sample_code"]:c for c in changes}
    originals=db.scalars(select(PairedReading).where(PairedReading.dataset_id==parent.id).order_by(PairedReading.sample_code)).all()
    for r in originals:
        c=change_map.get(r.sample_code)
        db.add(PairedReading(dataset_id=new_dataset.id,sample_code=r.sample_code,
                             reference_value=c["reference_after"] if c else r.reference_value,
                             candidate_value=c["candidate_after"] if c else r.candidate_value))
    try:
        revision=DatasetRevision(parent_dataset_id=parent.id,new_dataset_id=new_dataset.id,base_version=parent.version,
                                 reason=data.reason,correction_hash=digest,created_by=user.email)
        db.add(revision);db.flush()
        db.add_all([ReadingCorrection(revision_id=revision.id,**c) for c in changes])
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise_revision_conflict(exc)
    return {"revision_id":revision.id,"new_dataset_id":new_dataset.id,"new_name":new_dataset.name,
            "version":new_dataset.version,"idempotent_hit":False,"change_count":len(changes),"noop_count":noop_count}

def list_revisions(db,dataset_id):
    if not db.get(PairDataset,dataset_id):raise HTTPException(404,"配对数据集不存在")
    chain={dataset_id}
    pending=[dataset_id]
    while pending:
        current=pending.pop()
        children=db.scalars(select(PairDataset.id).where(PairDataset.revision_of_id==current)).all()
        for child in children:
            if child not in chain:chain.add(child);pending.append(child)
        parent=db.get(PairDataset,current)
        if parent and parent.revision_of_id and parent.revision_of_id not in chain:
            chain.add(parent.revision_of_id);pending.append(parent.revision_of_id)
    revisions=db.scalars(select(DatasetRevision).where(DatasetRevision.parent_dataset_id.in_(chain)).order_by(DatasetRevision.id)).all()
    result=[]
    for rev in revisions:
        parent=db.get(PairDataset,rev.parent_dataset_id);new=db.get(PairDataset,rev.new_dataset_id)
        corrections=db.scalars(select(ReadingCorrection).where(ReadingCorrection.revision_id==rev.id).order_by(ReadingCorrection.sample_code)).all()
        result.append({"id":rev.id,"parent_dataset_id":rev.parent_dataset_id,"parent_name":parent.name if parent else "",
                       "base_version":rev.base_version,"new_dataset_id":rev.new_dataset_id,"new_name":new.name if new else "",
                       "version":new.version if new else None,"reason":rev.reason,"created_by":rev.created_by,
                       "created_at":rev.created_at,
                       "corrections":[{"sample_code":c.sample_code,"reference_before":c.reference_before,"reference_after":c.reference_after,
                                       "candidate_before":c.candidate_before,"candidate_after":c.candidate_after} for c in corrections]})
    return result
