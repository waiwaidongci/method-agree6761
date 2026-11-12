import math
import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException
from pydantic import ValidationError

from src.config.database import Base
from src.models import (Instrument,PairDataset,PairedReading,ComparisonRun,
                        DatasetRevision,ReadingCorrection)
from src.schemas.revision import RevisionInput,CorrectionItem
from src.services import revision_service as svc

engine=create_engine("sqlite://",connect_args={"check_same_thread":False},
                     poolclass=StaticPool)
Session=sessionmaker(bind=engine,expire_on_commit=False)

class U:
    def __init__(self,email):self.email=email
ADMIN=U("analyst@ciguang.demo")

@pytest.fixture()
def db():
    Base.metadata.create_all(engine)
    s=Session()
    ref=Instrument(code="CG-R01",name="ref",serial="s1",unit="%",lower=2,upper=90)
    cand=Instrument(code="CG-N02",name="cand",serial="s2",unit="%",lower=2,upper=90)
    s.add_all([ref,cand]);s.flush()
    ds=PairDataset(name="N02 · 原始",reference_id=ref.id,candidate_id=cand.id,
                   source_file="pairs.csv",note="orig",version=1)
    s.add(ds);s.flush()
    for i in range(25):
        s.add(PairedReading(dataset_id=ds.id,sample_code=f"CG1-{i+1:03d}",
                            reference_value=10.0+i,candidate_value=11.0+i))
    run=ComparisonRun(name="old run",dataset_id=ds.id,lambda_ratio=1,allowance=2,
                      range_low=0,range_high=100,bootstrap_count=200,status="completed",
                      result={"fingerprint":"old-fp","points":[]})
    s.add(run);s.commit()
    yield s
    s.close();Base.metadata.drop_all(engine)

def payload(base_version=1,corrections=None,reason="试片读数抄错，按纸质记录更正"):
    return RevisionInput(base_version=base_version,reason=reason,
                         corrections=corrections or [CorrectionItem(sample_code="CG1-001",reference_value=10.5)])

def test_preview_shows_diff_and_keeps_other_readings(db):
    ds=db.scalar(select(PairDataset))
    prev=svc.preview_revision(db,ds.id,payload())
    assert prev["change_count"]==1 and prev["row_count"]==25 and prev["noop_count"]==0
    ch=prev["changes"][0]
    assert (ch["reference_before"],ch["reference_after"])==(10.0,10.5)
    assert (ch["candidate_before"],ch["candidate_after"])==(11.0,11.0)

def test_preview_noop_change_rejected(db):
    ds=db.scalar(select(PairDataset))
    with pytest.raises(HTTPException) as e:
        svc.preview_revision(db,ds.id,payload(corrections=[CorrectionItem(sample_code="CG1-001",reference_value=10.0)]))
    assert e.value.status_code==422

def test_unknown_sample_rejects_whole_order(db):
    ds=db.scalar(select(PairDataset))
    with pytest.raises(HTTPException) as e:
        svc.preview_revision(db,ds.id,payload(corrections=[
            CorrectionItem(sample_code="CG1-001",reference_value=12.0),
            CorrectionItem(sample_code="NOPE",reference_value=1.0)]))
    assert e.value.status_code==422 and "不属于本样本集" in e.value.detail
    assert db.scalar(select(func.count()).select_from(DatasetRevision))==0
    assert db.scalar(select(PairedReading.reference_value).where(PairedReading.sample_code=="CG1-001"))==10.0

def test_out_of_range_rejects_whole_order(db):
    ds=db.scalar(select(PairDataset))
    with pytest.raises(HTTPException) as e:
        svc.preview_revision(db,ds.id,payload(corrections=[
            CorrectionItem(sample_code="CG1-001",reference_value=12.0),
            CorrectionItem(sample_code="CG1-002",candidate_value=95.0)]))
    assert e.value.status_code==422 and "量程" in e.value.detail

def test_duplicate_code_in_order_rejected(db):
    ds=db.scalar(select(PairDataset))
    with pytest.raises(HTTPException) as e:
        svc.preview_revision(db,ds.id,payload(corrections=[
            CorrectionItem(sample_code="CG1-001",reference_value=12.0),
            CorrectionItem(sample_code="CG1-001",candidate_value=13.0)]))
    assert e.value.status_code==422

def test_nan_and_inf_rejected_by_schema():
    with pytest.raises(ValidationError):
        CorrectionItem(sample_code="CG1-001",reference_value=float("nan"))
    with pytest.raises(ValidationError):
        CorrectionItem(sample_code="CG1-001",candidate_value=float("inf"))

def test_confirm_creates_full_revised_dataset_with_unchanged_rows(db):
    ds=db.scalar(select(PairDataset))
    out=svc.confirm_revision(db,ds.id,payload(corrections=[
        CorrectionItem(sample_code="CG1-001",reference_value=10.5),
        CorrectionItem(sample_code="CG1-025",candidate_value=88.0)]),ADMIN)
    assert out["idempotent_hit"] is False and out["version"]==2 and out["change_count"]==2
    new=db.get(PairDataset,out["new_dataset_id"])
    assert new.revision_of_id==ds.id and new.version==2 and new.reference_id==ds.reference_id
    assert db.scalar(select(func.count()).select_from(PairedReading).where(PairedReading.dataset_id==new.id))==25
    r1=db.scalar(select(PairedReading).where(PairedReading.dataset_id==new.id,PairedReading.sample_code=="CG1-001"))
    r25=db.scalar(select(PairedReading).where(PairedReading.dataset_id==new.id,PairedReading.sample_code=="CG1-025"))
    r2=db.scalar(select(PairedReading).where(PairedReading.dataset_id==new.id,PairedReading.sample_code=="CG1-002"))
    assert (r1.reference_value,r1.candidate_value)==(10.5,11.0)
    assert (r25.reference_value,r25.candidate_value)==(34.0,88.0)
    assert (r2.reference_value,r2.candidate_value)==(11.0,12.0)
    old1=db.scalar(select(PairedReading).where(PairedReading.dataset_id==ds.id,PairedReading.sample_code=="CG1-001"))
    assert (old1.reference_value,old1.candidate_value)==(10.0,11.0)
    rev=db.get(DatasetRevision,out["revision_id"])
    assert rev.reason.startswith("试片读数抄错") and rev.created_by==ADMIN.email and rev.base_version==1
    stored=db.scalars(select(ReadingCorrection).where(ReadingCorrection.revision_id==rev.id)).all()
    assert {c.sample_code for c in stored}=={"CG1-001","CG1-025"}

def test_old_run_still_points_at_original_dataset(db):
    ds=db.scalar(select(PairDataset))
    out=svc.confirm_revision(db,ds.id,payload(),ADMIN)
    run=db.scalar(select(ComparisonRun))
    assert run.dataset_id==ds.id
    assert run.dataset_id!=out["new_dataset_id"]

def test_repeated_confirm_is_idempotent_no_extra_version(db):
    ds=db.scalar(select(PairDataset))
    p=payload()
    first=svc.confirm_revision(db,ds.id,p,ADMIN)
    second=svc.confirm_revision(db,ds.id,p,ADMIN)
    assert second["idempotent_hit"] is True
    assert second["new_dataset_id"]==first["new_dataset_id"]
    assert db.scalar(select(func.count()).select_from(PairDataset))==2
    assert db.scalar(select(func.count()).select_from(DatasetRevision))==1

def test_only_one_successor_per_version_concurrent_conflict(db):
    ds=db.scalar(select(PairDataset))
    svc.confirm_revision(db,ds.id,payload(corrections=[CorrectionItem(sample_code="CG1-001",reference_value=10.5)]),ADMIN)
    with pytest.raises(HTTPException) as e:
        svc.confirm_revision(db,ds.id,payload(corrections=[CorrectionItem(sample_code="CG1-002",reference_value=11.5)]),ADMIN)
    assert e.value.status_code==409 and "一个后继版本" in e.value.detail
    with pytest.raises(HTTPException) as e2:
        svc.preview_revision(db,ds.id,payload())
    assert e2.value.status_code==409

def test_stale_base_version_conflicts(db):
    ds=db.scalar(select(PairDataset))
    svc.confirm_revision(db,ds.id,payload(),ADMIN)
    new=db.scalar(select(PairDataset).where(PairDataset.revision_of_id==ds.id))
    with pytest.raises(HTTPException) as e:
        svc.confirm_revision(db,new.id,payload(base_version=1,
            corrections=[CorrectionItem(sample_code="CG1-001",reference_value=10.9)]),ADMIN)
    assert e.value.status_code==409 and "过期更正" in e.value.detail

def test_second_generation_revision_chains_on_latest(db):
    ds=db.scalar(select(PairDataset))
    v2=svc.confirm_revision(db,ds.id,payload(corrections=[CorrectionItem(sample_code="CG1-001",reference_value=10.5)]),ADMIN)
    ds2=db.get(PairDataset,v2["new_dataset_id"])
    v3=svc.confirm_revision(db,ds2.id,payload(base_version=2,
        corrections=[CorrectionItem(sample_code="CG1-002",candidate_value=50.0)]),ADMIN)
    assert v3["version"]==3
    ds3=db.get(PairDataset,v3["new_dataset_id"])
    assert ds3.revision_of_id==ds2.id
    r1=db.scalar(select(PairedReading).where(PairedReading.dataset_id==ds3.id,PairedReading.sample_code=="CG1-001"))
    r2=db.scalar(select(PairedReading).where(PairedReading.dataset_id==ds3.id,PairedReading.sample_code=="CG1-002"))
    assert r1.reference_value==10.5 and r2.candidate_value==50.0

def test_list_revisions_returns_full_chain_with_trail(db):
    ds=db.scalar(select(PairDataset))
    v2=svc.confirm_revision(db,ds.id,payload(corrections=[CorrectionItem(sample_code="CG1-001",reference_value=10.5)]),ADMIN)
    ds2=db.get(PairDataset,v2["new_dataset_id"])
    svc.confirm_revision(db,ds2.id,payload(base_version=2,
        corrections=[CorrectionItem(sample_code="CG1-002",candidate_value=50.0)]),ADMIN)
    chain_from_root=svc.list_revisions(db,ds.id)
    chain_from_leaf=svc.list_revisions(db,ds2.id)
    assert len(chain_from_root)==2 and len(chain_from_leaf)==2
    first=chain_from_root[0]
    assert first["version"]==2 and first["corrections"][0]["sample_code"]=="CG1-001"
    assert first["corrections"][0]["reference_before"]==10.0
    assert chain_from_root[1]["version"]==3

def test_reason_too_short_rejected_by_schema():
    with pytest.raises(ValidationError):
        RevisionInput(base_version=1,reason="错",corrections=[CorrectionItem(sample_code="CG1-001")])

def test_empty_correction_list_rejected():
    with pytest.raises(ValidationError):
        RevisionInput(base_version=1,reason="足够长的更正原因说明",corrections=[])

def test_missing_dataset_404(db):
    with pytest.raises(HTTPException) as e:
        svc.preview_revision(db,9999,payload())
    assert e.value.status_code==404
    with pytest.raises(HTTPException) as e:
        svc.list_revisions(db,9999)
    assert e.value.status_code==404
