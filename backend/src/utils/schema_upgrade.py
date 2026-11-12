from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

def ensure_revision_schema(engine):
    """Idempotent v2 upgrade for volumes created under schema v1.

    create_all() only materialises missing tables; columns added to an existing
    table must be migrated explicitly. Fresh databases already match the model
    metadata, and SQLite test databases are created from metadata directly.
    """
    if engine.dialect.name!="mysql":
        return
    with engine.begin() as conn:
        cols={row[0] for row in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=DATABASE() AND table_name='pair_datasets'"))}
        if "version" not in cols:
            conn.execute(text("ALTER TABLE pair_datasets ADD COLUMN version INTEGER NOT NULL DEFAULT 1"))
        if "revision_of_id" not in cols:
            conn.execute(text(
                "ALTER TABLE pair_datasets ADD COLUMN revision_of_id INTEGER NULL, "
                "ADD CONSTRAINT fk_pair_datasets_revision_of "
                "FOREIGN KEY (revision_of_id) REFERENCES pair_datasets(id)"))

def raise_revision_conflict(exc:IntegrityError):
    message=str(getattr(exc,"orig",exc))
    if "parent_dataset_id" in message or "correction_hash" in message:
        raise HTTPException(409,"该版本的修订版已存在（并发更正仅接纳一个后继版本，或相同更正已确认过）")
    raise exc
