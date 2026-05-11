import asyncpg
from typing import Optional
import structlog

logger = structlog.get_logger()

async def create_ingest_job(conn: asyncpg.Connection, batch_id: str):
    query = """
    INSERT INTO ingest_jobs (batch_id, status, updated_at)
    VALUES ($1, 'PENDING', NOW())
    ON CONFLICT (batch_id) DO NOTHING
    """
    await conn.execute(query, batch_id)

async def update_job_status(
    conn: asyncpg.Connection, 
    batch_id: str, 
    status: str, 
    error: Optional[str] = None
):
    query = """
    UPDATE ingest_jobs
    SET status = $2, last_error = $3, updated_at = NOW(),
        retry_count = CASE WHEN $2 = 'FAILED' THEN retry_count + 1 ELSE retry_count END
    WHERE batch_id = $1
    """
    await conn.execute(query, batch_id, status, error)

async def reset_failed_job(conn: asyncpg.Connection, batch_id: str):
    """
    Resets a failed job to PENDING to allow re-processing.
    """
    query = """
    UPDATE ingest_jobs
    SET status = 'PENDING', last_error = NULL, updated_at = NOW()
    WHERE batch_id = $1 AND status = 'FAILED'
    """
    await conn.execute(query, batch_id)
