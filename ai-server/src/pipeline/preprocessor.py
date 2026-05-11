from typing import Dict, Any
import numpy as np
from src.models.dispatch_batch import DispatchBatch
import structlog

logger = structlog.get_logger()

def aggregate_lot_stats(batch: DispatchBatch) -> Dict[str, Any]:
    """
    Aggregates statistical metrics from the batch records.
    Handles PASS drop policy: detailed fields are only present for FAIL records.
    """
    total = len(batch.records)
    if total == 0:
        return {}

    # 1. Yield & Results
    pass_count = sum(1 for r in batch.records if r.overall_result == "PASS")
    fail_count = sum(1 for r in batch.records if r.overall_result == "FAIL")
    yield_pct = (pass_count / total * 100) if total > 0 else 0.0

    # 2. Process Performance (Takt time, Duration)
    takt_times = [r.takt_time_ms for r in batch.records]
    durations = [r.inspection_duration_ms for r in batch.records]
    
    # 3. Fail Reason Distribution
    fail_reasons: Dict[str, int] = {}
    for r in batch.records:
        if r.overall_result == "FAIL" and r.fail_reason_code:
            fail_reasons[r.fail_reason_code] = fail_reasons.get(r.fail_reason_code, 0) + 1

    # 4. Quality Metrics (Only for FAIL records with details)
    # Example: Chipping from singulation
    chipping_values = []
    for r in batch.records:
        if r.overall_result == "FAIL" and r.singulation:
            # Safely get value from potentially nested/different structures
            val = r.singulation.get("chipping_top_um")
            if val is not None:
                chipping_values.append(val)

    return {
        "pass_count": pass_count,
        "fail_count": fail_count,
        "yield_pct": yield_pct,
        "takt_p50": np.median(takt_times) if takt_times else 0,
        "takt_p95": np.percentile(takt_times, 95) if takt_times else 0,
        "duration_p50": np.median(durations) if durations else 0,
        "duration_p95": np.percentile(durations, 95) if durations else 0,
        "fail_reasons": fail_reasons,
        "avg_chipping": np.mean(chipping_values) if chipping_values else None
    }

def aggregate_alarm_stats(batch: DispatchBatch) -> Dict[str, Any]:
    if not batch.alarmHistory:
        return {}
    
    levels: Dict[str, int] = {}
    sources: Dict[str, int] = {}
    for a in batch.alarmHistory:
        levels[a.alarm_level] = levels.get(a.alarm_level, 0) + 1
        sources[a.hw_error_source] = sources.get(a.hw_error_source, 0) + 1
        
    return {
        "count": len(batch.alarmHistory),
        "levels": levels,
        "sources": sources
    }

def aggregate_availability_stats(batch: DispatchBatch) -> Dict[str, Any]:
    if not batch.statusHistory:
        return {}
    
    total_uptime = sum(s.uptime_sec for s in batch.statusHistory)
    status_durations: Dict[str, int] = {}
    for s in batch.statusHistory:
        status_durations[s.equipment_status] = status_durations.get(s.equipment_status, 0) + s.uptime_sec
        
    run_time = status_durations.get("RUN", 0)
    availability = (run_time / total_uptime * 100) if total_uptime > 0 else 0.0
    
    return {
        "availability_pct": availability,
        "run_sec": run_time,
        "stop_sec": status_durations.get("STOP", 0),
        "idle_sec": status_durations.get("IDLE", 0)
    }
