import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from src.pipeline.job_worker import process_batch_job
from src.pipeline.jobs import job_tracker

@pytest.mark.asyncio
async def test_job_tracker_integration():
    """
    Verifies that process_batch_job correctly tracks its status in job_tracker.
    """
    batch_id = "test-tracker-batch"
    
    # Mocking dependencies to avoid real processing
    with patch("src.pipeline.job_worker.db_pool.get_pool") as mock_pool, \
         patch("src.pipeline.job_worker.create_chunks") as mock_chunks, \
         patch("src.pipeline.job_worker.embedder.embed_texts") as mock_embed, \
         patch("src.pipeline.job_worker.save_embeddings", new_callable=AsyncMock) as mock_save, \
         patch("src.pipeline.job_worker.update_job_status", new_callable=AsyncMock) as mock_status:
        
        # Setup mocks for successful minimal run
        mock_conn = AsyncMock()
        # Mock fetchrow for idempotency check (not completed)
        mock_conn.fetchrow.return_value = None
        
        class MockACN:
            async def __aenter__(self): return mock_conn
            async def __aexit__(self, *args): pass
            
        mock_pool.return_value.acquire.return_value = MockACN()
        mock_chunks.return_value = [] # No chunks, but tracker should still work
        
        # Call the background worker
        await process_batch_job(batch_id)
        
        # If it finished without error, tracker should be empty
        assert batch_id not in job_tracker.active_jobs
