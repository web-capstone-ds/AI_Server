import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from src.config import settings
from src.llm.report_generator import generate_periodic_report
from src.db.pool import db_pool
from src.db.reports import save_report, mark_report_pushed
import structlog

logger = structlog.get_logger()

class ReportScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()

    async def push_report_to_backend(self, report):
        """
        Push the generated report to Web Backend.
        """
        url = f"{settings.BACKEND_SERVER_URL}/api/reports"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # In a real app, include JWT auth header
                response = await client.post(url, json=report.model_dump())
                if response.is_success:
                    logger.info("report_pushed_successfully", report_id=report.reportId)
                    return True
                else:
                    logger.error("report_push_failed", status=response.status_code, body=response.text)
        except Exception as e:
            logger.error("report_push_exception", error=str(e))
        return False

    async def run_daily_report(self):
        logger.info("daily_report_job_started")
        try:
            report = await generate_periodic_report("daily", 1)
            async with db_pool.get_pool().acquire() as conn:
                await save_report(conn, report)
                if await self.push_report_to_backend(report):
                    await mark_report_pushed(conn, report.reportId)
        except Exception as e:
            logger.error("daily_report_job_failed", error=str(e))

    async def run_weekly_report(self):
        logger.info("weekly_report_job_started")
        try:
            report = await generate_periodic_report("weekly", 7)
            async with db_pool.get_pool().acquire() as conn:
                await save_report(conn, report)
                if await self.push_report_to_backend(report):
                    await mark_report_pushed(conn, report.reportId)
        except Exception as e:
            logger.error("weekly_report_job_failed", error=str(e))

    def start(self):
        self.scheduler.add_job(
            self.run_daily_report, 
            CronTrigger.from_crontab(settings.DAILY_REPORT_CRON)
        )
        self.scheduler.add_job(
            self.run_weekly_report, 
            CronTrigger.from_crontab(settings.WEEKLY_REPORT_CRON)
        )
        self.scheduler.start()
        logger.info("report_scheduler_started", 
                    daily_cron=settings.DAILY_REPORT_CRON, 
                    weekly_cron=settings.WEEKLY_REPORT_CRON)

    def stop(self):
        self.scheduler.shutdown()
        logger.info("report_scheduler_stopped")

report_scheduler = ReportScheduler()
