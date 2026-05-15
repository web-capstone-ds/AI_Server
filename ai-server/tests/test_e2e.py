import pytest
import time
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock
from src.main import app
from src.utils.auth import verify_ingest_api_key, verify_backend_jwt
from tests.fixtures.large_batch_generator import generate_large_batch

client = TestClient(app)

@pytest.fixture(autouse=True)
def skip_auth():
    app.dependency_overrides[verify_ingest_api_key] = lambda: "test-key"
    app.dependency_overrides[verify_backend_jwt] = lambda: {"sub": "test-user"}
    yield
    app.dependency_overrides = {}

class AsyncContextManagerMock:
    def __init__(self, return_value=None):
        self.return_value = return_value
    async def __aenter__(self):
        return self.return_value
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

@pytest.mark.asyncio
async def test_e2e_ingest_performance_and_background_split():
    """
    Verifies that /api/ingest responds quickly (<10s) even for 2,792 records,
    and background processing is handled separately.
    """
    large_batch = generate_large_batch(2792)
    
    # Mock DB pool
    with patch("src.api.ingest.db_pool.get_pool") as mock_get_pool:
        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.transaction.return_value = AsyncContextManagerMock()
        mock_conn.execute = AsyncMock()
        mock_conn.executemany = AsyncMock()
        
        mock_get_pool.return_value.acquire.return_value = AsyncContextManagerMock(return_value=mock_conn)
        
        with patch("src.api.ingest.check_batch_id_exists", new_callable=AsyncMock) as mock_check, \
             patch("src.api.ingest.save_ingest_batch", new_callable=AsyncMock), \
             patch("src.api.ingest.create_ingest_job", new_callable=AsyncMock), \
             patch("src.api.ingest.process_batch_job", new_callable=AsyncMock) as mock_bg_job:
            
            mock_check.return_value = None
            
            start_time = time.time()
            response = client.post(
                "/api/ingest",
                json=large_batch,
                headers={"X-API-Key": "test-key"}
            )
            end_time = time.time()
            
            # 1. Performance Check
            duration = end_time - start_time
            assert response.status_code == 200
            assert duration < 10.0, f"Ingest took too long: {duration}s"
            
            # 2. Background task was enqueued
            mock_bg_job.assert_called_once()

@pytest.mark.asyncio
async def test_e2e_duplicate_accepted():
    """
    Verifies that re-sending the same batchId returns 200 duplicate_accepted.
    """
    batch = generate_large_batch(10)
    
    with patch("src.api.ingest.db_pool.get_pool") as mock_get_pool:
        mock_conn = MagicMock()
        mock_conn.transaction.return_value = AsyncContextManagerMock()
        mock_get_pool.return_value.acquire.return_value = AsyncContextManagerMock(return_value=mock_conn)
        
        with patch("src.api.ingest.check_batch_id_exists", new_callable=AsyncMock) as mock_check, \
             patch("src.api.ingest.save_ingest_batch", new_callable=AsyncMock), \
             patch("src.api.ingest.create_ingest_job", new_callable=AsyncMock), \
             patch("src.api.ingest.process_batch_job", new_callable=AsyncMock):
            
            # First call - Success
            mock_check.return_value = None # Not duplicate
            response1 = client.post("/api/ingest", json=batch)
            assert response1.status_code == 200
            assert response1.json()["status"] == "accepted"
            
            # Second call - Duplicate
            mock_check.return_value = {
                'lot_hash': batch['lotHash'], 
                'equipment_hash': batch['equipmentHash']
            }
            response2 = client.post("/api/ingest", json=batch)
            assert response2.status_code == 200
            assert response2.json()["status"] == "duplicate_accepted"

@pytest.mark.asyncio
async def test_e2e_graceful_shutdown():
    """
    Verifies that shutdown waits for active jobs.
    """
    from src.pipeline.jobs import job_tracker
    from src.main import lifespan
    
    job_tracker.add_job("test-batch-1")
    
    with patch.object(job_tracker, 'wait_for_completion', new_callable=AsyncMock) as mock_wait:
        with patch("src.main.db_pool.connect", new_callable=AsyncMock):
            with patch("src.main.db_pool.disconnect", new_callable=AsyncMock):
                with patch("src.main.report_scheduler.stop"):
                    with patch("src.main.embedder.load_model"):
                        with patch("src.main.report_scheduler.start"):
                
                            async def run_lifespan():
                                async with lifespan(app):
                                    pass
                            
                            await run_lifespan()
                            mock_wait.assert_called_once_with(timeout=20.0)
    
    job_tracker.remove_job("test-batch-1")
