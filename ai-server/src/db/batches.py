from datetime import datetime, timedelta
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
    SELECT payload_raw
    FROM ingest_batches 
    WHERE batch_id = $1
    """
    row = await conn.fetchrow(query, batch_id)
    if not row or row["payload_raw"] is None:
        return None
    payload = row["payload_raw"]
    return json.loads(payload) if isinstance(payload, str) else dict(payload)


def _batch_where(
    equipment_id: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> tuple[str, list[Any]]:
    where_clauses = []
    params: list[Any] = []

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

    return (" WHERE " + " AND ".join(where_clauses)) if where_clauses else "", params


def _to_batch_list_item(row: Dict[str, Any]) -> Dict[str, Any]:
    lot_hash = row.get("lot_hash")
    return {
        "batchId": str(row.get("batch_id")) if row.get("batch_id") is not None else None,
        "equipmentId": row.get("equipment_id"),
        "equipmentHash": row.get("equipment_hash"),
        "lotHashShort": lot_hash[:8] if lot_hash else None,
        "recipeId": row.get("recipe_id"),
        "lotStatus": row.get("lot_status"),
        "dispatchedAt": row.get("dispatched_at"),
        "lotEndAt": row.get("lot_end_at"),
        "yieldPct": float(row["yield_pct"]) if row.get("yield_pct") is not None else None,
        "totalUnits": row.get("total_units"),
        "failCount": row.get("fail_count"),
        "judgment": row.get("judgment"),
        "severityCode": row.get("severity_code"),
        "alarmCount": row.get("alarm_count") or 0,
        "availabilityPct": float(row["availability_pct"]) if row.get("availability_pct") is not None else None,
    }


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _status_where(
    equipment_id: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    if equipment_id:
        params.append(equipment_id)
        clauses.append(
            f"(equipment_id = ${len(params)}::text OR equipment_hash = ${len(params)}::text "
            f"OR equipment_key = ${len(params)}::text)"
        )
    if from_date:
        params.append(from_date)
        clauses.append(f"ts >= ${len(params)}::timestamptz")
    if to_date:
        params.append(to_date)
        clauses.append(f"ts <= ${len(params)}::timestamptz")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


async def _status_metrics_by_equipment(
    conn: asyncpg.Connection,
    equipment_id: Optional[str],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
) -> Dict[str, Dict[str, Any]]:
    where_sql, params = _status_where(equipment_id, from_date, to_date)
    query = f"""
    WITH sh AS (
        SELECT
            equipment_key,
            status,
            ts,
            LEAD(ts) OVER (PARTITION BY equipment_key ORDER BY ts) as next_ts
        FROM equipment_status_log
        {where_sql}
    ),
    totals AS (
        SELECT
            equipment_key,
            SUM(CASE WHEN status = 'RUN' AND next_ts IS NOT NULL THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as run_sec,
            SUM(CASE WHEN status = 'STOP' AND next_ts IS NOT NULL THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as stop_sec,
            SUM(CASE WHEN next_ts IS NOT NULL THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as total_sec
        FROM sh
        GROUP BY equipment_key
    )
    SELECT
        equipment_key,
        ROUND(100.0 * run_sec / NULLIF(total_sec, 0), 2) as availability_pct,
        stop_sec / 60.0 as downtime_min
    FROM totals
    """
    rows = await conn.fetch(query, *params)
    return {
        r["equipment_key"]: {
            "availabilityPct": float(r["availability_pct"] or 0.0),
            "downtimeMin": float(r["downtime_min"] or 0.0),
        }
        for r in rows
    }


async def _status_metrics_by_time_group(
    conn: asyncpg.Connection,
    group_by: str,
    equipment_id: Optional[str],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
) -> Dict[str, Dict[str, Any]]:
    where_sql, params = _status_where(equipment_id, from_date, to_date)
    bucket_expr = "date_trunc('day', ts)" if group_by == "day" else "date_trunc('week', ts)"
    query = f"""
    WITH sh AS (
        SELECT
            status,
            ts,
            {bucket_expr} as bucket,
            LEAD(ts) OVER (PARTITION BY equipment_key ORDER BY ts) as next_ts
        FROM equipment_status_log
        {where_sql}
    ),
    totals AS (
        SELECT
            bucket,
            SUM(CASE WHEN status = 'RUN' AND next_ts IS NOT NULL THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as run_sec,
            SUM(CASE WHEN status = 'STOP' AND next_ts IS NOT NULL THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as stop_sec,
            SUM(CASE WHEN next_ts IS NOT NULL THEN EXTRACT(EPOCH FROM (next_ts - ts)) ELSE 0 END) as total_sec
        FROM sh
        GROUP BY bucket
    )
    SELECT
        bucket,
        ROUND(100.0 * run_sec / NULLIF(total_sec, 0), 2) as availability_pct,
        stop_sec / 60.0 as downtime_min
    FROM totals
    """
    rows = await conn.fetch(query, *params)
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        bucket = r["bucket"]
        key = bucket.strftime("%Y-%m-%d") if group_by == "day" else f"{bucket.isocalendar().year}-W{bucket.isocalendar().week:02d}"
        out[key] = {
            "avgAvailabilityPct": float(r["availability_pct"] or 0.0),
            "totalDowntimeMin": float(r["downtime_min"] or 0.0),
        }
    return out


async def _mtbf_by_equipment(
    conn: asyncpg.Connection,
    where_sql: str,
    params: list[Any],
) -> Dict[str, Optional[float]]:
    query = f"""
    WITH deduped AS (
        SELECT DISTINCT ON (lot_hash) *
        FROM ingest_batches
        {where_sql}
        ORDER BY lot_hash, dispatched_at DESC
    ),
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
    SELECT
        equipment_key,
        AVG(EXTRACT(EPOCH FROM (next_alarm_ts - alarm_ts)) / 3600.0) as mtbf_hours
    FROM alarm_times
    WHERE next_alarm_ts IS NOT NULL
    GROUP BY equipment_key
    """
    rows = await conn.fetch(query, *params)
    return {
        r["equipment_key"]: float(r["mtbf_hours"]) if r["mtbf_hours"] is not None else None
        for r in rows
    }


async def _mtbf_by_time_group(
    conn: asyncpg.Connection,
    group_by: str,
    where_sql: str,
    params: list[Any],
) -> Dict[str, Optional[float]]:
    bucket_expr = "date_trunc('day', alarm_ts)" if group_by == "day" else "date_trunc('week', alarm_ts)"
    query = f"""
    WITH deduped AS (
        SELECT DISTINCT ON (lot_hash) *
        FROM ingest_batches
        {where_sql}
        ORDER BY lot_hash, dispatched_at DESC
    ),
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
    SELECT
        {bucket_expr} as bucket,
        AVG(EXTRACT(EPOCH FROM (next_alarm_ts - alarm_ts)) / 3600.0) as mtbf_hours
    FROM alarm_times
    WHERE next_alarm_ts IS NOT NULL
    GROUP BY bucket
    """
    rows = await conn.fetch(query, *params)
    out: Dict[str, Optional[float]] = {}
    for r in rows:
        bucket = r["bucket"]
        key = bucket.strftime("%Y-%m-%d") if group_by == "day" else f"{bucket.isocalendar().year}-W{bucket.isocalendar().week:02d}"
        out[key] = float(r["mtbf_hours"]) if r["mtbf_hours"] is not None else None
    return out

async def list_batches(
    conn: asyncpg.Connection, 
    equipment_id: Optional[str] = None, 
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    where_sql, params = _batch_where(equipment_id, from_date, to_date)
    query = f"""
    SELECT
        batch_id,
        lot_hash,
        equipment_hash,
        equipment_id,
        dispatched_at,
        payload_raw->'lotSummary'->>'recipeId' as recipe_id_camel,
        payload_raw->'lotSummary'->>'recipe_id' as recipe_id_snake,
        COALESCE(
            payload_raw->'lotSummary'->>'recipeId',
            payload_raw->'lotSummary'->>'recipe_id',
            payload_raw->'lotSummary'->>'recipeHash'
        ) as recipe_id,
        COALESCE(payload_raw->'lotSummary'->>'lotStatus', payload_raw->'lotSummary'->>'lot_status') as lot_status,
        COALESCE(payload_raw->'lotSummary'->>'lotEndAt', payload_raw->'lotSummary'->>'lot_end_at')::timestamptz as lot_end_at,
        COALESCE(payload_raw->'lotSummary'->>'yieldPct', payload_raw->'lotSummary'->>'yield_pct')::float as yield_pct,
        COALESCE(payload_raw->'lotSummary'->>'totalUnits', payload_raw->'lotSummary'->>'total_units')::int as total_units,
        COALESCE(payload_raw->'lotSummary'->>'failCount', payload_raw->'lotSummary'->>'fail_count')::int as fail_count,
        payload_raw->'oracleAnalysis'->0->>'judgment' as judgment,
        CASE payload_raw->'oracleAnalysis'->0->>'judgment'
            WHEN 'DANGER' THEN 3
            WHEN 'WARNING' THEN 2
            ELSE 1
        END as severity_code,
        COALESCE(jsonb_array_length(payload_raw->'alarmHistory'), 0) as alarm_count,
        NULL::float as availability_pct
    FROM ingest_batches
    {where_sql}
    """
    query += f" ORDER BY dispatched_at DESC LIMIT ${len(params)+1} OFFSET ${len(params)+2}"
    params.extend([limit, offset])
    
    rows = await conn.fetch(query, *params)
    return [_to_batch_list_item(dict(row)) for row in rows]


async def count_batches(
    conn: asyncpg.Connection,
    equipment_id: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> int:
    where_sql, params = _batch_where(equipment_id, from_date, to_date)
    row = await conn.fetchrow(f"SELECT COUNT(*) as count FROM ingest_batches{where_sql}", *params)
    return int(row["count"] or 0)

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
    batch_params = []

    # equipment_status_log(가동률·현재 가동 소스)용 별도 WHERE 절.
    # - period: ts 가 [from, to] 안 (가동률/비가동 구간 집계용)
    # - latest: ts <= to (현재 상태 판정용, 하한 없음 — 종일 무변화 장비도 마지막 상태 유지)
    if equipment_id:
        batch_params.append(equipment_id)
        where_clauses.append(
            f"(equipment_id = ${len(batch_params)}::text OR equipment_hash = ${len(batch_params)}::text "
            f"OR COALESCE(equipment_id, equipment_hash) = ${len(batch_params)}::text)"
        )
    if from_date:
        batch_params.append(from_date)
        where_clauses.append(f"dispatched_at >= ${len(batch_params)}::timestamptz")
    if to_date:
        batch_params.append(to_date)
        where_clauses.append(f"dispatched_at <= ${len(batch_params)}::timestamptz")

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    def _build_status_where(include_from: bool):
        status_clauses = []
        status_params = []

        if equipment_id:
            status_params.append(equipment_id)
            status_clauses.append(
                f"(equipment_id = ${len(status_params)}::text OR equipment_hash = ${len(status_params)}::text "
                f"OR equipment_key = ${len(status_params)}::text)"
            )
        if include_from and from_date:
            status_params.append(from_date)
            status_clauses.append(f"ts >= ${len(status_params)}::timestamptz")
        if to_date:
            status_params.append(to_date)
            status_clauses.append(f"ts <= ${len(status_params)}::timestamptz")

        status_sql = (" WHERE " + " AND ".join(status_clauses)) if status_clauses else ""
        return status_sql, status_params

    status_period_where, status_period_params = _build_status_where(include_from=True)
    status_latest_where, status_latest_params = _build_status_where(include_from=False)

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
    base_row = await conn.fetchrow(base_query, *batch_params)

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
    oracle_row = await conn.fetchrow(oracle_query, *batch_params)

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
    equip_row = await conn.fetchrow(equip_query, *status_latest_params)

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
    avail_row = await conn.fetchrow(avail_query, *status_period_params)

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
    fail_rows = await conn.fetch(fail_query, *batch_params)

    # 6. Equipment Details.
    # 장비 목록은 LOT 완료 여부와 무관하게 equipment_status_log(상태 피드)의 모든 장비를
    # 기준으로 채운다. LOT를 완료하지 않은 장비(IDLE/STOP/진행중)도 드롭다운/상세 목록에
    # 나타나며, 생산/수율/UPH는 LOT batch가 있을 때만 채워지고 없으면 0이 된다.
    # deduped(batch_params)와 status_latest(status log) 두 소스를 함께 쓰므로 파라미터
    # 목록을 이어 붙이고 status 절 인덱스를 batch_params 길이만큼 오프셋한다.
    ed_params = list(batch_params)
    ed_status_clauses = []
    if equipment_id:
        ed_params.append(equipment_id)
        ed_status_clauses.append(
            f"(equipment_id = ${len(ed_params)}::text OR equipment_hash = ${len(ed_params)}::text "
            f"OR equipment_key = ${len(ed_params)}::text)"
        )
    if to_date:
        ed_params.append(to_date)
        ed_status_clauses.append(f"ts <= ${len(ed_params)}::timestamptz")
    ed_status_where = (" WHERE " + " AND ".join(ed_status_clauses)) if ed_status_clauses else ""

    equip_detail_query = f"""
    WITH {deduped_cte},
    status_latest AS (
        SELECT DISTINCT ON (equipment_key)
            equipment_key,
            equipment_hash,
            status
        FROM equipment_status_log
        {ed_status_where}
        ORDER BY equipment_key, ts DESC
    ),
    uph AS (
        SELECT
            COALESCE(equipment_id, equipment_hash) AS equipment_key,
            AVG((payload_raw->'lotSummary'->>'total_units')::float /
                NULLIF((payload_raw->'lotSummary'->>'lot_duration_sec')::float, 0) * 3600) as avg_uph
        FROM deduped
        GROUP BY COALESCE(equipment_id, equipment_hash)
    ),
    yield_trends AS (
        SELECT
            equipment_key,
            array_agg(yield_pct ORDER BY dispatched_at) FILTER (WHERE yield_pct IS NOT NULL) as yield_trend
        FROM (
            SELECT
                COALESCE(equipment_id, equipment_hash) AS equipment_key,
                dispatched_at,
                COALESCE(payload_raw->'lotSummary'->>'yieldPct', payload_raw->'lotSummary'->>'yield_pct')::float as yield_pct
            FROM deduped
        ) t
        GROUP BY equipment_key
    ),
    agg AS (
        SELECT
            COALESCE(d.equipment_id, d.equipment_hash) AS equipment_key,
            MIN(d.equipment_hash) as equipment_hash,
            (array_agg(COALESCE(
                d.payload_raw->'lotSummary'->>'recipeId',
                d.payload_raw->'lotSummary'->>'recipe_id',
                d.payload_raw->'lotSummary'->>'recipeHash'
            ) ORDER BY d.dispatched_at DESC))[1] as recipe_id,
            COUNT(*) FILTER (WHERE (rec->>'overall_result') IS NOT NULL) as total_units,
            COUNT(*) FILTER (WHERE (rec->>'overall_result') = 'FAIL') as total_fail,
            COUNT(*) FILTER (WHERE (rec->>'overall_result') = 'PASS') as pass_count
        FROM deduped d,
        jsonb_array_elements(d.payload_raw->'records') as rec
        GROUP BY COALESCE(d.equipment_id, d.equipment_hash)
    ),
    batch_meta AS (
        SELECT
            COALESCE(equipment_id, equipment_hash) AS equipment_key,
            SUM(COALESCE(jsonb_array_length(payload_raw->'alarmHistory'), 0)) as alarm_count,
            COUNT(*) FILTER (WHERE payload_raw->'oracleAnalysis'->0->>'judgment' = 'WARNING') as marginal_count
        FROM deduped
        GROUP BY COALESCE(equipment_id, equipment_hash)
    )
    SELECT
        COALESCE(s.equipment_key, a.equipment_key) AS equipment_key,
        COALESCE(s.equipment_hash, a.equipment_hash) AS equipment_hash,
        a.recipe_id,
        CASE WHEN COALESCE(a.total_units, 0) > 0
             THEN ROUND(100.0 * a.pass_count / a.total_units, 2)
             ELSE 0 END AS avg_yield,
        COALESCE(a.total_units, 0) AS total_units,
        COALESCE(a.total_fail, 0) AS total_fail,
        COALESCE(u.avg_uph, 0) AS avg_uph,
        COALESCE(y.yield_trend, ARRAY[]::float[]) as yield_trend,
        COALESCE(m.alarm_count, 0) as alarm_count,
        COALESCE(m.marginal_count, 0) as marginal_count,
        COALESCE(s.status, 'UNKNOWN') as status
    FROM status_latest s
    FULL OUTER JOIN agg a ON a.equipment_key = s.equipment_key
    LEFT JOIN uph u ON u.equipment_key = COALESCE(s.equipment_key, a.equipment_key)
    LEFT JOIN yield_trends y ON y.equipment_key = COALESCE(s.equipment_key, a.equipment_key)
    LEFT JOIN batch_meta m ON m.equipment_key = COALESCE(s.equipment_key, a.equipment_key)
    ORDER BY total_units DESC, equipment_key
    """
    equip_detail_rows = await conn.fetch(equip_detail_query, *ed_params)
    equipment_status_metrics = await _status_metrics_by_equipment(conn, equipment_id, from_date, to_date)
    equipment_mtbf = await _mtbf_by_equipment(conn, where_sql, batch_params)

    fail_by_equipment_query = f"""
    WITH {deduped_cte},
    ranked AS (
        SELECT
            COALESCE(equipment_id, equipment_hash) as equipment_key,
            rec->>'fail_reason_code' as reason_code,
            COUNT(*) as count,
            ROW_NUMBER() OVER (
                PARTITION BY COALESCE(equipment_id, equipment_hash)
                ORDER BY COUNT(*) DESC
            ) as rn
        FROM deduped,
        jsonb_array_elements(payload_raw->'records') as rec
        WHERE rec->>'fail_reason_code' IS NOT NULL
          AND rec->>'fail_reason_code' != 'null'
        GROUP BY COALESCE(equipment_id, equipment_hash), rec->>'fail_reason_code'
    )
    SELECT equipment_key, reason_code, count
    FROM ranked
    WHERE rn <= 5
    ORDER BY equipment_key, count DESC
    """
    fail_by_equipment_rows = await conn.fetch(fail_by_equipment_query, *batch_params)
    fail_by_equipment: Dict[str, List[Dict[str, Any]]] = {}
    for r in fail_by_equipment_rows:
        fail_by_equipment.setdefault(r["equipment_key"], []).append({
            "reason_code": r["reason_code"],
            "count": r["count"],
        })

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
    mtbf_row = await conn.fetchrow(mtbf_query, *batch_params)

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
                "recipeId": _row_get(r, "recipe_id"),
                "totalFail": _row_get(r, "total_fail", 0) or 0,
                "yieldPct": r["avg_yield"] or 0.0,
                "avgYieldPct": r["avg_yield"] or 0.0,
                "totalUnits": r["total_units"] or 0,
                "uph": r["avg_uph"] or 0.0,
                "avgUph": r["avg_uph"] or 0.0,
                "availabilityPct": equipment_status_metrics.get(r["equipment_key"], {}).get("availabilityPct", 0.0),
                "avgAvailabilityPct": equipment_status_metrics.get(r["equipment_key"], {}).get("availabilityPct", 0.0),
                "downtimeMin": equipment_status_metrics.get(r["equipment_key"], {}).get("downtimeMin", 0.0),
                "mtbfHours": equipment_mtbf.get(r["equipment_key"]),
                "alarmCount": _row_get(r, "alarm_count", 0) or 0,
                "marginalCount": _row_get(r, "marginal_count", 0) or 0,
                "topFailReasons": fail_by_equipment.get(r["equipment_key"], []),
                "yieldTrend": [float(v) for v in (_row_get(r, "yield_trend", []) or [])],
                "status": r["status"]
            } for r in equip_detail_rows
        ],
    }


def _group_label(group_by: str, key: datetime | str) -> str:
    if group_by == "day" and isinstance(key, datetime):
        return key.strftime("%m-%d")
    if group_by == "week" and isinstance(key, datetime):
        start = key.date()
        end = start + timedelta(days=6)
        return f"{start:%m/%d}-{end:%m/%d}"
    return str(key)


async def aggregate_kpi_groups(
    conn: asyncpg.Connection,
    group_by: Optional[str],
    equipment_id: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    if group_by not in {"day", "week", "equipment"}:
        return []

    where_sql, params = _batch_where(equipment_id, from_date, to_date)
    deduped_cte = f"""
    deduped AS (
        SELECT DISTINCT ON (lot_hash) *
        FROM ingest_batches
        {where_sql}
        ORDER BY lot_hash, dispatched_at DESC
    )
    """

    if group_by in {"day", "week"}:
        status_by_group = await _status_metrics_by_time_group(conn, group_by, equipment_id, from_date, to_date)
        mtbf_by_group = await _mtbf_by_time_group(conn, group_by, where_sql, params)
        bucket_expr = "date_trunc('day', dispatched_at)" if group_by == "day" else "date_trunc('week', dispatched_at)"
        query = f"""
        WITH {deduped_cte},
        recs AS (
            SELECT
                {bucket_expr} as bucket,
                COUNT(*) FILTER (WHERE rec->>'overall_result' IS NOT NULL) as total_units,
                COUNT(*) FILTER (WHERE rec->>'overall_result' = 'FAIL') as total_fail,
                COUNT(*) FILTER (WHERE rec->>'overall_result' = 'PASS') as pass_count
            FROM deduped,
            jsonb_array_elements(payload_raw->'records') as rec
            GROUP BY bucket
        ),
        lots AS (
            SELECT
                {bucket_expr} as bucket,
                AVG((payload_raw->'lotSummary'->>'total_units')::float /
                    NULLIF((payload_raw->'lotSummary'->>'lot_duration_sec')::float, 0) * 3600) as avg_uph
            FROM deduped
            GROUP BY bucket
        )
        SELECT
            recs.bucket,
            recs.total_units,
            recs.total_fail,
            CASE WHEN recs.total_units > 0
                 THEN ROUND(100.0 * recs.pass_count / recs.total_units, 2)
                 ELSE 0 END as avg_yield_pct,
            COALESCE(lots.avg_uph, 0) as avg_uph
        FROM recs
        LEFT JOIN lots ON lots.bucket = recs.bucket
        ORDER BY recs.bucket
        """
        rows = await conn.fetch(query, *params)
        groups = []
        for row in rows:
            bucket = row["bucket"]
            key = bucket.strftime("%Y-%m-%d") if group_by == "day" else f"{bucket.isocalendar().year}-W{bucket.isocalendar().week:02d}"
            groups.append({
                "key": key,
                "label": _group_label(group_by, bucket),
                "totalUnits": row["total_units"] or 0,
                "totalFail": row["total_fail"] or 0,
                "avgYieldPct": float(row["avg_yield_pct"] or 0.0),
                "avgUph": float(row["avg_uph"] or 0.0),
                "avgAvailabilityPct": status_by_group.get(key, {}).get("avgAvailabilityPct", 0.0),
                "totalDowntimeMin": status_by_group.get(key, {}).get("totalDowntimeMin", 0.0),
                "avgMtbfHours": mtbf_by_group.get(key),
                "topFailReasons": [],
            })
        return groups

    status_by_equipment = await _status_metrics_by_equipment(conn, equipment_id, from_date, to_date)
    mtbf_by_equipment = await _mtbf_by_equipment(conn, where_sql, params)
    fail_by_equipment_query = f"""
    WITH {deduped_cte},
    ranked AS (
        SELECT
            COALESCE(equipment_id, equipment_hash) as equipment_key,
            rec->>'fail_reason_code' as reason_code,
            COUNT(*) as count,
            ROW_NUMBER() OVER (
                PARTITION BY COALESCE(equipment_id, equipment_hash)
                ORDER BY COUNT(*) DESC
            ) as rn
        FROM deduped,
        jsonb_array_elements(payload_raw->'records') as rec
        WHERE rec->>'fail_reason_code' IS NOT NULL
          AND rec->>'fail_reason_code' != 'null'
        GROUP BY COALESCE(equipment_id, equipment_hash), rec->>'fail_reason_code'
    )
    SELECT equipment_key, reason_code, count
    FROM ranked
    WHERE rn <= 5
    ORDER BY equipment_key, count DESC
    """
    fail_rows = await conn.fetch(fail_by_equipment_query, *params)
    fail_by_equipment: Dict[str, List[Dict[str, Any]]] = {}
    for r in fail_rows:
        fail_by_equipment.setdefault(r["equipment_key"], []).append({
            "reason_code": r["reason_code"],
            "count": r["count"],
        })
    query = f"""
    WITH {deduped_cte},
    recs AS (
        SELECT
            COALESCE(d.equipment_id, d.equipment_hash) as equipment_key,
            MIN(d.equipment_hash) as equipment_hash,
            (array_agg(COALESCE(
                d.payload_raw->'lotSummary'->>'recipeId',
                d.payload_raw->'lotSummary'->>'recipe_id',
                d.payload_raw->'lotSummary'->>'recipeHash'
            ) ORDER BY d.dispatched_at DESC))[1] as recipe_id,
            COUNT(*) FILTER (WHERE rec->>'overall_result' IS NOT NULL) as total_units,
            COUNT(*) FILTER (WHERE rec->>'overall_result' = 'FAIL') as total_fail,
            COUNT(*) FILTER (WHERE rec->>'overall_result' = 'PASS') as pass_count
        FROM deduped d,
        jsonb_array_elements(d.payload_raw->'records') as rec
        GROUP BY COALESCE(d.equipment_id, d.equipment_hash)
    ),
    batch_meta AS (
        SELECT
            COALESCE(equipment_id, equipment_hash) as equipment_key,
            SUM(COALESCE(jsonb_array_length(payload_raw->'alarmHistory'), 0)) as alarm_count,
            COUNT(*) FILTER (WHERE payload_raw->'oracleAnalysis'->0->>'judgment' = 'WARNING') as marginal_count
        FROM deduped
        GROUP BY COALESCE(equipment_id, equipment_hash)
    ),
    uph AS (
        SELECT
            COALESCE(equipment_id, equipment_hash) as equipment_key,
            AVG((payload_raw->'lotSummary'->>'total_units')::float /
                NULLIF((payload_raw->'lotSummary'->>'lot_duration_sec')::float, 0) * 3600) as avg_uph
        FROM deduped
        GROUP BY COALESCE(equipment_id, equipment_hash)
    )
    SELECT
        recs.equipment_key,
        recs.equipment_hash,
        recs.recipe_id,
        recs.total_units,
        recs.total_fail,
        CASE WHEN recs.total_units > 0
             THEN ROUND(100.0 * recs.pass_count / recs.total_units, 2)
             ELSE 0 END as avg_yield_pct,
        COALESCE(uph.avg_uph, 0) as avg_uph,
        COALESCE(batch_meta.alarm_count, 0) as alarm_count,
        COALESCE(batch_meta.marginal_count, 0) as marginal_count
    FROM recs
    LEFT JOIN uph ON uph.equipment_key = recs.equipment_key
    LEFT JOIN batch_meta ON batch_meta.equipment_key = recs.equipment_key
    ORDER BY recs.total_units DESC, recs.equipment_key
    """
    rows = await conn.fetch(query, *params)
    return [
        {
            "key": r["equipment_key"],
            "name": r["equipment_key"],
            "equipmentHash": r["equipment_hash"],
            "recipeId": r["recipe_id"],
            "totalUnits": r["total_units"] or 0,
            "totalFail": r["total_fail"] or 0,
            "avgYieldPct": float(r["avg_yield_pct"] or 0.0),
            "yieldPct": float(r["avg_yield_pct"] or 0.0),
            "avgUph": float(r["avg_uph"] or 0.0),
            "avgAvailabilityPct": status_by_equipment.get(r["equipment_key"], {}).get("availabilityPct", 0.0),
            "totalDowntimeMin": status_by_equipment.get(r["equipment_key"], {}).get("downtimeMin", 0.0),
            "avgMtbfHours": mtbf_by_equipment.get(r["equipment_key"]),
            "alarmCount": r["alarm_count"] or 0,
            "marginalCount": r["marginal_count"] or 0,
            "topFailReasons": fail_by_equipment.get(r["equipment_key"], []),
        } for r in rows
    ]

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
