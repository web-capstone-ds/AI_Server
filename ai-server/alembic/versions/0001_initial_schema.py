"""initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ingest_batches (
            batch_id        UUID            PRIMARY KEY,
            lot_hash        TEXT            NOT NULL,
            equipment_hash  TEXT            NOT NULL,
            equipment_id    TEXT,
            total_records   INTEGER         NOT NULL,
            payload_raw     JSONB           NOT NULL,
            records_summary JSONB           NOT NULL,
            dispatched_at   TIMESTAMPTZ     NOT NULL,
            ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            pushed_to_backend BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS ingest_jobs (
            job_id          BIGSERIAL       PRIMARY KEY,
            batch_id        UUID            NOT NULL UNIQUE REFERENCES ingest_batches(batch_id) ON DELETE CASCADE,
            status          TEXT            NOT NULL DEFAULT 'PENDING',
            retry_count     INTEGER         NOT NULL DEFAULT 0,
            last_error      TEXT,
            updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS lot_embeddings (
            id              BIGSERIAL       PRIMARY KEY,
            batch_id        UUID            NOT NULL REFERENCES ingest_batches(batch_id) ON DELETE CASCADE,
            lot_hash        TEXT            NOT NULL,
            equipment_hash  TEXT            NOT NULL,
            equipment_id    TEXT,
            recipe_hash     TEXT            NOT NULL,
            chunk_type      TEXT            NOT NULL,
            chunk_text      TEXT            NOT NULL,
            embedding       vector(384)     NOT NULL,
            yield_pct       DOUBLE PRECISION,
            lot_status      TEXT,
            total_units     INTEGER,
            fail_count      INTEGER,
            dispatched_at   TIMESTAMPTZ     NOT NULL,
            ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS analysis_reports (
            id                  BIGSERIAL       PRIMARY KEY,
            report_id           UUID            NOT NULL UNIQUE,
            report_type         TEXT            NOT NULL,
            period_start        TIMESTAMPTZ     NOT NULL,
            period_end          TIMESTAMPTZ     NOT NULL,
            content             JSONB           NOT NULL,
            pushed_to_backend   BOOLEAN         NOT NULL DEFAULT FALSE,
            generated_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_ingest_batch_hash ON ingest_batches (lot_hash, equipment_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ingest_job_status ON ingest_jobs (status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lot_embeddings_batch ON lot_embeddings (batch_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lot_embeddings_recipe_hash ON lot_embeddings (recipe_hash, dispatched_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lot_embeddings_equipment ON lot_embeddings (equipment_hash, dispatched_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lot_embeddings_vector ON lot_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_analysis_reports_type_date ON analysis_reports (report_type, generated_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analysis_reports")
    op.execute("DROP TABLE IF EXISTS lot_embeddings")
    op.execute("DROP TABLE IF EXISTS ingest_jobs")
    op.execute("DROP TABLE IF EXISTS ingest_batches")
    op.execute("DROP EXTENSION IF EXISTS vector")
