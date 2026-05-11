import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.config import settings
from tests.conftest import get_mock_batch

client = TestClient(app)

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
