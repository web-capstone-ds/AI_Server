import pytest
from unittest.mock import AsyncMock
from src.rag.retriever import retrieve_relevant_chunks

@pytest.mark.asyncio
async def test_retrieve_relevant_chunks_no_filters():
    # Mock connection
    conn = AsyncMock()
    conn.fetch.return_value = [
        {
            "chunk_type": "summary",
            "chunk_text": "test content",
            "lot_hash": "hash1",
            "equipment_id": "EQ1",
            "equipment_hash": "eqhash1",
            "recipe_hash": "recipehash1",
            "yield_pct": 98.5,
            "fail_count": 10,
            "total_units": 1000,
            "dispatched_at": "2024-01-01",
            "distance": 0.1
        }
    ]
    
    # Call
    results = await retrieve_relevant_chunks(conn, "test query", top_k=5)
    
    # Assert
    assert len(results) == 1
    assert results[0]["lot_hash"] == "hash1"
    conn.fetch.assert_called_once()
    # Check if vector cast is in the query
    args, _ = conn.fetch.call_args
    assert "$1::vector" in args[0]

@pytest.mark.asyncio
async def test_retrieve_relevant_chunks_with_filters():
    conn = AsyncMock()
    conn.fetch.return_value = []
    
    filters = {
        "equipmentId": "EQ1",
        "recipeHash": "recipehash1",
        "date_range": {
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z"
        }
    }
    
    await retrieve_relevant_chunks(conn, "query", filters=filters)
    
    args, _ = conn.fetch.call_args
    query = args[0]
    assert "equipment_id = $2" in query
    assert "recipe_hash = $3" in query
    assert "dispatched_at >= $4" in query
    assert "dispatched_at <= $5" in query
