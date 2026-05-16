from typing import List, Dict, Optional, Union
from pydantic import BaseModel
from src.models.kpi import ReportPeriod, FailReasonCount

class RecipeMetric(BaseModel):
    recipe_id: str
    avgYieldPct: float
    totalLots: int

class EquipmentMetric(BaseModel):
    equipmentId: str
    avgYieldPct: float
    avgUph: float
    alarmCount: int

class ReportMetrics(BaseModel):
    # Production Metrics
    totalLots: int
    avgYieldPct: float
    minYieldPct: float
    maxYieldPct: float
    totalFailCount: int
    avgUph: float
    topFailReasons: List[FailReasonCount]
    recipeBreakdown: List[RecipeMetric]
    # Oracle Metrics
    judgmentDistribution: Dict[str, int]
    marginalCount: int
    # Equipment Metrics
    avgAvailabilityPct: float
    totalDowntimeMin: float
    avgMtbfHours: Optional[float] = None
    equipmentBreakdown: List[EquipmentMetric]

class Insight(BaseModel):
    severity: str # info | warning | critical
    category: str # yield | quality | equipment | recipe
    message: str
    evidence: Union[List[str], str]

class LotBrief(BaseModel):
    lotHash: str
    yield_pct: float
    judgment: str

class AnalysisReport(BaseModel):
    reportId: str
    reportType: str # daily | weekly
    generatedAt: str
    period: ReportPeriod
    summary: str
    metrics: ReportMetrics
    insights: List[Insight]
    recommendations: List[str]
    lotDetails: List[LotBrief]
