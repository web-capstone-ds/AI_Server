from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from src.db.pool import db_pool
from src.db.reports import get_latest_report
from src.scheduler.report_scheduler import report_scheduler
from src.utils.auth import verify_backend_jwt
import structlog

router = APIRouter(prefix="/api/report", tags=["report"])
logger = structlog.get_logger()

@router.post("/{report_type}")
async def trigger_report(
    report_type: str,
    background_tasks: BackgroundTasks,
    _ = Depends(verify_backend_jwt)
):
    if report_type not in ["daily", "weekly"]:
        raise HTTPException(status_code=400, detail="Invalid report type")
    
    logger.info("report_trigger_received", type=report_type)
    
    if report_type == "daily":
        background_tasks.add_task(report_scheduler.run_daily_report)
    else:
        background_tasks.add_task(report_scheduler.run_weekly_report)
        
    return {"status": "accepted", "message": f"{report_type} report generation started in background"}

@router.get("/{report_type}/latest")
async def get_latest(
    report_type: str,
    _ = Depends(verify_backend_jwt)
):
    if report_type not in ["daily", "weekly"]:
        raise HTTPException(status_code=400, detail="Invalid report type")
        
    async with db_pool.get_pool().acquire() as conn:
        report = await get_latest_report(conn, report_type)
        if not report:
            raise HTTPException(status_code=404, detail="No report found")
        return report
