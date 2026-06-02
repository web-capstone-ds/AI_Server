import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from src.main import app
from src.config import settings
from tests.conftest import get_mock_batch

client = TestClient(app)


def get_mock_status_snapshot():
    return {
        "equipmentHash": "hash-eq3",
        "statuses": [
            {"time": "2026-06-03T00:00:00Z", "equipment_status": "IDLE"},
            {"time": "2026-06-03T00:01:00Z", "equipment_status": "RUNNING"},
        ],
    }

# Mocking DB to avoid actual connection in pure unit test
# In a real environment, we'd use a test DB or mock the DB pool

def test_ingest_auth_failure():
    payload = get_mock_batch()
    response = client.post("/api/ingest", json=payload, headers={"X-Api-Key": "wrong"})
    assert response.status_code == 401

@pytest.mark.skip(reason="Requires DB connection")
def test_ingest_success():
    payload = get_mock_batch()
    headers = {"X-Api-Key": settings.AI_INGEST_API_KEY}
    response = client.post("/api/ingest", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

def test_pydantic_validation():
    # Missing required field totalRecords
    payload = get_mock_batch()
    del payload["totalRecords"]
    headers = {"X-Api-Key": settings.AI_INGEST_API_KEY}
    response = client.post("/api/ingest", json=payload, headers=headers)
    assert response.status_code == 422 # Pydantic validation error

def test_extra_fields_allowed():
    # Extra field at root and in sub-model
    payload = get_mock_batch()
    payload["unknown_root_field"] = "value"
    payload["records"][0]["unknown_sub_field"] = 123
    
    # This should NOT fail because of ConfigDict(extra="allow")
    # But we can't easily check success without DB, so we just verify it passes Pydantic in a separate test
    from src.models.dispatch_batch import DispatchBatch
    model = DispatchBatch(**payload)
    assert model.unknown_root_field == "value"
    assert model.records[0].unknown_sub_field == 123

def test_status_ingest_auth_failure():
    response = client.post("/api/ingest/status", json=get_mock_status_snapshot(), headers={"X-Api-Key": "wrong"})
    assert response.status_code == 401


def test_status_ingest_validation():
    # Missing required field equipmentHash
    payload = get_mock_status_snapshot()
    del payload["equipmentHash"]
    headers = {"X-Api-Key": settings.AI_INGEST_API_KEY}
    response = client.post("/api/ingest/status", json=payload, headers=headers)
    assert response.status_code == 422


def test_status_snapshot_normalizes_status():
    # Pydantic normalizes equipment_status (RUNNING -> RUN) and time -> UTC
    from src.models.status_snapshot import EquipmentStatusSnapshot
    model = EquipmentStatusSnapshot(**get_mock_status_snapshot())
    assert [s.equipment_status for s in model.statuses] == ["IDLE", "RUN"]


@pytest.mark.asyncio
@patch("src.db.pool.db_pool.get_pool")
async def test_status_ingest_success(mock_get_pool):
    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    # conn.transaction() must return an async context manager (not a coroutine)
    mock_conn.transaction = MagicMock(return_value=AsyncMock())
    mock_get_pool.return_value = mock_pool

    headers = {"X-Api-Key": settings.AI_INGEST_API_KEY}
    response = client.post("/api/ingest/status", json=get_mock_status_snapshot(), headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["received"] == 2
    mock_conn.executemany.assert_awaited_once()


def test_alarm_history_masks_pii():
    from src.models.dispatch_batch import DispatchBatch

    payload = get_mock_batch()
    payload["alarmHistory"] = [{
        "time": "2026-05-31T00:00:00Z",
        "alarm_level": "WARNING",
        "hw_error_code": "TEST_ERR",
        "hw_error_source": "SECURITY_TEST",
        "hw_error_detail": "작업자 김철수(010-1234-5678) test@example.com ENG-KIM",
        "auto_recovery_attempted": False,
        "requires_manual_intervention": True,
    }]

    model = DispatchBatch(**payload)
    assert model.alarmHistory[0].hw_error_detail == "작업자 김철수([PHONE]) [EMAIL] [ID]"
