import asyncpg
from typing import List
import numpy as np
from src.models.dispatch_batch import DispatchBatch
from src.pipeline.chunker import Chunk
import structlog

logger = structlog.get_logger()

async def save_embeddings(
    conn: asyncpg.Connection, 
    batch: DispatchBatch, 
    chunks: List[Chunk], 
    embeddings: List[np.ndarray]
):
    """
    Saves chunks and their embeddings to lot_embeddings table.
    """
    await conn.execute("DELETE FROM lot_embeddings WHERE batch_id = $1", batch.batchId)

    query = """
    INSERT INTO lot_embeddings (
        batch_id, lot_hash, equipment_hash, equipment_id, recipe_hash,
        chunk_type, chunk_text, embedding, yield_pct, lot_status,
        total_units, fail_count, dispatched_at
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, $9, $10, $11, $12, $13)
    """
    
    ls = batch.lotSummary
    data = []
    for chunk, emb in zip(chunks, embeddings):
        # Convert numpy array to list for asyncpg (then cast to vector in SQL)
        # Note: pgvector expects a string representation or a specific format.
        # Using string representation '[1.0, 2.0, ...]' is often the easiest for generic drivers.
        emb_str = "[" + ",".join(map(str, emb.tolist())) + "]"
        
        data.append((
            batch.batchId,
            batch.lotHash,
            batch.equipmentHash,
            batch.equipmentId,
            ls.recipeHash,
            chunk.type,
            chunk.text,
            emb_str, # Will be cast to vector in SQL if needed, but pgvector handles string format
            ls.yield_pct,
            ls.lot_status,
            ls.total_units,
            ls.fail_count,
            batch.dispatchedAt
        ))
    
    # We use executemany for efficiency
    await conn.executemany(query, data)
    logger.info("embeddings_saved_to_db", batch_id=batch.batchId, count=len(data))
