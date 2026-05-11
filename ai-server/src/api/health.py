from fastapi import APIRouter
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
        health_status["components"]["database"] = f"unhealthy: {str(e)}"
    
    # Check embedding model status
    if embedder.model is not None:
        health_status["components"]["embedding_model"] = "healthy"
    else:
        health_status["status"] = "unhealthy"
        health_status["components"]["embedding_model"] = "unloaded"
    
    return health_status
