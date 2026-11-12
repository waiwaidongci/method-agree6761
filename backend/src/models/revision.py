from datetime import datetime
from sqlalchemy import String,ForeignKey,DateTime,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from src.config.database import Base
class DatasetRevision(Base):
    __tablename__="dataset_revisions"
    __table_args__=(UniqueConstraint("parent_dataset_id"),UniqueConstraint("correction_hash"))
    id:Mapped[int]=mapped_column(primary_key=True)
    parent_dataset_id:Mapped[int]=mapped_column(ForeignKey("pair_datasets.id"))
    new_dataset_id:Mapped[int]=mapped_column(ForeignKey("pair_datasets.id"))
    base_version:Mapped[int]
    reason:Mapped[str]=mapped_column(String(600))
    correction_hash:Mapped[str]=mapped_column(String(64))
    created_by:Mapped[str]=mapped_column(String(160))
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class ReadingCorrection(Base):
    __tablename__="reading_corrections"
    __table_args__=(UniqueConstraint("revision_id","sample_code"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    revision_id:Mapped[int]=mapped_column(ForeignKey("dataset_revisions.id"))
    sample_code:Mapped[str]=mapped_column(String(80))
    reference_before:Mapped[float]
    reference_after:Mapped[float]
    candidate_before:Mapped[float]
    candidate_after:Mapped[float]
