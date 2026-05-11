import asyncpg
from typing import Optional
from src.config import settings
import structlog

logger = structlog.get_logger()

class DatabasePool:
    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        if not self._pool:
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=settings.database_url,
                    min_size=settings.PG_POOL_MIN,
                    max_size=settings.PG_POOL_MAX,
                    # Pre-load pgvector if needed, but usually it's already there
                )
                logger.info("db_pool_connected", host=settings.PG_HOST, db=settings.PG_NAME)
            except Exception as e:
                logger.error("db_connection_failed", error=str(e))
                raise

    async def disconnect(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("db_pool_disconnected")

    def get_pool(self) -> asyncpg.Pool:
        if not self._pool:
            raise RuntimeError("Database pool not initialized. Call connect() first.")
        return self._pool

db_pool = DatabasePool()

async def get_db():
    async with db_pool.get_pool().acquire() as connection:
        yield connection
