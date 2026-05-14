from datetime import datetime
from typing import Dict, Any, Optional, List
import asyncpg
import structlog
import json
from src.models.dispatch_batch import DispatchBatch

logger = structlog.get_logger()

async def save_ingest_batch(conn: asyncpg.Connection, batch: DispatchBatch, records_summary: Dict[str, Any]):
    """
    Saves the full DispatchBatch as payload_raw and calculated records_summary.
    """
    query = """
    INSERT INTO ingest_batches (
        batch_id, lot_hash, equipment_hash, equipment_id, total_records,
        payload_raw, records_summary, dispatched_at
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """
    
    await conn.execute(
        query,
        batch.batchId,
        batch.lotHash,
        batch.equipmentHash,
        batch.equipmentId,
        batch.totalRecords,
        batch.model_dump_json(),  # Full raw payload
        json.dumps(records_summary),  # KPI fast-path summary
        batch.dispatchedAt
    )

async def check_batch_id_exists(conn: asyncpg.Connection, batch_id: str) -> Optional[Dict[str, Any]]:
    query = "SELECT lot_hash, equipment_hash FROM ingest_batches WHERE batch_id = $1"
    row = await conn.fetchrow(query, batch_id)
    return dict(row) if row else None

async def get_batch_by_id(conn: asyncpg.Connection, batch_id: str) -> Optional[Dict[str, Any]]:
    query = "SELECT * FROM ingest_batches WHERE batch_id = $1"
    row = await conn.fetchrow(query, batch_id)
    return dict(row) if row else None

async def list_batches(
    conn: asyncpg.Connection, 
    equipment_id: Optional[str] = None, 
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    query = "SELECT batch_id, lot_hash, equipment_hash, equipment_id, total_records, dispatched_at, ingested_at FROM ingest_batches"
    where_clauses = []
    params = []
    
    if equipment_id:
        params.append(equipment_id)
        where_clauses.append(f"equipment_id = ${len(params)}")
    if from_date:
        params.append(from_date)
        where_clauses.append(f"dispatched_at >= ${len(params)}")
    if to_date:
        params.append(to_date)
        where_clauses.append(f"dispatched_at <= ${len(params)}")
        
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
        
    query += f" ORDER BY dispatched_at DESC LIMIT ${len(params)+1} OFFSET ${len(params)+2}"
    params.extend([limit, offset])
    
    rows = await conn.fetch(query, *params)
    return [dict(row) for row in rows]

async def get_latest_batches_per_equipment(conn: asyncpg.Connection) -> List[Dict[str, Any]]:
    query = """
    SELECT DISTINCT ON (equipment_id) 
        batch_id, lot_hash, equipment_id, dispatched_at, 
        payload_raw->'lotSummary'->>'lot_status' as lot_status,
        (payload_raw->'lotSummary'->>'yield_pct')::float as yield_pct
    FROM ingest_batches
    ORDER BY equipment_id, dispatched_at DESC
    """
    rows = await conn.fetch(query)
    return [dict(row) for row in rows]

async def aggregate_kpi_summary(
    conn: asyncpg.Connection,
    equipment_id: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Aggregates KPIs from ingest_batches using PostgreSQL JSONB extraction.
    """
    where_clauses = []
    params = []
    
    if equipment_id:
        params.append(equipment_id)
        where_clauses.append(f"equipment_id = ${len(params)}")
    if from_date:
        params.append(from_date)
        where_clauses.append(f"dispatched_at >= ${len(params)}")
    if to_date:
        params.append(to_date)
        where_clauses.append(f"dispatched_at <= ${len(params)}")
        
    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    
    # 1. Base Aggregations (Production & Basic Stats)
    # Fallback yield: yield_actual (oracle) -> actual (yield_status) -> yield_pct (lotSummary)
    base_query = f"""
    SELECT 
        COUNT(*) as total_lots,
        SUM((payload_raw->'lotSummary'->>'total_units')::int) as total_units,
        SUM((payload_raw->'lotSummary'->>'fail_count')::int) as total_fail,
        AVG(COALESCE(
            (payload_raw->'oracleAnalysis'->0->>'yield_actual')::float,
            (payload_raw->'oracleAnalysis'->0->'yield_status'->>'actual')::float,
            (payload_raw->'lotSummary'->>'yield_pct')::float
        )) as avg_yield_pct,
        AVG((payload_raw->'lotSummary'->>'total_units')::float / NULLIF((payload_raw->'lotSummary'->>'lot_duration_sec')::float, 0) * 3600) as avg_uph
    FROM ingest_batches
    {where_sql}
    """
    base_row = await conn.fetchrow(base_query, *params)
    
    # 2. Oracle Judgments
    oracle_query = f"""
    SELECT 
        COUNT(*) FILTER (WHERE payload_raw->'oracleAnalysis'->0->>'judgment' = 'DANGER') as danger_count,
        COUNT(*) FILTER (WHERE payload_raw->'oracleAnalysis'->0->>'judgment' = 'WARNING') as warning_count,
        COUNT(*) FILTER (WHERE 
            payload_raw->'oracleAnalysis'->0->'violated_rules'->>'yield_grade' = 'MARGINAL' 
            OR payload_raw->'oracleAnalysis'->0->>'judgment' = 'WARNING'
        ) as marginal_count
    FROM ingest_batches
    {where_sql}
    """
    oracle_row = await conn.fetchrow(oracle_query, *params)
    
    # 3. Availability & Active Equipment
    # Note: Simplified for A3. In real usage, we'd look at the latest batch's status history
    equip_query = f"""
    WITH latest_status AS (
        SELECT DISTINCT ON (equipment_id) 
            equipment_id,
            payload_raw->'statusHistory'->-1->>'equipment_status' as last_status
        FROM ingest_batches
        {where_sql}
        ORDER BY equipment_id, dispatched_at DESC
    )
    SELECT 
        COUNT(*) as total_equip_count,
        COUNT(*) FILTER (WHERE last_status = 'RUN') as active_equip_count
    FROM latest_status
    """
    equip_row = await conn.fetchrow(equip_query, *params)

    # 4. Availability & Downtime (Detailed aggregation)
    avail_query = f"""
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
        {where_sql}
    ),
    totals AS (
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
        ROUND(100.0 * run_sec / NULLIF(total_sec, 0), 2) as avg_availability_pct,
        stop_sec / 60.0 as total_downtime_min
    FROM totals
    """
    avail_row = await conn.fetchrow(avail_query, *params)

    # 5. Top Failure Reasons
    fail_where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""
    fail_query = f"""
    SELECT
        (rec->>'fail_reason_code') as reason_code,
        COUNT(*) as count
    FROM ingest_batches,
    jsonb_array_elements(payload_raw->'records') as rec
    WHERE (rec->>'fail_reason_code') IS NOT NULL
      AND (rec->>'fail_reason_code') != 'null'
    {fail_where_sql}
    GROUP BY reason_code
    ORDER BY count DESC
    LIMIT 5
    """
    fail_rows = await conn.fetch(fail_query, *params)

    # 6. Equipment Details
    equip_detail_query = f"""
    WITH latest AS (
        SELECT DISTINCT ON (equipment_id)
            equipment_id,
            payload_raw->'statusHistory'->-1->>'equipment_status' as status
        FROM ingest_batches
        {where_sql}
        ORDER BY equipment_id, dispatched_at DESC
    ),
    agg AS (
        SELECT
            equipment_id,
            AVG((payload_raw->'lotSummary'->>'yield_pct')::float) as avg_yield,
            SUM((payload_raw->'lotSummary'->>'total_units')::int) as total_units,
            AVG((payload_raw->'lotSummary'->>'total_units')::float /
                NULLIF((payload_raw->'lotSummary'->>'lot_duration_sec')::float, 0) * 3600) as avg_uph
        FROM ingest_batches
        {where_sql}
        GROUP BY equipment_id
    )
    SELECT a.equipment_id, a.avg_yield, a.total_units, a.avg_uph, COALESCE(l.status, 'UNKNOWN') as status
    FROM agg a LEFT JOIN latest l USING (equipment_id)
    """
    equip_detail_rows = await conn.fetch(equip_detail_query, *params)
    
    # 7. MTBF Calculation
    mtbf_query = f"""
    WITH alarm_times AS (
        SELECT
            equipment_id,
            (rec->>'time')::timestamptz as alarm_ts,
            LEAD((rec->>'time')::timestamptz) OVER (
                PARTITION BY equipment_id
                ORDER BY (rec->>'time')::timestamptz
            ) as next_alarm_ts
        FROM ingest_batches,
        jsonb_array_elements(payload_raw->'alarmHistory') as rec
        {where_sql}
    )
    SELECT AVG(EXTRACT(EPOCH FROM (next_alarm_ts - alarm_ts)) / 3600.0) as avg_mtbf_hours
    FROM alarm_times
    WHERE next_alarm_ts IS NOT NULL
    """
    mtbf_row = await conn.fetchrow(mtbf_query, *params)
    
    return {
        "totalUnits": base_row["total_units"] or 0,
        "totalInspected": base_row["total_units"] or 0,
        "totalFail": base_row["total_fail"] or 0,
        "avgYieldPct": base_row["avg_yield_pct"] or 0.0,
        "avgUph": base_row["avg_uph"] or 0.0,
        "marginalCount": oracle_row["marginal_count"] or 0,
        "dangerCount": oracle_row["danger_count"] or 0,
        "warningCount": oracle_row["warning_count"] or 0,
        "activeEquipmentCount": equip_row["active_equip_count"] or 0,
        "totalEquipmentCount": equip_row["total_equip_count"] or 0,
        "avgAvailabilityPct": float(avail_row["avg_availability_pct"] or 0.0),
        "totalDowntimeMin": float(avail_row["total_downtime_min"] or 0.0),
        "avgMtbfHours": float(mtbf_row["avg_mtbf_hours"]) if mtbf_row and mtbf_row["avg_mtbf_hours"] else None,
        "topFailReasons": [{"reason_code": r["reason_code"], "count": r["count"]} for r in fail_rows],
        "equipmentDetails": [
            {
                "equipmentId": r["equipment_id"],
                "avgYieldPct": r["avg_yield"] or 0.0,
                "totalUnits": r["total_units"] or 0,
                "avgUph": r["avg_uph"] or 0.0,
                "status": r["status"]
            } for r in equip_detail_rows
        ],
    }

async def get_latest_batches(
    conn: asyncpg.Connection,
    equipment_id: Optional[str] = None,
    limit: int = 50,
):
    query = """
    SELECT batch_id, lot_hash, equipment_hash, equipment_id, total_records,
           records_summary, dispatched_at, ingested_at
    FROM ingest_batches
    """
    params = []
    if equipment_id:
        params.append(equipment_id)
        query += " WHERE equipment_id = $1"

    params.append(limit)
    query += f" ORDER BY dispatched_at DESC LIMIT ${len(params)}"
    return await conn.fetch(query, *params)
