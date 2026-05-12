import re
import math
from datetime import datetime, timezone
from typing import List, Dict, Any

# Yield/quality-related query keywords
_YIELD_PATTERN = re.compile(
    r"수율|yield|불량|fail|품질|quality|defect|불합격|marginal|위험|DANGER|WARNING",
    re.IGNORECASE,
)

_HALF_LIFE_DAYS = 7.0  # chunks older than 7 days lose half their recency boost

W_DISTANCE = 0.60  # primary: semantic similarity
W_TIME     = 0.25  # secondary: recency
W_YIELD    = 0.15  # conditional: yield anomaly (only for yield-related queries)


def _recency_penalty(dispatched_at) -> float:
    """Exponential decay penalty [0, 1]. 0 = just dispatched, approaches 1 for old chunks."""
    if dispatched_at is None:
        return 0.5
    if isinstance(dispatched_at, str):
        try:
            dispatched_at = datetime.fromisoformat(dispatched_at)
        except Exception:
            return 0.5
    now = datetime.now(timezone.utc)
    if dispatched_at.tzinfo is None:
        dispatched_at = dispatched_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - dispatched_at).total_seconds() / 86400.0)
    return 1.0 - math.exp(-age_days * math.log(2) / _HALF_LIFE_DAYS)


def _yield_anomaly_score(yield_pct) -> float:
    """Anomaly relevance [0, 1]. Higher when yield is lower (more abnormal)."""
    if yield_pct is None:
        return 0.0
    return max(0.0, (100.0 - float(yield_pct)) / 100.0)


def rerank_chunks(query: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Reranks retrieved chunks using three signals:
    - Semantic distance  (pgvector cosine distance, weight 0.60)
    - Recency            (7-day exponential half-life, weight 0.25)
    - Yield anomaly      (activated for yield/quality queries, weight 0.15)

    Lower final score = higher rank.
    """
    if not chunks:
        return chunks

    is_yield_query = bool(_YIELD_PATTERN.search(query))

    scored = []
    for chunk in chunks:
        distance    = float(chunk.get("distance", 1.0))
        time_pen    = _recency_penalty(chunk.get("dispatched_at"))
        yield_score = _yield_anomaly_score(chunk.get("yield_pct")) if is_yield_query else 0.0

        final_score = W_DISTANCE * distance + W_TIME * time_pen - W_YIELD * yield_score
        scored.append((final_score, chunk))

    scored.sort(key=lambda x: x[0])
    return [chunk for _, chunk in scored]
