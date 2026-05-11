import pytest
import uuid
from src.db.ingest_jobs import create_ingest_job, update_job_status, reset_failed_job
from src.db.pool import db_pool

@pytest.mark.asyncio
async def test_job_status_transitions():
    # This requires a running DB. If not available, skip.
    try:
        await db_pool.connect()
    except Exception as exc:
        pytest.skip(f"Database not available: {exc}")

    async with db_pool.get_pool().acquire() as conn:
        batch_id = str(uuid.uuid4())
        
        # We need a record in ingest_batches first due to FK
        await conn.execute(
            "INSERT INTO ingest_batches (batch_id, lot_hash, equipment_hash, total_records, payload_raw, records_summary, dispatched_at) "
            "VALUES ($1, 'h1', 'h2', 0, '{}', '{}', NOW())", 
            batch_id
        )

        # 1. Create
        await create_ingest_job(conn, batch_id)
        row = await conn.fetchrow("SELECT status FROM ingest_jobs WHERE batch_id = $1", batch_id)
        assert row["status"] == "PENDING"

        # 2. Update to Processing
        await update_job_status(conn, batch_id, "PROCESSING")
        row = await conn.fetchrow("SELECT status FROM ingest_jobs WHERE batch_id = $1", batch_id)
        assert row["status"] == "PROCESSING"

        # 3. Fail
        await update_job_status(conn, batch_id, "FAILED", error="Test error")
        row = await conn.fetchrow("SELECT status, retry_count, last_error FROM ingest_jobs WHERE batch_id = $1", batch_id)
        assert row["status"] == "FAILED"
        assert row["retry_count"] == 1
        assert row["last_error"] == "Test error"

        # 4. Reset
        await reset_failed_job(conn, batch_id)
        row = await conn.fetchrow("SELECT status, last_error FROM ingest_jobs WHERE batch_id = $1", batch_id)
        assert row["status"] == "PENDING"
        assert row["last_error"] is None

        # Clean up
        await conn.execute("DELETE FROM ingest_jobs WHERE batch_id = $1", batch_id)
        await conn.execute("DELETE FROM ingest_batches WHERE batch_id = $1", batch_id)
    
    await db_pool.disconnect()
