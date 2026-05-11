import asyncpg
from typing import Dict, Any, Optional
import structlog
import json
from src.models.dispatch_batch import DispatchBatch

logger = structlog.get_logger()

async def save_ingest_batch(conn: asyncpg.Connection, batch: DispatchBatch, records_summary: Dict[str, Any]):
    """
    Saves the full DispatchBatch as payload_raw and calculated records_summary.
    """
    query = """
    INSERT INTO ingest_batches (
        batch_id, lot_hash, equipment_hash, equipment_id, total_records,
        payload_raw, records_summary, dispatched_at
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """
    
    await conn.execute(
        query,
        batch.batchId,
        batch.lotHash,
        batch.equipmentHash,
        batch.equipmentId,
        batch.totalRecords,
        batch.model_dump_json(),  # Full raw payload
        json.dumps(records_summary),  # KPI fast-path summary
        batch.dispatchedAt
    )

async def check_batch_id_exists(conn: asyncpg.Connection, batch_id: str) -> Optional[Dict[str, Any]]:
    query = "SELECT lot_hash, equipment_hash FROM ingest_batches WHERE batch_id = $1"
    return await conn.fetchrow(query, batch_id)

async def get_latest_batches(
    conn: asyncpg.Connection,
    equipment_id: Optional[str] = None,
    limit: int = 50,
):
    query = """
    SELECT batch_id, lot_hash, equipment_hash, equipment_id, total_records,
           records_summary, dispatched_at, ingested_at
    FROM ingest_batches
    """
    params = []
    if equipment_id:
        params.append(equipment_id)
        query += " WHERE equipment_id = $1"

    params.append(limit)
    query += f" ORDER BY dispatched_at DESC LIMIT ${len(params)}"
    return await conn.fetch(query, *params)
