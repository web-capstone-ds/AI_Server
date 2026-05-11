import numpy as np
from typing import List
from sentence_transformers import SentenceTransformer
from src.config import settings
import structlog

logger = structlog.get_logger()

class Embedder:
    def __init__(self):
        self.model = None
        self.dimension = settings.EMBEDDING_DIMENSION
        self.device = settings.EMBEDDING_DEVICE

    def load_model(self):
        if self.model is None:
            try:
                logger.info("loading_embedding_model", model=settings.EMBEDDING_MODEL, device=self.device)
                
                # Load the model. If USE_ONNX is True, we would ideally use optimum.onnxruntime
                # For this implementation, we'll use the standard SentenceTransformer
                # which can be optimized with ONNX if the library is available and configured.
                self.model = SentenceTransformer(
                    settings.EMBEDDING_MODEL, 
                    device=self.device
                )
                
                if settings.EMBEDDING_USE_ONNX:
                    # In a real production environment, we'd use the ONNX exported version
                    # For now, we'll stick to the base model but acknowledge the config
                    logger.info("embedding_model_onnx_config_detected")
                
                logger.info("embedding_model_loaded")
            except Exception as e:
                logger.error("embedding_model_load_failed", error=str(e))
                raise

    def embed_texts(self, texts: List[str]) -> List[np.ndarray]:
        if self.model is None:
            self.load_model()
        
        # multilingual-e5-small requires 'passage: ' or 'query: ' prefix
        # We assume the chunks already have 'passage: ' prefix from chunker.py
        
        embeddings = self.model.encode(
            texts, 
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True
        )
        return list(embeddings)

    def embed_query(self, query: str) -> np.ndarray:
        if self.model is None:
            self.load_model()
        
        # Prefix query with 'query: ' for e5 models
        prefixed_query = f"query: {query}"
        embedding = self.model.encode(
            prefixed_query,
            convert_to_numpy=True
        )
        return embedding

embedder = Embedder()
