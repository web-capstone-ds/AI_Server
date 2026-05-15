from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException
from src.db.pool import db_pool
from src.db.batches import list_batches, get_batch_by_id, get_latest_batches_per_equipment, aggregate_kpi_summary
from src.models.kpi import KpiSummaryResponse, ReportPeriod
from src.utils.auth import verify_backend_jwt
import structlog

router = APIRouter(prefix="/api/batches", tags=["batches"])
logger = structlog.get_logger()

@router.get("", response_model=List[dict])
async def get_batches(
    equipmentId: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    _ = Depends(verify_backend_jwt)
):
    """
    List batches with filtering and pagination.
    """
    # Parse dates
    try:
        start = datetime.fromisoformat(from_date) if from_date else None
        end = datetime.fromisoformat(to_date) if to_date else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO 8601.")
    offset = (page - 1) * size
    
    async with db_pool.get_pool().acquire() as conn:
        rows = await list_batches(conn, equipmentId, start, end, size, offset)
        return rows

@router.get("/latest", response_model=List[dict])
async def get_latest(
    _ = Depends(verify_backend_jwt)
):
    """
    Get the latest batch for each equipment.
    """
    async with db_pool.get_pool().acquire() as conn:
        rows = await get_latest_batches_per_equipment(conn)
        return rows

@router.get("/kpi-summary", response_model=KpiSummaryResponse)
async def get_kpi(
    equipmentId: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    _ = Depends(verify_backend_jwt)
):
    """
    Aggregate production and operation KPIs.
    """
    try:
        start = datetime.fromisoformat(from_date) if from_date else None
        end = datetime.fromisoformat(to_date) if to_date else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO 8601.")
    
    async with db_pool.get_pool().acquire() as conn:
        kpi_data = await aggregate_kpi_summary(conn, equipmentId, start, end)
        
        # Populate period for the response
        kpi_data["period"] = ReportPeriod(
            start=from_date or "earliest",
            end=to_date or "now"
        )
        
        # Ensure lists are present
        kpi_data.setdefault("topFailReasons", [])
        kpi_data.setdefault("equipmentDetails", [])
        
        return KpiSummaryResponse(**kpi_data)

@router.get("/{batchId}", response_model=dict)
async def get_detail(
    batchId: str,
    _ = Depends(verify_backend_jwt)
):
    """
    Get full batch details (raw payload).
    """
    async with db_pool.get_pool().acquire() as conn:
        batch = await get_batch_by_id(conn, batchId)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        return batch
