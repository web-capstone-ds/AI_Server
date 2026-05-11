from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from src.models.dispatch_batch import DispatchBatch, IngestResponse
from src.utils.auth import verify_ingest_api_key
from src.db.pool import db_pool
from src.db.batches import save_ingest_batch, check_batch_id_exists
from src.db.ingest_jobs import create_ingest_job
from src.pipeline.job_worker import process_batch_job
import structlog

router = APIRouter(prefix="/api", tags=["ingest"])
logger = structlog.get_logger()

@router.post("/ingest", response_model=IngestResponse)
async def ingest_batch(
    batch: DispatchBatch,
    background_tasks: BackgroundTasks,
    _ = Depends(verify_ingest_api_key)
):
    batch_id_str = str(batch.batchId)
    logger.info("ingest_received", batch_id=batch_id_str, lot_hash=batch.lotHash)
    
    async with db_pool.get_pool().acquire() as conn:
        # 1. Idempotency Check
        existing = await check_batch_id_exists(conn, batch_id_str)
        if existing:
            # If same batchId but different hashes -> Conflict 409
            if existing['lot_hash'] != batch.lotHash or existing['equipment_hash'] != batch.equipmentHash:
                logger.warning("ingest_conflict", batch_id=batch_id_str)
                raise HTTPException(status_code=409, detail="Batch ID conflict with different data")
            
            # If same batchId and same hashes -> Success 200 (duplicate_accepted)
            logger.info("ingest_duplicate", batch_id=batch_id_str)
            return IngestResponse(status="duplicate_accepted", batchId=batch_id_str)
        
        # 2. Pre-calculate summary stats for records_summary (minimal for A1)
        records_summary = {
            "total": len(batch.records),
            "pass": sum(1 for r in batch.records if r.overall_result == "PASS"),
            "fail": sum(1 for r in batch.records if r.overall_result == "FAIL"),
        }
        
        # 3. Store raw payload and metadata
        try:
            async with conn.transaction():
                await save_ingest_batch(conn, batch, records_summary)
                await create_ingest_job(conn, batch_id_str)
                logger.info("ingest_stored", batch_id=batch_id_str)
        except Exception as e:
            logger.error("ingest_storage_failed", batch_id=batch_id_str, error=str(e))
            raise HTTPException(status_code=500, detail="Database storage failed")

    # 4. Enqueue background processing
    background_tasks.add_task(process_batch_job, batch_id_str)
    
    return IngestResponse(status="accepted", batchId=batch_id_str)
