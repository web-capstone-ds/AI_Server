import json
from uuid import uuid4
from datetime import datetime, timedelta
import asyncpg
from src.db.pool import db_pool
from src.llm.client import llm_client
from src.llm.prompts import REPORT_SYSTEM_PROMPT
from src.models.report import AnalysisReport, ReportMetrics, Insight, RecipeMetric, EquipmentMetric
import structlog

logger = structlog.get_logger()

async def aggregate_metrics(conn: asyncpg.Connection, start_time: datetime, end_time: datetime) -> ReportMetrics:
    """
    Aggregates metrics from ingest_batches for the given period.
    """
    # 1. Production Summary
    prod_query = """
    SELECT
        COUNT(*) as total_lots,
        AVG((payload_raw->'lotSummary'->>'yield_pct')::float) as avg_yield,
        MIN((payload_raw->'lotSummary'->>'yield_pct')::float) as min_yield,
        MAX((payload_raw->'lotSummary'->>'yield_pct')::float) as max_yield,
        SUM((payload_raw->'lotSummary'->>'fail_count')::int) as total_fail,
        AVG(
            (payload_raw->'lotSummary'->>'total_units')::float
            / NULLIF((payload_raw->'lotSummary'->>'lot_duration_sec')::float, 0) * 3600
        ) as avg_uph
    FROM ingest_batches
    WHERE dispatched_at BETWEEN $1 AND $2
    """
    prod_row = await conn.fetchrow(prod_query, start_time, end_time)

    # 2. Recipe Breakdown
    recipe_query = """
    SELECT
        payload_raw->'lotSummary'->>'recipe_id' as recipe_id,
        AVG((payload_raw->'lotSummary'->>'yield_pct')::float) as avg_yield,
        COUNT(*) as total_lots
    FROM ingest_batches
    WHERE dispatched_at BETWEEN $1 AND $2
    GROUP BY recipe_id
    """
    recipe_rows = await conn.fetch(recipe_query, start_time, end_time)

    # 3. Equipment base metrics (yield, uph)
    equip_query = """
    SELECT
        equipment_id,
        AVG((payload_raw->'lotSummary'->>'yield_pct')::float) as avg_yield,
        AVG(
            (payload_raw->'lotSummary'->>'total_units')::float
            / NULLIF((payload_raw->'lotSummary'->>'lot_duration_sec')::float, 0) * 3600
        ) as avg_uph
    FROM ingest_batches
    WHERE dispatched_at BETWEEN $1 AND $2
    GROUP BY equipment_id
    """
    equip_rows = await conn.fetch(equip_query, start_time, end_time)

    # 4. Oracle judgment distribution + marginal count
    oracle_dist_query = """
    SELECT
        payload_raw->'oracleAnalysis'->0->>'judgment' as judgment,
        COUNT(*) as cnt
    FROM ingest_batches
    WHERE dispatched_at BETWEEN $1 AND $2
        AND payload_raw->'oracleAnalysis'->0->>'judgment' IS NOT NULL
    GROUP BY judgment
    """
    oracle_rows = await conn.fetch(oracle_dist_query, start_time, end_time)
    judgment_dist = {r['judgment']: r['cnt'] for r in oracle_rows}

    marginal_query = """
    SELECT COUNT(*) as cnt
    FROM ingest_batches
    WHERE dispatched_at BETWEEN $1 AND $2
        AND (
            payload_raw->'oracleAnalysis'->0->'violated_rules'->>'yield_grade' = 'MARGINAL'
            OR payload_raw->'oracleAnalysis'->0->>'judgment' = 'WARNING'
        )
    """
    marginal_row = await conn.fetchrow(marginal_query, start_time, end_time)

    # 5. Availability & downtime from statusHistory (time-weighted, per batch)
    avail_query = """
    WITH sh AS (
        SELECT
            batch_id,
            equipment_id,
            (rec->>'equipment_status') as status,
            (rec->>'time')::timestamptz as ts,
            LEAD((rec->>'time')::timestamptz) OVER (
                PARTITION BY batch_id, equipment_id
                ORDER BY (rec->>'time')::timestamptz
            ) as next_ts
        FROM ingest_batches,
        jsonb_array_elements(payload_raw->'statusHistory') as rec
        WHERE dispatched_at BETWEEN $1 AND $2
    ),
    batch_totals AS (
        SELECT
            SUM(CASE WHEN status = 'RUN' AND next_ts IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as run_sec,
            SUM(CASE WHEN next_ts IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as total_sec,
            SUM(CASE WHEN status = 'STOP' AND next_ts IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as stop_sec
        FROM sh
    )
    SELECT
        ROUND(
            100.0 * run_sec / NULLIF(total_sec, 0),
            2
        ) as avg_availability_pct,
        stop_sec / 60.0 as total_downtime_min
    FROM batch_totals
    """
    avail_row = await conn.fetchrow(avail_query, start_time, end_time)

    # 6. MTBF from alarmHistory (avg interval between alarms per equipment)
    mtbf_query = """
    WITH ah AS (
        SELECT
            equipment_id,
            (rec->>'time')::timestamptz as alarm_ts,
            LEAD((rec->>'time')::timestamptz) OVER (
                PARTITION BY equipment_id
                ORDER BY (rec->>'time')::timestamptz
            ) as next_alarm_ts
        FROM ingest_batches,
        jsonb_array_elements(payload_raw->'alarmHistory') as rec
        WHERE dispatched_at BETWEEN $1 AND $2
    )
    SELECT AVG(EXTRACT(EPOCH FROM (next_alarm_ts - alarm_ts)) / 3600.0) as avg_mtbf_hours
    FROM ah
    WHERE next_alarm_ts IS NOT NULL
    """
    mtbf_row = await conn.fetchrow(mtbf_query, start_time, end_time)

    # 7. Alarm count per equipment
    alarm_query = """
    SELECT
        equipment_id,
        COUNT(rec) as alarm_count
    FROM ingest_batches,
    jsonb_array_elements(payload_raw->'alarmHistory') as rec
    WHERE dispatched_at BETWEEN $1 AND $2
    GROUP BY equipment_id
    """
    alarm_rows = await conn.fetch(alarm_query, start_time, end_time)
    alarm_by_equip = {r['equipment_id']: r['alarm_count'] for r in alarm_rows}

    return ReportMetrics(
        totalLots=prod_row['total_lots'] or 0,
        avgYieldPct=prod_row['avg_yield'] or 0.0,
        minYieldPct=prod_row['min_yield'] or 0.0,
        maxYieldPct=prod_row['max_yield'] or 0.0,
        totalFailCount=prod_row['total_fail'] or 0,
        avgUph=prod_row['avg_uph'] or 0.0,
        topFailReasons=[],
        recipeBreakdown=[
            RecipeMetric(
                recipe_id=r['recipe_id'],
                avgYieldPct=r['avg_yield'] or 0.0,
                totalLots=r['total_lots']
            ) for r in recipe_rows if r['recipe_id']
        ],
        judgmentDistribution=judgment_dist,
        marginalCount=marginal_row['cnt'] or 0,
        avgAvailabilityPct=float(avail_row['avg_availability_pct'] or 0.0),
        totalDowntimeMin=float(avail_row['total_downtime_min'] or 0.0),
        avgMtbfHours=float(mtbf_row['avg_mtbf_hours']) if mtbf_row['avg_mtbf_hours'] else None,
        equipmentBreakdown=[
            EquipmentMetric(
                equipmentId=e['equipment_id'],
                avgYieldPct=e['avg_yield'] or 0.0,
                avgUph=e['avg_uph'] or 0.0,
                alarmCount=alarm_by_equip.get(e['equipment_id'], 0)
            ) for e in equip_rows if e['equipment_id']
        ]
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
