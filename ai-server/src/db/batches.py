from datetime import datetime
from typing import Dict, Any, Optional, List
import asyncpg
import structlog
import json
from src.config import settings
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
    query = """
    SELECT batch_id, lot_hash, equipment_hash, equipment_id, total_records, 
           records_summary, dispatched_at, ingested_at, pushed_to_backend 
    FROM ingest_batches 
    WHERE batch_id = $1
    """
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
        where_clauses.append(
            f"(equipment_id = ${len(params)} OR equipment_hash = ${len(params)} "
            f"OR COALESCE(equipment_id, equipment_hash) = ${len(params)})"
        )
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

async def get_latest_batch_full(conn: asyncpg.Connection, equipment_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Returns the full payload_raw (parsed DispatchBatch) of the most recent batch.
    If equipment_id is given, scopes to that equipment. None if no batch exists.
    This dict maps directly to Spring's BatchDetailResponse.batch.
    """
    query = """
    SELECT payload_raw
    FROM ingest_batches
    WHERE (
        $1::text IS NULL
        OR equipment_id = $1
        OR equipment_hash = $1
        OR COALESCE(equipment_id, equipment_hash) = $1
    )
    ORDER BY dispatched_at DESC
    LIMIT 1
    """
    row = await conn.fetchrow(query, equipment_id)
    if not row or row["payload_raw"] is None:
        return None
    payload = row["payload_raw"]
    # payload_raw is JSONB; asyncpg may return it as str depending on codec config.
    return json.loads(payload) if isinstance(payload, str) else dict(payload)

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

    # equipment_status_log(가동률·현재 가동 소스)용 별도 WHERE 절. 같은 params 인덱스를 공유한다.
    # - period: ts 가 [from, to] 안 (가동률/비가동 구간 집계용)
    # - latest: ts <= to (현재 상태 판정용, 하한 없음 — 종일 무변화 장비도 마지막 상태 유지)
    status_eq = None
    status_from = None
    status_to = None

    if equipment_id:
        params.append(equipment_id)
        where_clauses.append(
            f"(equipment_id = ${len(params)} OR equipment_hash = ${len(params)} "
            f"OR COALESCE(equipment_id, equipment_hash) = ${len(params)})"
        )
        status_eq = (
            f"(equipment_id = ${len(params)} OR equipment_hash = ${len(params)} "
            f"OR equipment_key = ${len(params)})"
        )
    if from_date:
        params.append(from_date)
        where_clauses.append(f"dispatched_at >= ${len(params)}")
        status_from = f"ts >= ${len(params)}"
    if to_date:
        params.append(to_date)
        where_clauses.append(f"dispatched_at <= ${len(params)}")
        status_to = f"ts <= ${len(params)}"

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    def _status_where(parts):
        parts = [p for p in parts if p]
        return (" WHERE " + " AND ".join(parts)) if parts else ""

    status_period_where = _status_where([status_eq, status_from, status_to])
    status_latest_where = _status_where([status_eq, status_to])

    # Deduplicate batches by lot_hash, keeping only the latest dispatched batch
    # per LOT. A LOT can be re-dispatched with a new batch_id (e.g. dispatcher
    # restart / lost sent_lots.jsonl), which would otherwise double-count
    # production. All lot/record-level aggregations read from this CTE.
    deduped_cte = f"""
    deduped AS (
        SELECT DISTINCT ON (lot_hash) *
        FROM ingest_batches
        {where_sql}
        ORDER BY lot_hash, dispatched_at DESC
    )
    """

    # 1. Production & Yield (inspection_results 기준)
    # 생산량 = 검사 결과 행 수, 수율 = PASS / 전체 검사 행 (units-weighted).
    # UPH/LOT 수는 LOT summary 기준으로 deduped batch 위에서 계산.
    base_query = f"""
    WITH {deduped_cte},
    recs AS (
        SELECT
            COUNT(*) FILTER (WHERE (rec->>'overall_result') IS NOT NULL) AS total_inspected,
            COUNT(*) FILTER (WHERE (rec->>'overall_result') = 'PASS') AS pass_count,
            COUNT(*) FILTER (WHERE (rec->>'overall_result') = 'FAIL') AS fail_count
        FROM deduped,
        jsonb_array_elements(payload_raw->'records') AS rec
    ),
    lots AS (
        SELECT
            COUNT(*) AS total_lots,
            AVG((payload_raw->'lotSummary'->>'total_units')::float
                / NULLIF((payload_raw->'lotSummary'->>'lot_duration_sec')::float, 0) * 3600) AS avg_uph
        FROM deduped
    )
    SELECT
        lots.total_lots,
        recs.total_inspected,
        recs.pass_count,
        recs.fail_count,
        CASE WHEN recs.total_inspected > 0
             THEN ROUND(100.0 * recs.pass_count / recs.total_inspected, 2)
             ELSE NULL END AS yield_pct,
        lots.avg_uph
    FROM recs, lots
    """
    base_row = await conn.fetchrow(base_query, *params)

    # 2. Oracle Judgments
    oracle_query = f"""
    WITH {deduped_cte}
    SELECT
        COUNT(*) FILTER (WHERE payload_raw->'oracleAnalysis'->0->>'judgment' = 'DANGER') as danger_count,
        COUNT(*) FILTER (WHERE payload_raw->'oracleAnalysis'->0->>'judgment' = 'WARNING') as warning_count,
        COUNT(*) FILTER (WHERE
            payload_raw->'oracleAnalysis'->0->'violated_rules'->>'yield_grade' = 'MARGINAL'
            OR payload_raw->'oracleAnalysis'->0->>'judgment' = 'WARNING'
        ) as marginal_count
    FROM deduped
    """
    oracle_row = await conn.fetchrow(oracle_query, *params)

    # 3. Active Equipment (latest status per equipment).
    # equipment_status_log(LOT와 무관한 실시간 상태 로그) 기준으로, LOT를 완료하지 않은
    # 장비(IDLE/STOP/진행중)도 포함해 현재 상태를 판정한다.
    # Total equipment is the configured equipment master (denominator of 가동 N/M).
    equip_query = f"""
    WITH latest_status AS (
        SELECT DISTINCT ON (equipment_key)
            equipment_key,
            status as last_status
        FROM equipment_status_log
        {status_latest_where}
        ORDER BY equipment_key, ts DESC
    )
    SELECT
        COUNT(*) as observed_equip_count,
        COUNT(*) FILTER (WHERE last_status = 'RUN') as active_equip_count
    FROM latest_status
    """
    equip_row = await conn.fetchrow(equip_query, *params)

    # 4. Availability & Downtime (Detailed aggregation)
    # equipment_status_log 기준. 장비별로 ts 순서대로 LEAD를 잡아 RUN/IDLE/STOP 구간 시간을
    # 합산한다(배치 경계 없이 장비 단위로 연속 계산하므로 누락/중복 없음).
    avail_query = f"""
    WITH sh AS (
        SELECT
            equipment_key,
            status,
            ts,
            LEAD(ts) OVER (
                PARTITION BY equipment_key
                ORDER BY ts
            ) as next_ts
        FROM equipment_status_log
        {status_period_where}
    ),
    totals AS (
        SELECT
            SUM(CASE WHEN status = 'RUN' AND next_ts IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as run_sec,
            SUM(CASE WHEN status = 'IDLE' AND next_ts IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as idle_sec,
            SUM(CASE WHEN next_ts IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as total_sec,
            SUM(CASE WHEN status = 'STOP' AND next_ts IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as stop_sec
        FROM sh
    )
    SELECT
        ROUND(100.0 * run_sec / NULLIF(total_sec, 0), 2) as avg_availability_pct,
        ROUND(100.0 * idle_sec / NULLIF(total_sec, 0), 2) as avg_idle_pct,
        stop_sec / 60.0 as total_downtime_min
    FROM totals
    """
    avail_row = await conn.fetchrow(avail_query, *params)

    # 5. Top Failure Reasons (inspection_results.fail_reason_code 원천값)
    fail_query = f"""
    WITH {deduped_cte}
    SELECT
        (rec->>'fail_reason_code') as reason_code,
        COUNT(*) as count
    FROM deduped,
    jsonb_array_elements(payload_raw->'records') as rec
    WHERE (rec->>'fail_reason_code') IS NOT NULL
      AND (rec->>'fail_reason_code') != 'null'
    GROUP BY reason_code
    ORDER BY count DESC
    LIMIT 5
    """
    fail_rows = await conn.fetch(fail_query, *params)

    # 6. Equipment Details (inspection_results 기준, consistent with headline)
    equip_detail_query = f"""
    WITH {deduped_cte},
    latest AS (
        SELECT DISTINCT ON (COALESCE(equipment_id, equipment_hash))
            COALESCE(equipment_id, equipment_hash) AS equipment_key,
            equipment_hash,
            payload_raw->'statusHistory'->-1->>'equipment_status' as status
        FROM ingest_batches
        {where_sql}
        ORDER BY COALESCE(equipment_id, equipment_hash), dispatched_at DESC
    ),
    uph AS (
        SELECT
            COALESCE(equipment_id, equipment_hash) AS equipment_key,
            AVG((payload_raw->'lotSummary'->>'total_units')::float /
                NULLIF((payload_raw->'lotSummary'->>'lot_duration_sec')::float, 0) * 3600) as avg_uph
        FROM deduped
        GROUP BY COALESCE(equipment_id, equipment_hash)
    ),
    agg AS (
        SELECT
            COALESCE(d.equipment_id, d.equipment_hash) AS equipment_key,
            MIN(d.equipment_hash) as equipment_hash,
            COUNT(*) FILTER (WHERE (rec->>'overall_result') IS NOT NULL) as total_units,
            COUNT(*) FILTER (WHERE (rec->>'overall_result') = 'PASS') as pass_count
        FROM deduped d,
        jsonb_array_elements(d.payload_raw->'records') as rec
        GROUP BY COALESCE(d.equipment_id, d.equipment_hash)
    )
    SELECT
        a.equipment_key,
        COALESCE(l.equipment_hash, a.equipment_hash) AS equipment_hash,
        CASE WHEN a.total_units > 0
             THEN ROUND(100.0 * a.pass_count / a.total_units, 2)
             ELSE 0 END AS avg_yield,
        a.total_units,
        COALESCE(u.avg_uph, 0) AS avg_uph,
        COALESCE(l.status, 'UNKNOWN') as status
    FROM agg a
    LEFT JOIN latest l USING (equipment_key)
    LEFT JOIN uph u USING (equipment_key)
    """
    equip_detail_rows = await conn.fetch(equip_detail_query, *params)

    # 7. MTBF Calculation
    mtbf_query = f"""
    WITH {deduped_cte},
    alarm_times AS (
        SELECT
            COALESCE(equipment_id, equipment_hash) AS equipment_key,
            (rec->>'time')::timestamptz as alarm_ts,
            LEAD((rec->>'time')::timestamptz) OVER (
                PARTITION BY COALESCE(equipment_id, equipment_hash)
                ORDER BY (rec->>'time')::timestamptz
            ) as next_alarm_ts
        FROM deduped,
        jsonb_array_elements(payload_raw->'alarmHistory') as rec
    )
    SELECT AVG(EXTRACT(EPOCH FROM (next_alarm_ts - alarm_ts)) / 3600.0) as avg_mtbf_hours
    FROM alarm_times
    WHERE next_alarm_ts IS NOT NULL
    """
    mtbf_row = await conn.fetchrow(mtbf_query, *params)

    # Total equipment count: when filtering a single equipment, the denominator
    # is that one equipment; otherwise it is the configured equipment master.
    observed_equip = equip_row["observed_equip_count"] or 0
    if equipment_id:
        total_equip_count = observed_equip
    else:
        master = settings.equipment_master_list
        total_equip_count = len(master) if master else observed_equip

    return {
        "totalUnits": base_row["total_inspected"] or 0,
        "totalInspected": base_row["total_inspected"] or 0,
        "totalFail": base_row["fail_count"] or 0,
        "avgYieldPct": float(base_row["yield_pct"]) if base_row["yield_pct"] is not None else 0.0,
        "avgUph": base_row["avg_uph"] or 0.0,
        "marginalCount": oracle_row["marginal_count"] or 0,
        "dangerCount": oracle_row["danger_count"] or 0,
        "warningCount": oracle_row["warning_count"] or 0,
        "activeEquipmentCount": equip_row["active_equip_count"] or 0,
        "totalEquipmentCount": total_equip_count,
        "avgAvailabilityPct": float(avail_row["avg_availability_pct"] or 0.0),
        "avgIdlePct": float(avail_row["avg_idle_pct"] or 0.0),
        "totalDowntimeMin": float(avail_row["total_downtime_min"] or 0.0),
        "avgMtbfHours": float(mtbf_row["avg_mtbf_hours"]) if mtbf_row and mtbf_row["avg_mtbf_hours"] else None,
        "topFailReasons": [{"reason_code": r["reason_code"], "count": r["count"]} for r in fail_rows],
        "equipmentDetails": [
            {
                "equipmentId": r["equipment_key"],
                "equipmentHash": r["equipment_hash"],
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
        query += " WHERE (equipment_id = $1 OR equipment_hash = $1 OR COALESCE(equipment_id, equipment_hash) = $1)"

    params.append(limit)
    query += f" ORDER BY dispatched_at DESC LIMIT ${len(params)}"
    return await conn.fetch(query, *params)
