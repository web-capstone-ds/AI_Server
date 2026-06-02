from typing import List, Tuple

import asyncpg
import structlog

from src.models.status_snapshot import EquipmentStatusSnapshot

logger = structlog.get_logger()


async def save_status_snapshot(conn: asyncpg.Connection, snapshot: EquipmentStatusSnapshot) -> int:
    """
    장비 실시간 상태 레코드를 equipment_status_log에 upsert한다.

    equipment_key = equipmentId(plaintext 모드) 우선, 없으면 equipmentHash.
    (equipment_key, ts) 기준 멱등(idempotent) — 재전송/중복 구간이 와도 누적 카운트되지 않는다.
    반환값은 수신한 레코드 수.
    """
    if not snapshot.statuses:
        return 0

    equipment_key = snapshot.equipmentId or snapshot.equipmentHash
    rows: List[Tuple] = [
        (equipment_key, snapshot.equipmentHash, snapshot.equipmentId, s.equipment_status, s.time)
        for s in snapshot.statuses
    ]

    await conn.executemany(
        """
        INSERT INTO equipment_status_log (equipment_key, equipment_hash, equipment_id, status, ts)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (equipment_key, ts) DO UPDATE SET status = EXCLUDED.status
        """,
        rows,
    )
    return len(rows)
