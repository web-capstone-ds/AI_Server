import json
from datetime import datetime
import asyncpg
from src.models.report import AnalysisReport
import structlog

logger = structlog.get_logger()

async def save_report(conn: asyncpg.Connection, report: AnalysisReport):
    query = """
    INSERT INTO analysis_reports (
        report_id, report_type, period_start, period_end, content, generated_at
    ) VALUES ($1, $2, $3, $4, $5, $6)
    """
    await conn.execute(
        query,
        report.reportId,
        report.reportType,
        datetime.fromisoformat(report.period.start),
        datetime.fromisoformat(report.period.end),
        json.dumps(report.model_dump(), default=str),
        datetime.fromisoformat(report.generatedAt)
    )
    logger.info("report_saved_to_db", report_id=report.reportId)

async def mark_report_pushed(conn: asyncpg.Connection, report_id: str):
    query = "UPDATE analysis_reports SET pushed_to_backend = TRUE WHERE report_id = $1"
    await conn.execute(query, report_id)

async def get_latest_report(conn: asyncpg.Connection, report_type: str):
    query = "SELECT content FROM analysis_reports WHERE report_type = $1 ORDER BY generated_at DESC LIMIT 1"
    row = await conn.fetchrow(query, report_type)
    return json.loads(row['content']) if row else None
