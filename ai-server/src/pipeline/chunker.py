from typing import List

from src.models.dispatch_batch import DispatchBatch
from src.pipeline.preprocessor import (
    aggregate_alarm_stats,
    aggregate_availability_stats,
    aggregate_lot_stats,
)


class Chunk:
    def __init__(self, type: str, text: str):
        self.type = type
        self.text = text


def create_chunks(batch: DispatchBatch) -> List[Chunk]:
    chunks: List[Chunk] = []
    lot_summary = batch.lotSummary
    lot_stats = aggregate_lot_stats(batch)
    prefix = "passage: "

    equipment = batch.equipmentId or batch.equipmentHash
    chunks.append(
        Chunk(
            "lot_summary",
            f"{prefix}LOT summary | lotHash={batch.lotHash} | equipment={equipment} | "
            f"recipe={lot_summary.recipe_id} | yield={lot_summary.yield_pct}% | "
            f"PASS={lot_summary.pass_count} | FAIL={lot_summary.fail_count} | "
            f"total_units={lot_summary.total_units} | lot_duration={lot_summary.lot_duration_sec}s",
        )
    )

    chunks.append(
        Chunk(
            "process",
            f"{prefix}Process metrics | lotHash={batch.lotHash} | "
            f"TaktTime(P50/P95)={lot_stats.get('takt_p50', 0)}/{lot_stats.get('takt_p95', 0)}ms | "
            f"InspectionDuration(P50/P95)={lot_stats.get('duration_p50', 0)}/{lot_stats.get('duration_p95', 0)}ms",
        )
    )

    if lot_summary.fail_count > 0 and lot_stats.get("fail_reasons"):
        reasons = ", ".join(f"{key}:{value}" for key, value in lot_stats["fail_reasons"].items())
        chunks.append(
            Chunk(
                "fail_analysis",
                f"{prefix}Failure analysis | lotHash={batch.lotHash} | fail_reason_distribution={reasons}",
            )
        )

    if lot_stats.get("avg_chipping") is not None:
        chunks.append(
            Chunk(
                "quality",
                f"{prefix}Quality metrics | lotHash={batch.lotHash} | "
                f"avg_chipping_top={lot_stats['avg_chipping']:.2f}um",
            )
        )

    for index, oracle_analysis in enumerate(batch.oracleAnalysis):
        yield_actual = oracle_analysis.yield_actual
        if yield_actual is None:
            yield_actual = oracle_analysis.yield_pct
        if yield_actual is None and getattr(oracle_analysis, "yield_status", None):
            yield_status = getattr(oracle_analysis, "yield_status")
            if isinstance(yield_status, dict):
                yield_actual = yield_status.get("actual")

        rules = str(oracle_analysis.violated_rules) if oracle_analysis.violated_rules else "None"
        chunks.append(
            Chunk(
                "oracle",
                f"{prefix}Oracle judgment({index + 1}) | lotHash={batch.lotHash} | "
                f"judgment={oracle_analysis.judgment} | yield={yield_actual}% | "
                f"violated_rules={rules} | comment={oracle_analysis.ai_comment or 'None'}",
            )
        )

    availability_stats = aggregate_availability_stats(batch)
    if availability_stats:
        chunks.append(
            Chunk(
                "availability",
                f"{prefix}Availability history | lotHash={batch.lotHash} | "
                f"availability={availability_stats['availability_pct']:.1f}% | "
                f"RUN={availability_stats['run_sec']}s | STOP={availability_stats['stop_sec']}s | "
                f"IDLE={availability_stats['idle_sec']}s",
            )
        )

    alarm_stats = aggregate_alarm_stats(batch)
    if alarm_stats:
        levels = ", ".join(f"{key}:{value}" for key, value in alarm_stats["levels"].items())
        chunks.append(
            Chunk(
                "alarm",
                f"{prefix}Alarm history | lotHash={batch.lotHash} | "
                f"alarm_count={alarm_stats['count']} | level_distribution={levels}",
            )
        )

    return chunks
