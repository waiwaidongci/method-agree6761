import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from fastapi import HTTPException

from src.config.database import Base,get_db
from src.models import Instrument,PairDataset,PairedReading,DatasetRevision
from src.main import app
from src.middlewares import audit as audit_mw
from src.utils.auth import current_user

engine=create_engine("sqlite://",connect_args={"check_same_thread":False},
                     poolclass=StaticPool)
Session=sessionmaker(bind=engine,expire_on_commit=False)
audit_mw.Session=Session

class FakeUser:
    def __init__(self,email,role):self.email=email;self.role=role
EDITOR=FakeUser("analyst@ciguang.demo","analyst")
VIEWER=FakeUser("viewer@ciguang.demo","viewer")

@pytest.fixture()
def client():
    Base.metadata.create_all(engine)
    s=Session()
    ref=Instrument(code="CG-R01",name="ref",serial="s1",unit="%",lower=0,upper=100)
    cand=Instrument(code="CG-N02",name="cand",serial="s2",unit="%",lower=0,upper=100)
    s.add_all([ref,cand]);s.flush()
    ds=PairDataset(name="N02 · API样本",reference_id=ref.id,candidate_id=cand.id,
                   source_file="pairs.csv",note="orig",version=1)
    s.add(ds);s.flush()
    for i in range(22):
        s.add(PairedReading(dataset_id=ds.id,sample_code=f"CG1-{i+1:03d}",
                            reference_value=10.0+i,candidate_value=11.0+i))
    s.commit();ds_id=ds.id;s.close()
    def override_db():
        db=Session()
        try:yield db
        finally:db.close()
    app.dependency_overrides[get_db]=override_db
    app.dependency_overrides[current_user]=lambda:EDITOR
    c=TestClient(app)
    yield c,ds_id
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)

def body(base=1,code="CG1-001",**kw):
    corr={"sample_code":code,**kw}
    return {"base_version":base,"reason":"纸质记录复核发现抄录错误，按原始记录单更正","corrections":[corr]}

def test_datasets_list_carries_version_fields(client):
    c,ds_id=client
    rows=c.get("/datasets").json()
    target=next(r for r in rows if r["id"]==ds_id)
    assert target["version"]==1 and target["revision_of_id"] is None and target["has_successor"] is False

def test_preview_then_confirm_flow(client):
    c,ds_id=client
    prev=c.post(f"/datasets/{ds_id}/revisions/preview",json=body(reference_value=10.5))
    assert prev.status_code==200,prev.text
    p=prev.json()
    assert p["change_count"]==1 and p["base_version"]==1 and p["changes"][0]["reference_after"]==10.5
    ok=c.post(f"/datasets/{ds_id}/revisions/confirm",json=body(reference_value=10.5))
    assert ok.status_code==201,ok.text
    out=ok.json()
    assert out["version"]==2 and out["idempotent_hit"] is False
    listing=c.get("/datasets").json()
    root=next(r for r in listing if r["id"]==ds_id)
    leaf=next(r for r in listing if r["id"]==out["new_dataset_id"])
    assert root["has_successor"] is True
    assert leaf["version"]==2 and leaf["revision_of_id"]==ds_id and leaf["row_count"]==22
    readings=c.get(f"/readings?dataset_id={out['new_dataset_id']}&limit=100").json()
    assert readings["total"]==22
    first=next(r for r in readings["rows"] if r["sample_code"]=="CG1-001")
    untouched=next(r for r in readings["rows"] if r["sample_code"]=="CG1-002")
    assert first["reference_value"]==10.5 and untouched["reference_value"]==11.0

def test_repeated_confirm_returns_same_dataset(client):
    c,ds_id=client
    payload=body(reference_value=10.5)
    first=c.post(f"/datasets/{ds_id}/revisions/confirm",json=payload).json()
    second=c.post(f"/datasets/{ds_id}/revisions/confirm",json=payload).json()
    assert second["idempotent_hit"] is True
    assert second["new_dataset_id"]==first["new_dataset_id"]
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(PairDataset))==2
        assert db.scalar(select(func.count()).select_from(DatasetRevision))==1

def test_second_concurrent_correction_conflicts(client):
    c,ds_id=client
    assert c.post(f"/datasets/{ds_id}/revisions/confirm",json=body(reference_value=10.5)).status_code==201
    conflict=c.post(f"/datasets/{ds_id}/revisions/confirm",json=body(code="CG1-002",reference_value=11.9))
    assert conflict.status_code==409 and "一个后继版本" in conflict.json()["detail"]

def test_duplicate_revision_row_raises_clean_conflict():
    from sqlalchemy.exc import IntegrityError
    from src.utils.schema_upgrade import raise_revision_conflict
    def fake(message):
        return IntegrityError("INSERT dataset_revisions",{},Exception(message))
    for message in ("(1062, \"Duplicate entry '7' for key 'dataset_revisions.parent_dataset_id'\")",
                    "UNIQUE constraint failed: dataset_revisions.correction_hash"):
        with pytest.raises(HTTPException) as e:
            raise_revision_conflict(fake(message))
        assert e.value.status_code==409
    with pytest.raises(IntegrityError):
        raise_revision_conflict(fake("some unrelated unique failure"))

def test_stale_base_version_conflicts(client):
    c,ds_id=client
    v2=c.post(f"/datasets/{ds_id}/revisions/confirm",json=body(reference_value=10.5)).json()
    stale=c.post(f"/datasets/{v2['new_dataset_id']}/revisions/confirm",
                 json=body(base=1,reference_value=10.9))
    assert stale.status_code==409 and "过期更正" in stale.json()["detail"]

def test_illegal_value_returns_whole_order_422_and_creates_nothing(client):
    c,ds_id=client
    bad=c.post(f"/datasets/{ds_id}/revisions/preview",json=body(code="CG1-001",candidate_value=999))
    assert bad.status_code==422
    unknown=c.post(f"/datasets/{ds_id}/revisions/confirm",json=body(code="GHOST",reference_value=5))
    assert unknown.status_code==422 and "整单退回" in unknown.json()["detail"]
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(DatasetRevision))==0
        assert db.scalar(select(func.count()).select_from(PairDataset))==1

def test_viewer_cannot_correct(client):
    c,ds_id=client
    app.dependency_overrides[current_user]=lambda:VIEWER
    denied=c.post(f"/datasets/{ds_id}/revisions/confirm",json=body(reference_value=10.5))
    assert denied.status_code==403

def test_revision_history_endpoint(client):
    c,ds_id=client
    v2=c.post(f"/datasets/{ds_id}/revisions/confirm",json=body(reference_value=10.5)).json()
    v3=c.post(f"/datasets/{v2['new_dataset_id']}/revisions/confirm",
              json=body(base=2,code="CG1-002",candidate_value=50)).json()
    chain=c.get(f"/datasets/{ds_id}/revisions").json()
    assert [r["version"] for r in chain]==[2,3]
    assert chain[0]["reason"].startswith("纸质记录") and chain[0]["created_by"]==EDITOR.email
    assert chain[0]["corrections"][0]["reference_before"]==10.0
    assert chain[0]["corrections"][0]["reference_after"]==10.5
    leaf_chain=c.get(f"/datasets/{v3['new_dataset_id']}/revisions").json()
    assert len(leaf_chain)==2
