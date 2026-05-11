import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock
from src.main import app
from src.utils.auth import verify_backend_jwt
from anthropic import APITimeoutError

client = TestClient(app)

@pytest.fixture(autouse=True)
def skip_auth():
    app.dependency_overrides[verify_backend_jwt] = lambda: {"sub": "test-user"}
    yield
    app.dependency_overrides = {}

@pytest.fixture
def mock_db_pool():
    with patch("src.api.query.db_pool") as mock:
        mock_conn = AsyncMock()
        # Mocking the async with db_pool.get_pool().acquire() as conn:
        mock.get_pool.return_value.acquire.return_value.__aenter__.return_value = mock_conn
        yield mock_conn

@pytest.fixture
def mock_retriever():
    with patch("src.api.query.retrieve_relevant_chunks") as mock:
        yield mock

@pytest.fixture
def mock_llm():
    with patch("src.api.query.llm_client.get_completion") as mock:
        yield mock

def test_query_ai_success(mock_db_pool, mock_retriever, mock_llm):
    # Setup mocks
    mock_retriever.return_value = [
        {
            "chunk_type": "summary",
            "chunk_text": "test content",
            "lot_hash": "hash1",
            "equipment_id": "EQ1",
            "recipe_id": "REC1",
            "yield_pct": 98.5,
            "dispatched_at": "2024-01-01",
            "distance": 0.1
        }
    ]
    mock_llm.return_value = "AI Answer"
    
    # Request
    response = client.post(
        "/api/query",
        json={"question": "What is the yield of EQ1?"}
    )
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "AI Answer"
    assert len(data["sources"]) == 1
    assert data["confidence"] > 0

def test_query_ai_empty_db(mock_db_pool, mock_retriever):
    mock_retriever.return_value = []
    
    response = client.post(
        "/api/query",
        json={"question": "Any data?"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "정보를 찾을 수 없습니다" in data["answer"]
    assert data["confidence"] == 0

def test_query_ai_llm_timeout(mock_db_pool, mock_retriever, mock_llm):
    mock_retriever.return_value = [{"lot_hash": "h1", "chunk_type": "t1", "chunk_text": "text", "distance": 0.1}]
    mock_llm.side_effect = APITimeoutError("Timeout")
    
    response = client.post(
        "/api/query",
        json={"question": "Timeout test"}
    )
    
    assert response.status_code == 504
    assert "초과되었습니다" in response.json()["detail"]
