-- Q24-07: additive repair for the exact 0004 bytes introduced in a42a1eb.
-- The original length-only constraint and recorded migration checksum remain.
-- Executed and recorded by migrate.py in the same transaction as pending SQL.
ALTER TABLE rick_ingestion_jobs
    ADD CONSTRAINT rick_ingestion_jobs_operation_v2_ck
    CHECK (operation ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$');
