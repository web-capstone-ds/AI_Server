from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class QueryRequest(BaseModel):
    question: str = Field(..., description="사용자의 질문")
    filters: Optional[Dict[str, Any]] = Field(None, description="필터 (recipeHash, equipmentId, equipmentHash, date_range)")

class Source(BaseModel):
    lotHash: str
    chunk_type: str
    distance: float
    metadata: Optional[Dict[str, Any]] = None

class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    confidence: float = 1.0
