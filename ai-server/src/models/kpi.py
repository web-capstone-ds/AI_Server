from typing import List, Optional
from pydantic import BaseModel, Field

class ReportPeriod(BaseModel):
    start: str
    end: str

class FailReasonCount(BaseModel):
    reason_code: str
    count: int

class EquipmentKpi(BaseModel):
    equipmentId: str
    equipmentHash: Optional[str] = None
    recipeId: Optional[str] = None
    totalFail: int = 0
    yieldPct: Optional[float] = None
    avgYieldPct: float
    totalUnits: int
    uph: Optional[float] = None
    avgUph: float
    availabilityPct: Optional[float] = None
    avgAvailabilityPct: float = 0.0
    downtimeMin: float = 0.0
    mtbfHours: Optional[float] = None
    alarmCount: int = 0
    marginalCount: int = 0
    topFailReasons: List[FailReasonCount] = Field(default_factory=list)
    yieldTrend: List[float] = Field(default_factory=list)
    status: Optional[str] = None # RUN / IDLE / STOP

class KpiSummaryResponse(BaseModel):
    period: ReportPeriod
    # Production KPI
    totalUnits: int
    totalInspected: int
    totalFail: int
    avgYieldPct: float
    avgUph: float
    # Oracle KPI
    marginalCount: int
    dangerCount: int
    warningCount: int
    # Operation KPI
    avgAvailabilityPct: float
    avgIdlePct: float = 0.0
    totalDowntimeMin: float
    activeEquipmentCount: int
    totalEquipmentCount: int
    avgMtbfHours: Optional[float] = None
    # Quality KPI
    topFailReasons: List[FailReasonCount]
    # Equipment Details
    equipmentDetails: List[EquipmentKpi]
