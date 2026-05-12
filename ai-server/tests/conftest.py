import os

# Set dummy environment variables for tests
os.environ["AI_INGEST_API_KEY"] = "test-key"
os.environ["BACKEND_JWT_SECRET"] = "test-secret"
os.environ["PG_PASSWORD"] = "changeit"
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"

from tests.fixtures.large_batch_generator import get_mock_batch, generate_large_batch

__all__ = ["get_mock_batch", "generate_large_batch"]
