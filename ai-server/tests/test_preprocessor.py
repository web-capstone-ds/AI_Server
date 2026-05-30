from datetime import datetime
from src.models.dispatch_batch import DispatchBatch
from src.pipeline.preprocessor import aggregate_lot_stats
from tests.conftest import get_mock_batch

def test_aggregate_lot_stats_pass_only():
    # Setup PASS only batch
    data = get_mock_batch(lot_hash="PASS_LOT", equip_hash="EQ1")
    batch = DispatchBatch(**data)
    
    stats = aggregate_lot_stats(batch)
    assert stats["pass_count"] == 1
    assert stats["fail_count"] == 0
    assert stats["yield_pct"] == 100.0
    assert stats["avg_chipping"] is None # No fails, so no chipping

def test_aggregate_lot_stats_with_fail():
    # Setup batch with 1 PASS, 1 FAIL
    lot_hash = "MIXED_LOT"
    data = {
        "batchId": "550e8400-e29b-41d4-a716-446655440000",
        "dispatchedAt": datetime.now().isoformat(),
        "lotHash": lot_hash,
        "equipmentHash": "EQ1",
        "totalRecords": 2,
        "records": [
            {
                "message_id": "m1", "time": datetime.now().isoformat(),
                "lotHash": lot_hash, "equipmentHash": "EQ1",
                "strip_id": 1, "unit_id": 1, "overall_result": "PASS",
                "fail_count": 0, "total_inspected_count": 1,
                "inspection_duration_ms": 100, "takt_time_ms": 500, "algorithm_version": "v1"
            },
            {
                "message_id": "m2", "time": datetime.now().isoformat(),
                "lotHash": lot_hash, "equipmentHash": "EQ1",
                "strip_id": 1, "unit_id": 2, "overall_result": "FAIL",
                "fail_reason_code": "ET52", "fail_count": 1, "total_inspected_count": 1,
                "inspection_duration_ms": 110, "takt_time_ms": 510, "algorithm_version": "v1",
                "singulation": {"chipping_top_um": 45.5}
            }
        ],
        "lotSummary": {
            "lotHash": lot_hash, "equipmentHash": "EQ1", "lot_status": "COMPLETED",
            "recipeHash": "recipe_hash_r1", "total_units": 2, "pass_count": 1, "fail_count": 1,
            "yield_pct": 50.0, "lot_duration_sec": 120
        }
    }
    batch = DispatchBatch(**data)
    
    stats = aggregate_lot_stats(batch)
    assert stats["pass_count"] == 1
    assert stats["fail_count"] == 1
    assert stats["yield_pct"] == 50.0
    assert stats["fail_reasons"]["ET52"] == 1
    assert stats["avg_chipping"] == 45.5
