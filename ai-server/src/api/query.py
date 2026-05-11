from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from src.db.pool import db_pool
from src.rag.retriever import retrieve_relevant_chunks
from src.llm.client import llm_client
from src.llm.prompts import RAG_SYSTEM_PROMPT, QUERY_TEMPLATE
from src.utils.auth import verify_backend_jwt
import structlog

router = APIRouter(prefix="/api/query", tags=["query"])
logger = structlog.get_logger()

class QueryRequest(BaseModel):
    question: str
    filters: Optional[Dict[str, Any]] = None

class QueryResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    confidence: float = 1.0

@router.post("", response_model=QueryResponse)
async def query_ai(
    request: QueryRequest,
    _ = Depends(verify_backend_jwt)
):
    logger.info("query_received", question=request.question)
    
    async with db_pool.get_pool().acquire() as conn:
        # 1. Retrieve relevant chunks
        chunks = await retrieve_relevant_chunks(
            conn, 
            request.question, 
            top_k=10, 
            filters=request.filters
        )
        
        if not chunks:
            return QueryResponse(
                answer="현재 등록된 데이터 중 관련 정보를 찾을 수 없습니다. 조금 더 구체적으로 질문해 주세요.",
                sources=[]
            )
            
        # 2. Build context string
        context_parts = []
        for i, c in enumerate(chunks):
            # Format each chunk for the prompt
            part = (
                f"[{i+1}] {c['chunk_text']} "
                f"(장비: {c['equipment_id']}, 레시피: {c['recipe_id']}, "
                f"수율: {c['yield_pct']}%, 시각: {c['dispatched_at']})"
            )
            context_parts.append(part)
        context_str = "\n".join(context_parts)
        
        # 3. Call LLM
        user_prompt = QUERY_TEMPLATE.format(
            context=context_str,
            question=request.question
        )
        
        try:
            answer = await llm_client.get_completion(RAG_SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            logger.error("query_llm_failed", error=str(e))
            raise HTTPException(status_code=500, detail="AI 분석 중 오류가 발생했습니다.")
            
        return QueryResponse(
            answer=answer,
            sources=[{
                "lotHash": c["lot_hash"],
                "chunk_type": c["chunk_type"],
                "distance": c["distance"]
            } for c in chunks]
        )
