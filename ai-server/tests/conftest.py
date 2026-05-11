import os

# Set dummy environment variables for tests
os.environ["AI_INGEST_API_KEY"] = "test-key"
os.environ["BACKEND_JWT_SECRET"] = "test-secret"
os.environ["PG_PASSWORD"] = "test-password"
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"

import uuid
from datetime import datetime

def get_mock_batch(batch_id: str = None, lot_hash: str = "lot_123", equip_hash: str = "equip_456") -> dict:
    return {
        "batchId": batch_id or str(uuid.uuid4()),
        "dispatchedAt": datetime.now().isoformat(),
        "lotHash": lot_hash,
        "equipmentHash": equip_hash,
        "totalRecords": 1,
        "records": [
            {
                "message_id": "msg_1",
                "time": datetime.now().isoformat(),
                "lotHash": lot_hash,
                "equipmentHash": equip_hash,
                "strip_id": 1,
                "unit_id": 1,
                "overall_result": "PASS",
                "fail_count": 0,
                "total_inspected_count": 1,
                "inspection_duration_ms": 100,
                "takt_time_ms": 500,
                "algorithm_version": "v1"
            }
        ],
        "lotSummary": {
            "lotHash": lot_hash,
            "equipmentHash": equip_hash,
            "lot_status": "COMPLETED",
            "recipe_id": "RECIPE_A",
            "total_units": 1,
            "pass_count": 1,
            "fail_count": 0,
            "yield_pct": 100.0,
            "lot_duration_sec": 60
        }
    }
