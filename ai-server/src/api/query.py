from fastapi import APIRouter, Depends, HTTPException
from anthropic import APITimeoutError
from src.db.pool import db_pool
from src.models.query import QueryRequest, QueryResponse, Source
from src.rag.retriever import retrieve_relevant_chunks
from src.rag.reranker import rerank_chunks
from src.rag.context_builder import build_context
from src.llm.client import llm_client
from src.llm.prompts import RAG_SYSTEM_PROMPT, QUERY_TEMPLATE
from src.utils.auth import verify_backend_jwt
import structlog

router = APIRouter(prefix="/api/query", tags=["query"])
logger = structlog.get_logger()

@router.post("", response_model=QueryResponse)
async def query_ai(
    request: QueryRequest,
    _ = Depends(verify_backend_jwt)
):
    logger.info("query_received", question=request.question[:100], filters=request.filters)
    
    async with db_pool.get_pool().acquire() as conn:
        # 1. Retrieve relevant chunks from Vector DB
        try:
            chunks = await retrieve_relevant_chunks(
                conn, 
                request.question, 
                top_k=15, # Retrieve a bit more for reranking
                filters=request.filters
            )
        except Exception as e:
            logger.error("retrieval_failed", error=str(e))
            raise HTTPException(status_code=500, detail="데이터 검색 중 오류가 발생했습니다.")
        
        if not chunks:
            return QueryResponse(
                answer="현재 등록된 데이터 중 분석 가능한 관련 정보를 찾을 수 없습니다. 질문을 조금 더 구체적으로 작성하거나 다른 필터를 적용해 주세요.",
                sources=[],
                confidence=0.0
            )
            
        # 2. Re-ranking
        reranked_chunks = rerank_chunks(request.question, chunks)
        top_chunks = reranked_chunks[:10] # Use top 10 for context
        
        # 3. Build context string
        context_str = build_context(top_chunks)
        
        # 4. Call LLM
        user_prompt = QUERY_TEMPLATE.format(
            context=context_str,
            question=request.question
        )
        
        try:
            answer = await llm_client.get_completion(RAG_SYSTEM_PROMPT, user_prompt)
        except APITimeoutError:
            logger.error("llm_timeout")
            raise HTTPException(status_code=504, detail="AI 분석 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.")
        except Exception as e:
            logger.error("query_llm_failed", error=str(e))
            raise HTTPException(status_code=500, detail="AI 분석 중 오류가 발생했습니다.")
            
        # 5. Build response
        sources = [
            Source(
                lotHash=c["lot_hash"],
                chunk_type=c["chunk_type"],
                distance=c["distance"],
                metadata={
                    "equipment_id": c.get("equipment_id"),
                    "recipe_id": c.get("recipe_id"),
                    "dispatched_at": str(c.get("dispatched_at"))
                }
            ) for c in top_chunks
        ]
        
        # Simple confidence calculation based on best distance
        # Lower distance (cosine) means higher similarity.
        best_distance = top_chunks[0]["distance"] if top_chunks else 1.0
        confidence = max(0.0, min(1.0, 1.0 - best_distance))
        
        return QueryResponse(
            answer=answer,
            sources=sources,
            confidence=round(float(confidence), 2)
        )
