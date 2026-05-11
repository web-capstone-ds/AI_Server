import asyncio
import json
import structlog
from typing import Optional
from src.models.dispatch_batch import DispatchBatch
from src.db.pool import db_pool
from src.db.ingest_jobs import update_job_status
from src.pipeline.chunker import create_chunks
from src.pipeline.embedder import embedder
from src.db.embeddings import save_embeddings

logger = structlog.get_logger()

# Limit background job concurrency as requested (concurrency 1~2)
_job_semaphore = asyncio.Semaphore(2)

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
            # payload_raw is stored as JSONB string or dict depending on asyncpg/postgres setup
            # DispatchBatch handles both if passed correctly
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
                
                await update_job_status(conn, batch_id, "COMPLETED")
                logger.info("job_processing_completed", batch_id=batch_id, chunk_count=len(chunks))
                
            except Exception as e:
                logger.error("job_processing_failed", batch_id=batch_id, error=str(e))
                await update_job_status(conn, batch_id, "FAILED", error=str(e))
                # Do not raise here, as it's a background task
