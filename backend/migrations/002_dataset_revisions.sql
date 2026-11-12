-- Schema v2: sample-reading corrections (revision lineage).
-- v1 tables stay intact; existing datasets remain version=1 with NULL revision_of_id,
-- so old comparison runs and approved qualifications keep recomputing on original readings.
-- Fresh databases are created from SQLAlchemy metadata; these statements are the
-- idempotent upgrade path for a v1 MySQL volume (also applied automatically at startup).

ALTER TABLE pair_datasets
    ADD COLUMN version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN revision_of_id INTEGER NULL,
    ADD CONSTRAINT fk_pair_datasets_revision_of
        FOREIGN KEY (revision_of_id) REFERENCES pair_datasets (id);

CREATE TABLE IF NOT EXISTS dataset_revisions (
    id INTEGER NOT NULL AUTO_INCREMENT,
    parent_dataset_id INTEGER NOT NULL,
    new_dataset_id INTEGER NOT NULL,
    base_version INTEGER NOT NULL,
    reason VARCHAR(600) NOT NULL,
    correction_hash VARCHAR(64) NOT NULL,
    created_by VARCHAR(160) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dataset_revisions_parent (parent_dataset_id),
    UNIQUE KEY uq_dataset_revisions_hash (correction_hash),
    CONSTRAINT fk_dataset_revisions_parent FOREIGN KEY (parent_dataset_id) REFERENCES pair_datasets (id),
    CONSTRAINT fk_dataset_revisions_new FOREIGN KEY (new_dataset_id) REFERENCES pair_datasets (id)
);

CREATE TABLE IF NOT EXISTS reading_corrections (
    id INTEGER NOT NULL AUTO_INCREMENT,
    revision_id INTEGER NOT NULL,
    sample_code VARCHAR(80) NOT NULL,
    reference_before FLOAT NOT NULL,
    reference_after FLOAT NOT NULL,
    candidate_before FLOAT NOT NULL,
    candidate_after FLOAT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_reading_corrections_revision_sample (revision_id, sample_code),
    CONSTRAINT fk_reading_corrections_revision FOREIGN KEY (revision_id) REFERENCES dataset_revisions (id)
);

-- Natural keys: dataset_revisions.parent_dataset_id (one accepted successor per version),
--               dataset_revisions.correction_hash (idempotent repeated confirmations),
--               reading_corrections(revision_id, sample_code).
SELECT 'method-agree schema v2';
