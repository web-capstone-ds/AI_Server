"""
조회 시점 derived 통계 계산.

Spring 백엔드의 DerivedBatchStats(AiDtos.java) 계약에 맞춰
payload_raw->records 에서 perSlotStats / geometricStats / singulationStats /
histogramBuckets / errorTypeDistribution 를 산출한다.

주의:
- PASS drop 정책상 상세 필드(inspection_detail/geometric/singulation)는 FAIL
  레코드에만 존재할 수 있다. 모든 추출은 null-safe 하며 표본이 없으면 빈 값으로 둔다.
- fail 판정 = ErrorType != 0 (0 = 정상). InspectionResult 의미는 mock 기준 가정.
- usl/lsl/cpk 등 규격 의존 필드는 AI 서버가 recipe_specs 를 보유하지 않으므로 None.
  Spring 이 recipe_specs 로 cpk/guidelines 를 자체 계산한다.
"""
from typing import Any, Dict, List, Optional
from collections import Counter
import numpy as np
import structlog

logger = structlog.get_logger()

# geometricStats[0] 은 Spring firstMetric/cpk 가 사용하므로 순서 의미 있음.
GEOMETRIC_METRICS = ["dimension_w_mm", "dimension_l_mm", "dimension_h_mm", "kerf_width_um"]
SINGULATION_METRICS = ["chipping_top_um", "chipping_bottom_um", "burr_height_um"]
HISTOGRAM_BINS = 10


def compute_derived(batch: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """payload_raw(dict) -> DerivedBatchStats(dict). batch 없으면 None."""
    if not batch:
        return None
    records = batch.get("records") or []

    per_slot, error_dist = _slot_and_error_stats(records)
    geometric = _metric_stats(records, "geometric", GEOMETRIC_METRICS)
    singulation = _metric_stats(records, "singulation", SINGULATION_METRICS)
    histograms = _histogram_buckets(records, "geometric", GEOMETRIC_METRICS[:1])

    return {
        "perSlotStats": per_slot,
        "geometricStats": geometric,
        "singulationStats": singulation,
        "histogramBuckets": histograms,
        "errorTypeDistribution": error_dist,
    }


def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    f = _to_float(value)
    return int(f) if f is not None else None


def _slot_and_error_stats(records: List[Dict[str, Any]]):
    """ZAxisNum 0~7 별 prs/side 집계와 ErrorType 분포."""
    # slot -> {"prs": [entries], "side": [entries]}
    slots: Dict[int, Dict[str, List[dict]]] = {}
    # (errorType) -> {"count", "slots": set(), "sides": set()}
    errors: Dict[int, Dict[str, Any]] = {}

    for rec in records:
        detail = rec.get("inspection_detail")
        if not isinstance(detail, dict):
            continue
        for side_key, group in (("prs", "prs_result"), ("side", "side_result")):
            entries = detail.get(group)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                z = _to_int(entry.get("ZAxisNum"))
                if z is None:
                    continue
                slots.setdefault(z, {"prs": [], "side": []})[side_key].append(entry)
                et = _to_int(entry.get("ErrorType"))
                if et is not None and et != 0:
                    bucket = errors.setdefault(et, {"count": 0, "slots": set(), "sides": set()})
                    bucket["count"] += 1
                    bucket["slots"].add(z)
                    bucket["sides"].add(side_key)

    per_slot: List[Dict[str, Any]] = []
    for z in sorted(slots.keys()):
        prs = slots[z]["prs"]
        side = slots[z]["side"]
        prs_fail = sum(1 for e in prs if (_to_int(e.get("ErrorType")) or 0) != 0)
        side_fail = sum(1 for e in side if (_to_int(e.get("ErrorType")) or 0) != 0)

        # 해당 슬롯 fail 중 최빈 ErrorType
        fail_types = [
            et for e in (prs + side)
            if (et := _to_int(e.get("ErrorType"))) is not None and et != 0
        ]
        dominant = Counter(fail_types).most_common(1)[0][0] if fail_types else None

        x_vals = [v for e in (prs + side) if (v := _to_float(e.get("XOffset"))) is not None]
        y_vals = [v for e in (prs + side) if (v := _to_float(e.get("YOffset"))) is not None]

        per_slot.append({
            "zAxisNum": z,
            "prsTotal": len(prs),
            "prsFail": prs_fail,
            "prsFailRatePct": _rate(prs_fail, len(prs)),
            "sideTotal": len(side),
            "sideFail": side_fail,
            "sideFailRatePct": _rate(side_fail, len(side)),
            "dominantErrorType": dominant,
            "xOffsetP95": _round(np.percentile(x_vals, 95)) if x_vals else None,
            "yOffsetP95": _round(np.percentile(y_vals, 95)) if y_vals else None,
        })

    total_errors = sum(b["count"] for b in errors.values())
    error_dist: List[Dict[str, Any]] = []
    for et, b in sorted(errors.items(), key=lambda kv: kv[1]["count"], reverse=True):
        sides = b["sides"]
        side_label = "both" if len(sides) > 1 else next(iter(sides), None)
        error_dist.append({
            "errorType": et,
            "count": b["count"],
            "ratio": _rate(b["count"], total_errors),
            "affectedSlots": sorted(b["slots"]),
            "side": side_label,
        })

    return per_slot, error_dist


def _metric_stats(records: List[Dict[str, Any]], section: str, metrics: List[str]) -> List[Dict[str, Any]]:
    """records[section][metric] 수치들에 대한 MetricStat 목록 (값이 있는 metric만)."""
    result: List[Dict[str, Any]] = []
    for metric in metrics:
        values = _collect(records, section, metric)
        if not values:
            continue
        arr = np.array(values, dtype=float)
        result.append({
            "metric": metric,
            "n": int(arr.size),
            "mean": _round(arr.mean()),
            "stdev": _round(arr.std(ddof=1)) if arr.size > 1 else 0.0,
            "min": _round(arr.min()),
            "max": _round(arr.max()),
            "p50": _round(np.percentile(arr, 50)),
            "p95": _round(np.percentile(arr, 95)),
            "p99": _round(np.percentile(arr, 99)),
            "usl": None,
            "lsl": None,
            "cp": None,
            "cpk": None,
            "inSpecPct": None,
        })
    return result


def _histogram_buckets(records: List[Dict[str, Any]], section: str, metrics: List[str]) -> Dict[str, Any]:
    """주 metric 들에 대한 HistogramBucket map. Spring histogram() 은 첫 bucket 만 사용."""
    buckets: Dict[str, Any] = {}
    for metric in metrics:
        values = _collect(records, section, metric)
        if not values:
            continue
        arr = np.array(values, dtype=float)
        counts, edges = np.histogram(arr, bins=HISTOGRAM_BINS)
        buckets[metric] = {
            "bucketEdges": [_round(e) for e in edges.tolist()],
            "counts": [int(c) for c in counts.tolist()],
            "mean": _round(arr.mean()),
            "usl": None,
            "lsl": None,
        }
    return buckets


def _collect(records: List[Dict[str, Any]], section: str, metric: str) -> List[float]:
    out: List[float] = []
    for rec in records:
        sect = rec.get(section)
        if isinstance(sect, dict):
            v = _to_float(sect.get(metric))
            if v is not None:
                out.append(v)
    return out


def _rate(part: int, whole: int) -> float:
    return _round(part / whole * 100) if whole else 0.0


def _round(value: Any) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 4)
