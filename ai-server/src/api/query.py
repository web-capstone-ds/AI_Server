import re

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


ALARM_RECOMMENDATION_PATTERN = re.compile(
    r"\[권고\]\s*제어 추천\s+ALARM-(?P<level>[A-Z]+)\s*\n"
    r"(?P<code>[A-Z0-9_]+)-?\s*\n"
    r"권고 조치:\s*(?P<action>[^\n]+)",
    re.MULTILINE,
)


def normalize_mobile_alarm_recommendations(answer: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        level = match.group("level").strip().upper()
        code = match.group("code").strip().upper()
        action = normalize_recommended_action(match.group("action"))
        title = summarize_alarm_title(level, code, action)
        prefix = f"[{level}]:" if level == "CRITICAL" else f"[{level}]"
        return f"{prefix} {title}\n권고 조치: {action}"

    return ALARM_RECOMMENDATION_PATTERN.sub(replacement, answer)


def normalize_recommended_action(action: str) -> str:
    normalized = action.strip()
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    normalized = normalized.replace("상태조회", "상태 조회")
    return normalized


def summarize_alarm_title(level: str, code: str, action: str) -> str:
    if level == "WARNING" and ("VISION" in code or "RECIPE" in code or "레시피" in action):
        return "LOT 레시피 이상"
    if level == "CRITICAL" and ("EAP" in code or "DISCON" in code or "상태 조회" in action):
        return "장비 정지"
    return "장비 경보 발생"


@router.post("", response_model=QueryResponse)
async def query_ai(
    request: QueryRequest,
    _=Depends(verify_backend_jwt),
):
    logger.info("query_received", question=request.question[:100], filters=request.filters)

    async with db_pool.get_pool().acquire() as conn:
        try:
            chunks = await retrieve_relevant_chunks(
                conn,
                request.question,
                top_k=15,
                filters=request.filters,
            )
        except Exception as e:
            logger.error("retrieval_failed", error=str(e))
            raise HTTPException(status_code=500, detail="데이터 검색 중 오류가 발생했습니다.")

        if not chunks:
            return QueryResponse(
                answer=(
                    "현재 등록된 데이터 중 분석 가능한 관련 정보를 찾을 수 없습니다. "
                    "질문을 조금 더 구체적으로 작성하거나 다른 필터를 적용해 주세요."
                ),
                sources=[],
                confidence=0.0,
            )

        reranked_chunks = rerank_chunks(request.question, chunks)
        top_chunks = reranked_chunks[:10]
        context_str = build_context(top_chunks)

        user_prompt = QUERY_TEMPLATE.format(
            context=context_str,
            question=request.question,
        )

        try:
            answer = await llm_client.get_completion(RAG_SYSTEM_PROMPT, user_prompt)
        except APITimeoutError:
            logger.error("llm_timeout")
            raise HTTPException(
                status_code=504,
                detail="AI 분석 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
            )
        except Exception as e:
            logger.error("query_llm_failed", error=str(e))
            raise HTTPException(status_code=500, detail="AI 분석 중 오류가 발생했습니다.")

        answer = normalize_mobile_alarm_recommendations(answer)

        sources = [
            Source(
                lotHash=c["lot_hash"],
                chunk_type=c["chunk_type"],
                distance=c["distance"],
                metadata={
                    "equipment_id": c.get("equipment_id"),
                    "recipe_hash": c.get("recipe_hash"),
                    "dispatched_at": str(c.get("dispatched_at")),
                },
            )
            for c in top_chunks
        ]

        best_distance = top_chunks[0]["distance"] if top_chunks else 1.0
        confidence = max(0.0, min(1.0, 1.0 - best_distance))

        return QueryResponse(
            answer=answer,
            sources=sources,
            confidence=round(float(confidence), 2),
        )
