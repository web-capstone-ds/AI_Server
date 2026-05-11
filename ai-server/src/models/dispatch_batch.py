from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator
import uuid

# Helper for status normalization
def normalize_equipment_status(status: str) -> str:
    s = status.upper()
    if s in ["RUNNING", "RUN"]:
        return "RUN"
    if s in ["IDLE", "STANDBY"]:
        return "IDLE"
    if s in ["STOP", "STOPPED", "DOWN"]:
        return "STOP"
    return s

class BaseExtraModel(BaseModel):
    model_config = ConfigDict(extra="allow")

class AnonymizedInspectionRecord(BaseExtraModel):
    message_id: str
    time: datetime
    lotHash: str
    equipmentHash: str
    equipmentId: Optional[str] = None
    strip_id: int
    unit_id: int
    overall_result: str
    fail_reason_code: Optional[str] = None
    fail_count: int
    total_inspected_count: int
    inspection_duration_ms: int
    takt_time_ms: int
    algorithm_version: str
    inspection_detail: Optional[Dict[str, Any]] = None
    geometric: Optional[Dict[str, Any]] = None
    bga: Optional[Dict[str, Any]] = None
    surface: Optional[Dict[str, Any]] = None
    singulation: Optional[Dict[str, Any]] = None

class AnonymizedLotRecord(BaseExtraModel):
    lotHash: str
    equipmentHash: str
    lot_status: str
    recipe_id: str
    total_units: int
    pass_count: int
    fail_count: int
    yield_pct: float
    lot_duration_sec: int

class OracleAnalysisRecord(BaseExtraModel):
    message_id: str
    time: datetime
    lot_id_hash: Optional[str] = None
    lotHash: Optional[str] = None
    judgment: str
    yield_actual: Optional[float] = None
    yield_pct: Optional[float] = None
    ai_comment: Optional[str] = None
    violated_rules: Optional[Dict[str, Any]] = None
    isolation_forest_score: Optional[float] = None
    threshold_proposal: Optional[Dict[str, Any]] = None
    analysis_source: Optional[str] = None

class StatusHistoryRecord(BaseExtraModel):
    time: datetime
    equipment_status: str
    lot_id: Optional[str] = None
    recipe_id: Optional[str] = None
    uptime_sec: int
    current_unit_count: Optional[int] = None
    expected_total_units: Optional[int] = None
    current_yield_pct: Optional[float] = None

    @field_validator("equipment_status", mode="after")
    @classmethod
    def normalize_status(cls, v: str) -> str:
        return normalize_equipment_status(v)

class AlarmHistoryRecord(BaseExtraModel):
    time: datetime
    alarm_level: str
    hw_error_code: str
    hw_error_source: str
    hw_error_detail: str
    auto_recovery_attempted: bool
    requires_manual_intervention: bool
    burst_id: Optional[str] = None
    burst_count: Optional[int] = None
    payload_raw: Optional[Dict[str, Any]] = None

class DispatchBatch(BaseExtraModel):
    batchId: uuid.UUID
    dispatchedAt: datetime
    lotHash: str
    equipmentHash: str
    equipmentId: Optional[str] = None
    totalRecords: int
    records: List[AnonymizedInspectionRecord]
    lotSummary: AnonymizedLotRecord
    oracleAnalysis: List[OracleAnalysisRecord] = Field(default_factory=list)
    statusHistory: List[StatusHistoryRecord] = Field(default_factory=list)
    alarmHistory: List[AlarmHistoryRecord] = Field(default_factory=list)

class IngestResponse(BaseModel):
    status: str
    batchId: str
