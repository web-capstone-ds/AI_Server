import numpy as np
import torch
import torch.nn.functional as F
from typing import List
from sentence_transformers import SentenceTransformer
from src.config import settings
import structlog

logger = structlog.get_logger()

class Embedder:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.ort_model = None
        self.use_onnx = False
        self.dimension = settings.EMBEDDING_DIMENSION
        self.device = settings.EMBEDDING_DEVICE

    def load_model(self):
        if self.model is None and self.ort_model is None:
            try:
                logger.info("loading_embedding_model", model=settings.EMBEDDING_MODEL, device=self.device)
                
                if settings.EMBEDDING_USE_ONNX:
                    try:
                        from optimum.onnxruntime import ORTModelForFeatureExtraction
                        from transformers import AutoTokenizer
                        
                        self.tokenizer = AutoTokenizer.from_pretrained(settings.EMBEDDING_MODEL)
                        self.ort_model = ORTModelForFeatureExtraction.from_pretrained(
                            settings.EMBEDDING_MODEL, 
                            export=True
                        )
                        self.use_onnx = True
                        logger.info("embedding_model_onnx_loaded")
                        return
                    except ImportError:
                        logger.warning("optimum_not_installed_fallback_to_st")
                        self.use_onnx = False

                # Fallback to standard SentenceTransformer
                self.model = SentenceTransformer(
                    settings.EMBEDDING_MODEL, 
                    device=self.device
                )
                logger.info("embedding_model_loaded")
            except Exception as e:
                logger.error("embedding_model_load_failed", error=str(e))
                raise

    def _mean_pooling(self, model_output, attention_mask):
        token_embeddings = model_output.last_hidden_state
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)

    def embed_texts(self, texts: List[str]) -> List[np.ndarray]:
        if not self.use_onnx and self.model is None:
            self.load_model()
        if self.use_onnx and self.ort_model is None:
            self.load_model()
        
        if self.use_onnx:
            inputs = self.tokenizer(
                texts, 
                padding=True, 
                truncation=True, 
                max_length=settings.EMBEDDING_MAX_SEQ_LENGTH, 
                return_tensors="pt"
            )
            with torch.no_grad():
                outputs = self.ort_model(**inputs)
            
            embeddings = self._mean_pooling(outputs, inputs['attention_mask'])
            embeddings = F.normalize(embeddings, p=2, dim=1)
            return list(embeddings.cpu().numpy())
        else:
            embeddings = self.model.encode(
                texts, 
                batch_size=settings.EMBEDDING_BATCH_SIZE,
                show_progress_bar=False,
                convert_to_numpy=True
            )
            return list(embeddings)

    def embed_query(self, query: str) -> np.ndarray:
        if not self.use_onnx and self.model is None:
            self.load_model()
        if self.use_onnx and self.ort_model is None:
            self.load_model()
        
        # Prefix query with 'query: ' for e5 models
        prefixed_query = f"query: {query}"
        
        if self.use_onnx:
            inputs = self.tokenizer(
                [prefixed_query], 
                padding=True, 
                truncation=True, 
                max_length=settings.EMBEDDING_MAX_SEQ_LENGTH, 
                return_tensors="pt"
            )
            with torch.no_grad():
                outputs = self.ort_model(**inputs)
                
            embeddings = self._mean_pooling(outputs, inputs['attention_mask'])
            embeddings = F.normalize(embeddings, p=2, dim=1)
            return embeddings.cpu().numpy()[0]
        else:
            embedding = self.model.encode(
                prefixed_query,
                convert_to_numpy=True
            )
            return embedding

embedder = Embedder()
