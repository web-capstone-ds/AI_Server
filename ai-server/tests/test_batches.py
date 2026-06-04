import pytest
import jwt
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from src.main import app
from src.config import settings
from tests.conftest import TEST_BACKEND_JWT_PRIVATE_KEY
from unittest.mock import patch, MagicMock, AsyncMock

client = TestClient(app)

def create_test_jwt():
    now = datetime.utcnow()
    payload = {
        "sub": "web-backend",
        "iat": now,
        "exp": now + timedelta(hours=1)
    }
    return jwt.encode(payload, TEST_BACKEND_JWT_PRIVATE_KEY.replace("\\n", "\n"), algorithm="RS256")

def test_get_batches_auth_failure():
    response = client.get("/api/batches")
    assert response.status_code == 401 # Missing Authorization header

def test_get_batches_invalid_jwt():
    response = client.get("/api/batches", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401

@pytest.mark.asyncio
@patch("src.db.pool.db_pool.get_pool")
async def test_get_batches_with_jwt(mock_get_pool):
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    mock_conn.fetchrow.return_value = {"count": 0}
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_get_pool.return_value = mock_pool

    token = create_test_jwt()
    response = client.get("/api/batches", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["items"] == []
    assert body["data"]["page"] == {
        "number": 1,
        "size": 50,
        "totalElements": 0,
        "totalPages": 0,
        "hasNext": False,
    }

@pytest.mark.asyncio
@patch("src.db.pool.db_pool.get_pool")
async def test_get_batches_filters_by_plain_id_or_equipment_hash(mock_get_pool):
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    mock_conn.fetchrow.return_value = {"count": 0}
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_get_pool.return_value = mock_pool

    token = create_test_jwt()
    response = client.get("/api/batches?equipmentId=hash-eq1", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    query = mock_conn.fetch.call_args.args[0]
    assert "equipment_id" in query
    assert "equipment_hash" in query
    assert mock_conn.fetch.call_args.args[1] == "hash-eq1"

@pytest.mark.asyncio
@patch("src.db.pool.db_pool.get_pool")
async def test_kpi_summary_mock(mock_get_pool):
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        {"total_lots": 1, "total_inspected": 100, "pass_count": 95, "fail_count": 5, "yield_pct": 95.0, "avg_uph": 400.0},
        {"danger_count": 0, "warning_count": 1, "marginal_count": 1},
        {"observed_equip_count": 2, "active_equip_count": 1},
        {"avg_availability_pct": 90.0, "avg_idle_pct": 5.0, "total_downtime_min": 10.0},
        {"avg_mtbf_hours": 12.5}
    ]
    mock_conn.fetch.side_effect = [
        [{"reason_code": "E001", "count": 10}],
        # 장비 목록은 status log 기준 — LOT가 없어 생산 0인 장비(IDLE)도 포함된다.
        [
            {"equipment_key": "EQ1", "equipment_hash": "hash-eq1", "avg_yield": 98.0, "total_units": 1000, "avg_uph": 120.0, "status": "RUN"},
            {"equipment_key": "EQ3", "equipment_hash": "hash-eq3", "avg_yield": 0.0, "total_units": 0, "avg_uph": 0.0, "status": "IDLE"},
        ]
    ]
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_get_pool.return_value = mock_pool

    token = create_test_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/batches/kpi-summary", headers=headers)
    assert response.status_code == 200
    body = response.json()
    # Backend envelope: {status, data:{period, summary, groups}}
    assert body["status"] == "ok"
    summary = body["data"]["summary"]
    assert summary["totalUnits"] == 100
    assert summary["totalInspected"] == 100
    assert summary["totalFail"] == 5
    assert summary["avgYieldPct"] == 95.0
    # No equipment filter -> denominator is the configured equipment master.
    assert summary["totalEquipmentCount"] == len(settings.equipment_master_list)
    assert summary["activeEquipmentCount"] == 1
    assert summary["avgAvailabilityPct"] == 90.0
    assert summary["avgIdlePct"] == 5.0
    assert summary["avgMtbfHours"] == 12.5
    assert len(summary["topFailReasons"]) == 1
    assert summary["topFailReasons"][0]["reason_code"] == "E001"
    assert len(summary["equipmentDetails"]) == 2
    assert summary["equipmentDetails"][0]["equipmentId"] == "EQ1"
    assert summary["equipmentDetails"][0]["equipmentHash"] == "hash-eq1"
    # 생산이 없는(LOT 미완료) 장비도 상태 피드 기준으로 목록에 포함된다.
    idle = next(e for e in summary["equipmentDetails"] if e["equipmentId"] == "EQ3")
    assert idle["status"] == "IDLE"
    assert idle["totalUnits"] == 0

@pytest.mark.asyncio
@patch("src.db.pool.db_pool.get_pool")
async def test_kpi_summary_uses_equipment_hash_when_plain_id_is_null(mock_get_pool):
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        {"total_lots": 1, "total_inspected": 100, "pass_count": 95, "fail_count": 5, "yield_pct": 95.0, "avg_uph": 400.0},
        {"danger_count": 0, "warning_count": 1, "marginal_count": 1},
        {"observed_equip_count": 1, "active_equip_count": 1},
        {"avg_availability_pct": 90.0, "avg_idle_pct": 5.0, "total_downtime_min": 10.0},
        {"avg_mtbf_hours": None}
    ]
    mock_conn.fetch.side_effect = [
        [],
        [{"equipment_key": "hash-only", "equipment_hash": "hash-only", "avg_yield": 98.0, "total_units": 1000, "avg_uph": 120.0, "status": "RUN"}]
    ]
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_get_pool.return_value = mock_pool

    token = create_test_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/batches/kpi-summary", headers=headers)

    assert response.status_code == 200
    summary = response.json()["data"]["summary"]
    assert summary["equipmentDetails"][0]["equipmentId"] == "hash-only"
    assert summary["equipmentDetails"][0]["equipmentHash"] == "hash-only"

@pytest.mark.asyncio
@patch("src.db.pool.db_pool.get_pool")
async def test_latest_returns_enveloped_batch_with_derived(mock_get_pool):
    import json
    payload = {
        "equipmentId": "DS-VIS-001",
        "records": [{
            "overall_result": "FAIL",
            "inspection_detail": {
                "side_result": [
                    {"ZAxisNum": 6, "ErrorType": 12, "XOffset": 0, "YOffset": 0},
                    {"ZAxisNum": 7, "ErrorType": 12, "XOffset": 0, "YOffset": 0},
                ],
                "prs_result": [
                    {"ZAxisNum": 0, "ErrorType": 0, "XOffset": 5, "YOffset": 2},
                ],
            },
            "geometric": {"dimension_w_mm": 10.08},
            "singulation": {"chipping_top_um": 52.0},
        }],
        "alarmHistory": [],
    }
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"payload_raw": json.dumps(payload)}
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_get_pool.return_value = mock_pool

    token = create_test_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/batches/latest?equipmentId=DS-VIS-001", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["batch"]["equipmentId"] == "DS-VIS-001"
    derived = body["data"]["derived"]
    assert len(derived["perSlotStats"]) == 3  # slots 0, 6, 7
    # ET=12 가 최다 (slot 6,7) → patternName 후보
    top = max(derived["errorTypeDistribution"], key=lambda e: e["count"])
    assert top["errorType"] == 12

@pytest.mark.asyncio
@patch("src.db.pool.db_pool.get_pool")
async def test_latest_accepts_equipment_hash_filter(mock_get_pool):
    import json
    payload = {
        "equipmentHash": "hash-eq1",
        "records": [],
        "alarmHistory": [],
    }
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"payload_raw": json.dumps(payload)}
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_get_pool.return_value = mock_pool

    token = create_test_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/batches/latest?equipmentId=hash-eq1", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["batch"]["equipmentHash"] == "hash-eq1"
    query = mock_conn.fetchrow.call_args.args[0]
    assert "equipment_hash" in query
    assert mock_conn.fetchrow.call_args.args[1] == "hash-eq1"


@pytest.mark.asyncio
@patch("src.db.pool.db_pool.get_pool")
async def test_latest_no_batch_returns_null_data(mock_get_pool):
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_get_pool.return_value = mock_pool

    token = create_test_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/batches/latest?equipmentId=NONE", headers=headers)
    assert response.status_code == 200
    body = response.json()
    # data=null → Spring BatchEnvelope.ok() == false → Optional.empty() → mock fallback
    assert body["data"] is None


@pytest.mark.asyncio
@patch("src.db.pool.db_pool.get_pool")
async def test_get_batch_detail_404(mock_get_pool):
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None # Not found
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_get_pool.return_value = mock_pool

    token = create_test_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/batches/non-existent-uuid", headers=headers)
    assert response.status_code == 404
