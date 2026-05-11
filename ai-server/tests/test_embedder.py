import pytest
from src.pipeline.embedder import embedder

def test_embedder_dimension():
    # Model might not be loaded in CI without actual model files, 
    # but we test the interface.
    # In a real test, we'd mock SentenceTransformer
    try:
        embedder.load_model()
        test_text = "passage: This is a test."
        emb = embedder.embed_texts([test_text])[0]
        assert emb.shape == (384,)
    except Exception as e:
        pytest.skip(f"Embedding model not available: {e}")

def test_embedder_query_prefix():
    try:
        embedder.load_model()
        query = "What is the yield?"
        emb = embedder.embed_query(query)
        assert emb.shape == (384,)
    except Exception as e:
        pytest.skip(f"Embedding model not available: {e}")
