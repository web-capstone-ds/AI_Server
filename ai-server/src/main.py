from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.config import settings
from src.utils.logging_config import setup_logging
from src.db.pool import db_pool
from src.api import ingest, health, batches, query, report
from src.pipeline.embedder import embedder
from src.scheduler.report_scheduler import report_scheduler
from src.pipeline.jobs import job_tracker
import structlog

# Initialize logging before everything else
setup_logging()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("app_startup", env=settings.APP_ENV)
    await db_pool.connect()
    
    # Pre-load embedding model (Task A2)
    try:
        # We wrap in try to prevent startup failure if model is missing during A1 testing
        embedder.load_model()
    except Exception as e:
        logger.warning("embedding_model_not_loaded", error=str(e))
    
    # Start Scheduler (Task A4)
    try:
        report_scheduler.start()
    except Exception as e:
        logger.warning("scheduler_not_started", error=str(e))
    
    yield
    
    # Shutdown
    logger.info("app_shutdown_started")
    
    # 1. Stop scheduler
    try:
        report_scheduler.stop()
    except Exception as e:
        logger.warning("scheduler_stop_failed", error=str(e))
    
    # 2. Wait for background jobs (Task A6)
    await job_tracker.wait_for_completion(timeout=20.0)
    
    # 3. Disconnect DB
    await db_pool.disconnect()
    logger.info("app_shutdown_completed")

app = FastAPI(
    title="DS Vision AI Server",
    version="0.1.0",
    lifespan=lifespan
)

# Task A1: Include Ingest and Health Routers
app.include_router(ingest.router)
app.include_router(health.router)
# Task A1: Placeholder for Batches API (KPI source)
app.include_router(batches.router)

# AI Query and Report API
app.include_router(query.router)
app.include_router(report.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app", 
        host=settings.APP_HOST, 
        port=settings.APP_PORT, 
        reload=(settings.APP_ENV == "development")
    )
