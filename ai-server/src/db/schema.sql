CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS ingest_batches (
    batch_id        UUID            PRIMARY KEY,
    lot_hash        TEXT            NOT NULL,
    equipment_hash  TEXT            NOT NULL,
    equipment_id    TEXT,
    total_records   INTEGER         NOT NULL,
    payload_raw     JSONB           NOT NULL,
    records_summary JSONB           NOT NULL,
    dispatched_at   TIMESTAMPTZ     NOT NULL,
    ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    job_id          BIGSERIAL       PRIMARY KEY,
    batch_id        UUID            NOT NULL UNIQUE REFERENCES ingest_batches(batch_id) ON DELETE CASCADE,
    status          TEXT            NOT NULL DEFAULT 'PENDING',
    retry_count     INTEGER         NOT NULL DEFAULT 0,
    last_error      TEXT,
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS lot_embeddings (
    id              BIGSERIAL       PRIMARY KEY,
    batch_id        UUID            NOT NULL REFERENCES ingest_batches(batch_id) ON DELETE CASCADE,
    lot_hash        TEXT            NOT NULL,
    equipment_hash  TEXT            NOT NULL,
    equipment_id    TEXT,
    recipe_id       TEXT            NOT NULL,
    chunk_type      TEXT            NOT NULL,
    chunk_text      TEXT            NOT NULL,
    embedding       vector(384)     NOT NULL,
    yield_pct       DOUBLE PRECISION,
    lot_status      TEXT,
    total_units     INTEGER,
    fail_count      INTEGER,
    dispatched_at   TIMESTAMPTZ     NOT NULL,
    ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingest_batch_hash
    ON ingest_batches (lot_hash, equipment_hash);

CREATE INDEX IF NOT EXISTS idx_ingest_job_status
    ON ingest_jobs (status);

CREATE INDEX IF NOT EXISTS idx_lot_embeddings_batch
    ON lot_embeddings (batch_id);

CREATE INDEX IF NOT EXISTS idx_lot_embeddings_recipe
    ON lot_embeddings (recipe_id, dispatched_at DESC);

CREATE INDEX IF NOT EXISTS idx_lot_embeddings_equipment
    ON lot_embeddings (equipment_hash, dispatched_at DESC);

CREATE INDEX IF NOT EXISTS idx_lot_embeddings_vector
    ON lot_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
