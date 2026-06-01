from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException
from src.db.pool import db_pool
from src.db.batches import list_batches, get_batch_by_id, get_latest_batch_full, aggregate_kpi_summary
from src.models.kpi import KpiSummaryResponse, ReportPeriod
from src.utils.auth import verify_backend_jwt
from src.utils.envelope import envelope
from src.pipeline.derived_stats import compute_derived
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

@router.get("/latest")
async def get_latest(
    equipmentId: Optional[str] = Query(None),
    _ = Depends(verify_backend_jwt)
):
    """
    Get the latest batch (full payload + derived stats) for an equipment.

    Returns the backend envelope {status, requestId, servedAt, data, error}
    where data = {"batch": <full payload_raw>, "derived": <DerivedBatchStats>}.
    If no batch exists, data is null (Spring treats it as empty -> mock fallback).
    """
    async with db_pool.get_pool().acquire() as conn:
        batch = await get_latest_batch_full(conn, equipmentId)
    if batch is None:
        return envelope(None)
    derived = compute_derived(batch)
    return envelope({"batch": batch, "derived": derived})

@router.get("/kpi-summary")
async def get_kpi(
    equipmentId: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    _ = Depends(verify_backend_jwt)
):
    """
    Aggregate production and operation KPIs.

    Returns the backend envelope where data maps to Spring's KpiSummaryData
    {period, summary: <KpiSummaryResponse>, groups: []}.
    """
    try:
        start = datetime.fromisoformat(from_date) if from_date else None
        end = datetime.fromisoformat(to_date) if to_date else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO 8601.")

    async with db_pool.get_pool().acquire() as conn:
        kpi_data = await aggregate_kpi_summary(conn, equipmentId, start, end)

        period = ReportPeriod(start=from_date or "earliest", end=to_date or "now")
        kpi_data["period"] = period

        # Ensure lists are present
        kpi_data.setdefault("topFailReasons", [])
        kpi_data.setdefault("equipmentDetails", [])

        summary = KpiSummaryResponse(**kpi_data)
        # Spring expects KpiSummaryData {period, summary, groups}; .summary() yields KpiSummaryResponse.
        data = {
            "period": period.model_dump(mode="json"),
            "summary": summary.model_dump(mode="json"),
            "groups": [],
        }
        return envelope(data)

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
