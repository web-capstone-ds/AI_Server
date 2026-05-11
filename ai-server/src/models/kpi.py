from typing import List, Optional
from pydantic import BaseModel

class ReportPeriod(BaseModel):
    start: str
    end: str

class FailReasonCount(BaseModel):
    reason_code: str
    count: int

class EquipmentKpi(BaseModel):
    equipmentId: str
    avgYieldPct: float
    totalUnits: int
    avgUph: float
    status: str # RUN / IDLE / STOP

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
    totalDowntimeMin: float
    activeEquipmentCount: int
    totalEquipmentCount: int
    avgMtbfHours: Optional[float] = None
    # Quality KPI
    topFailReasons: List[FailReasonCount]
    # Equipment Details
    equipmentDetails: List[EquipmentKpi]
