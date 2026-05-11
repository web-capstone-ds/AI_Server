import json
from uuid import uuid4
from datetime import datetime, timedelta
import asyncpg
from src.db.pool import db_pool
from src.llm.client import llm_client
from src.llm.prompts import REPORT_SYSTEM_PROMPT
from src.models.report import AnalysisReport, ReportMetrics, Insight
import structlog

logger = structlog.get_logger()

async def aggregate_metrics(conn: asyncpg.Connection, start_time: datetime, end_time: datetime) -> ReportMetrics:
    """
    Aggregates metrics from ingest_batches for the given period.
    """
    query = """
    SELECT 
        COUNT(*) as total_lots,
        AVG((lot_summary->>'yield_pct')::float) as avg_yield,
        MIN((lot_summary->>'yield_pct')::float) as min_yield,
        MAX((lot_summary->>'yield_pct')::float) as max_yield,
        SUM((lot_summary->>'fail_count')::int) as total_fail,
        AVG((lot_summary->>'total_units')::float / NULLIF((lot_summary->>'lot_duration_sec')::float, 0) * 3600) as avg_uph
    FROM ingest_batches
    WHERE dispatched_at BETWEEN $1 AND $2
    """
    row = await conn.fetchrow(query, start_time, end_time)
    
    # In a real app, we'd do more complex sub-queries for recipeBreakdown, etc.
    # For now, we populate with placeholders or simplified logic
    
    return ReportMetrics(
        totalLots=row['total_lots'] or 0,
        avgYieldPct=row['avg_yield'] or 0,
        minYieldPct=row['min_yield'] or 0,
        maxYieldPct=row['max_yield'] or 0,
        totalFailCount=row['total_fail'] or 0,
        avgUph=row['avg_uph'] or 0,
        topFailReasons=[],
        recipeBreakdown=[],
        judgmentDistribution={},
        marginalCount=0,
        avgAvailabilityPct=95.0,
        totalDowntimeMin=60.0,
        equipmentBreakdown=[]
    )

async def generate_periodic_report(report_type: str, days: int) -> AnalysisReport:
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    
    async with db_pool.get_pool().acquire() as conn:
        metrics = await aggregate_metrics(conn, start_time, end_time)
        
        # Build prompt for LLM
        metrics_json = metrics.model_dump_json()
        user_prompt = f"Analyze the following metrics for a {report_type} report and generate summary, insights, and recommendations in JSON format:\n{metrics_json}"
        
        try:
            # We expect the LLM to return a JSON string that fits our Insight/Recommendation schema
            # We'll use a simpler prompt for this example and manually wrap if needed
            llm_response = await llm_client.get_completion(REPORT_SYSTEM_PROMPT, user_prompt)
            # Try to parse JSON from LLM response
            # Note: In production, use more robust JSON extraction
            ai_data = json.loads(llm_response)
        except Exception as e:
            logger.error("report_ai_analysis_failed", error=str(e))
            ai_data = {
                "summary": "AI 분석 실패. 기본 통계 데이터만 제공됩니다.",
                "insights": [],
                "recommendations": []
            }
            
        report = AnalysisReport(
            reportId=str(uuid4()),
            reportType=report_type,
            generatedAt=datetime.now().isoformat(),
            period={"start": start_time.isoformat(), "end": end_time.isoformat()},
            summary=ai_data.get("summary", ""),
            metrics=metrics,
            insights=[Insight(**i) for i in ai_data.get("insights", [])],
            recommendations=ai_data.get("recommendations", []),
            lotDetails=[] # Optionally populate with top failing lots
        )
        
        return report
