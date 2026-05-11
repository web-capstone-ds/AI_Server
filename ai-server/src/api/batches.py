from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from src.db.pool import db_pool
from src.db.batches import get_latest_batches
from src.models.kpi import KpiSummaryResponse
from src.utils.auth import verify_backend_jwt
import structlog

router = APIRouter(prefix="/api/batches", tags=["batches"])
logger = structlog.get_logger()

@router.get("", response_model=List[dict])
async def list_batches(
    equipmentId: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    _ = Depends(verify_backend_jwt)
):
    async with db_pool.get_pool().acquire() as conn:
        rows = await get_latest_batches(conn, equipmentId, limit)
        return [dict(row) for row in rows]

@router.get("/kpi-summary", response_model=KpiSummaryResponse)
async def get_kpi_summary(
    equipmentId: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    _ = Depends(verify_backend_jwt)
):
    # This will be a complex aggregation query in the real world
    # For Task A1, we provide a placeholder response structure
    logger.info("kpi_summary_requested", equipmentId=equipmentId)
    
    # Placeholder response
    return KpiSummaryResponse(
        period={"start": from_date or "now-24h", "end": to_date or "now"},
        totalUnits=10000,
        totalInspected=9800,
        totalFail=200,
        avgYieldPct=98.0,
        avgUph=450.5,
        marginalCount=5,
        dangerCount=1,
        warningCount=3,
        avgAvailabilityPct=92.5,
        totalDowntimeMin=120.0,
        activeEquipmentCount=4,
        totalEquipmentCount=5,
        topFailReasons=[{"reason_code": "ET52", "count": 120}],
        equipmentDetails=[]
    )
