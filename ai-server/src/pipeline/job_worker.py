import asyncio
import json
import structlog
import httpx
from typing import Optional
from src.config import settings
from src.models.dispatch_batch import DispatchBatch
from src.db.pool import db_pool
from src.db.ingest_jobs import update_job_status
from src.pipeline.chunker import create_chunks
from src.pipeline.embedder import embedder
from src.db.embeddings import save_embeddings
from src.pipeline.jobs import job_tracker

logger = structlog.get_logger()

# Limit background job concurrency as requested (concurrency 1~2)
_job_semaphore = asyncio.Semaphore(2)

async def _notify_backend(batch_id: str, batch: DispatchBatch):
    backend_url = settings.BACKEND_SERVER_URL
    if not backend_url:
        return
    payload = {
        "batchId": batch_id,
        "equipmentId": batch.equipmentId,
        "yieldPct": batch.lotSummary.yield_pct if batch.lotSummary else None,
        "judgment": batch.oracleAnalysis[0].judgment if batch.oracleAnalysis else None
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{backend_url}/api/batches/notify", json=payload)
            resp.raise_for_status()
    except Exception as e:
        logger.warning("backend_notify_failed", batch_id=batch_id, error=str(e))

async def get_batch_payload(batch_id: str) -> Optional[DispatchBatch]:
    """
    Fetch the raw payload from the database to allow re-processing.
    """
    async with db_pool.get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT payload_raw FROM ingest_batches WHERE batch_id = $1", 
            batch_id
        )
        if row and row["payload_raw"]:
            data = row["payload_raw"]
            if isinstance(data, str):
                data = json.loads(data)
            return DispatchBatch(**data)
    return None

async def process_batch_job(batch_id: str, batch: Optional[DispatchBatch] = None):
    """
    Background worker that handles Chunking -> Embedding -> Vector storage.
    Can be triggered with an existing batch object or just a batch_id (re-processing).
    """
    job_tracker.add_job(batch_id)
    try:
        async with _job_semaphore:
            logger.info("job_processing_started", batch_id=batch_id)
            
            async with db_pool.get_pool().acquire() as conn:
                # Idempotency: Check if already completed
                job = await conn.fetchrow("SELECT status FROM ingest_jobs WHERE batch_id = $1", batch_id)
                if job and job["status"] == "COMPLETED":
                    logger.info("job_already_completed", batch_id=batch_id)
                    return

                try:
                    await update_job_status(conn, batch_id, "PROCESSING")
                    
                    # If batch object not provided (e.g., re-processing from failed state), fetch from DB
                    if not batch:
                        batch = await get_batch_payload(batch_id)
                        if not batch:
                            raise ValueError(f"Payload not found for batch_id {batch_id}")

                    # 1. Preprocessing & Chunking
                    chunks = create_chunks(batch)
                    if not chunks:
                        logger.warning("no_chunks_created", batch_id=batch_id)
                        await update_job_status(conn, batch_id, "COMPLETED") # Nothing to do, but success
                        return
                    
                    # 2. Embedding (Local CPU model)
                    texts = [c.text for c in chunks]
                    embeddings = embedder.embed_texts(texts)
                    
                    # 3. Vector DB storage
                    await save_embeddings(conn, batch, chunks, embeddings)
                    
                    # Notify web backend after processing is finished
                    await _notify_backend(batch_id, batch)
                    
                    await update_job_status(conn, batch_id, "COMPLETED")
                    logger.info("job_processing_completed", batch_id=batch_id, chunk_count=len(chunks))
                    
                except Exception as e:
                    logger.error("job_processing_failed", batch_id=batch_id, error=str(e))
                    await update_job_status(conn, batch_id, "FAILED", error=str(e))
                    # Do not raise here, as it's a background task
    finally:
        job_tracker.remove_job(batch_id)
