from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, field_validator

from src.models.dispatch_batch import (
    normalize_equipment_status,
    normalize_datetime_to_utc,
)


class StatusSnapshotRecord(BaseModel):
    """단일 status_updates 레코드 (비식별화 후)."""
    time: datetime
    equipment_status: str

    @field_validator("equipment_status", mode="after")
    @classmethod
    def _normalize_status(cls, v: str) -> str:
        return normalize_equipment_status(v)

    @field_validator("time", mode="after")
    @classmethod
    def _normalize_time(cls, v: datetime) -> datetime:
        return normalize_datetime_to_utc(v)


class EquipmentStatusSnapshot(BaseModel):
    """
    한 장비의 status_updates 구간 묶음.
    dispatcher가 워터마크 이후 신규 상태 레코드를 모아 전송한다.
    """
    equipmentHash: str
    equipmentId: Optional[str] = None
    statuses: List[StatusSnapshotRecord]


class StatusIngestResponse(BaseModel):
    status: str
    received: int
