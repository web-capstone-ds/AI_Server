import pytest
import jwt
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from src.main import app
from src.config import settings
from unittest.mock import patch, MagicMock, AsyncMock

client = TestClient(app)

def create_test_jwt():
    payload = {
        "sub": "web-backend",
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    return jwt.encode(payload, settings.BACKEND_JWT_SECRET, algorithm="HS256")

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
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_get_pool.return_value = mock_pool

    token = create_test_jwt()
    response = client.get("/api/batches", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
@patch("src.db.pool.db_pool.get_pool")
async def test_kpi_summary_mock(mock_get_pool):
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        {"total_lots": 1, "total_units": 100, "total_fail": 5, "avg_yield_pct": 95.0, "avg_uph": 400.0},
        {"danger_count": 0, "warning_count": 1, "marginal_count": 1},
        {"total_equip_count": 2, "active_equip_count": 1},
        {"avg_availability_pct": 90.0, "total_downtime_min": 10.0},
        {"avg_mtbf_hours": 12.5}
    ]
    mock_conn.fetch.side_effect = [
        [{"reason_code": "E001", "count": 10}],
        [{"equipment_id": "EQ1", "avg_yield": 98.0, "total_units": 1000, "avg_uph": 120.0, "status": "RUN"}]
    ]
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_get_pool.return_value = mock_pool

    token = create_test_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/batches/kpi-summary", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["totalUnits"] == 100
    assert data["avgYieldPct"] == 95.0
    assert data["avgMtbfHours"] == 12.5
    assert len(data["topFailReasons"]) == 1
    assert data["topFailReasons"][0]["reason_code"] == "E001"
    assert len(data["equipmentDetails"]) == 1
    assert data["equipmentDetails"][0]["equipmentId"] == "EQ1"

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
