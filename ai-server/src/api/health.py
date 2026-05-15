from fastapi import APIRouter
from fastapi.responses import JSONResponse
from src.db.pool import db_pool
from src.pipeline.embedder import embedder
import structlog

router = APIRouter(prefix="/health", tags=["system"])
logger = structlog.get_logger()

@router.get("")
async def health_check():
    health_status = {"status": "ok", "components": {}}

    # Check DB
    try:
        async with db_pool.get_pool().acquire() as conn:
            await conn.execute("SELECT 1")
        health_status["components"]["database"] = "healthy"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["components"]["database"] = "unhealthy"

    # Check embedding model status
    if embedder.model is not None or embedder.ort_model is not None:
        health_status["components"]["embedding_model"] = "healthy"
    else:
        health_status["status"] = "unhealthy"
        health_status["components"]["embedding_model"] = "unloaded"

    status_code = 503 if health_status["status"] == "unhealthy" else 200
    return JSONResponse(content=health_status, status_code=status_code)
