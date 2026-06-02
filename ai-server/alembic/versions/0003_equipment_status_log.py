"""equipment_status_log: live RUN/IDLE/STOP timeline for all equipment

LOT batch와 무관하게 dispatcher가 주기적으로 적재하는 장비 실시간 상태 로그.
가동률(R/I/D)·비가동시간·현재 가동 장비 수의 단일 소스로 사용한다.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-03 01:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS equipment_status_log (
            equipment_key   TEXT            NOT NULL,
            equipment_hash  TEXT            NOT NULL,
            equipment_id    TEXT,
            status          TEXT            NOT NULL,
            ts              TIMESTAMPTZ     NOT NULL,
            ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
            PRIMARY KEY (equipment_key, ts)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_equipment_status_log_ts ON equipment_status_log (ts)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_equipment_status_log_key_ts ON equipment_status_log (equipment_key, ts DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS equipment_status_log")
