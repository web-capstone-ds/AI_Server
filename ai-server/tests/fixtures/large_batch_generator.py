import uuid
import time
from datetime import datetime

def generate_large_batch(count: int = 2792) -> dict:
    lot_hash = f"lot_{uuid.uuid4().hex[:8]}"
    equip_hash = f"equip_{uuid.uuid4().hex[:8]}"
    
    records = []
    for i in range(count):
        records.append({
            "message_id": str(uuid.uuid4()),
            "time": datetime.now().isoformat(),
            "lotHash": lot_hash,
            "equipmentHash": equip_hash,
            "strip_id": (i // 10) + 1,
            "unit_id": (i % 10) + 1,
            "overall_result": "PASS" if i % 100 != 0 else "FAIL",
            "fail_count": 0 if i % 100 != 0 else 1,
            "total_inspected_count": 1,
            "inspection_duration_ms": 50,
            "takt_time_ms": 200,
            "algorithm_version": "v1.2.3"
        })
        
    return {
        "batchId": str(uuid.uuid4()),
        "dispatchedAt": datetime.now().isoformat(),
        "lotHash": lot_hash,
        "equipmentHash": equip_hash,
        "equipmentId": "DS-VIS-TEST",
        "totalRecords": count,
        "records": records,
        "lotSummary": {
            "lotHash": lot_hash,
            "equipmentHash": equip_hash,
            "lot_status": "COMPLETED",
            "recipe_id": "LARGE_BATCH_TEST",
            "total_units": count,
            "pass_count": count - (count // 100),
            "fail_count": count // 100,
            "yield_pct": 100.0 * (count - (count // 100)) / count,
            "lot_duration_sec": int(count * 0.2)
        }
    }
