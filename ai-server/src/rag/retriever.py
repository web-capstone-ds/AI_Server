import asyncpg
from typing import List, Dict, Any, Optional
from src.pipeline.embedder import embedder
import structlog

logger = structlog.get_logger()

async def retrieve_relevant_chunks(
    conn: asyncpg.Connection,
    query: str,
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Search for similar chunks in lot_embeddings using pgvector cosine distance.
    """
    # 1. Generate query embedding
    query_vector = embedder.embed_query(query)
    # Convert to list for asyncpg to handle casting to vector(384)
    query_vector_list = query_vector.tolist()
    
    # 2. Build Query
    base_query = """
    SELECT chunk_type, chunk_text, lot_hash, equipment_id, equipment_hash, recipe_id, 
           yield_pct, fail_count, total_units, dispatched_at,
           (embedding <=> $1::vector) as distance
    FROM lot_embeddings
    """
    
    where_clauses = []
    params: List[Any] = [query_vector_list]
    
    if filters:
        if filters.get("equipmentId"):
            params.append(filters["equipmentId"])
            where_clauses.append(f"equipment_id = ${len(params)}")
        if filters.get("equipmentHash"):
            params.append(filters["equipmentHash"])
            where_clauses.append(f"equipment_hash = ${len(params)}")
        if filters.get("recipeId"):
            params.append(filters["recipeId"])
            where_clauses.append(f"recipe_id = ${len(params)}")
        if filters.get("lotHash"):
            params.append(filters["lotHash"])
            where_clauses.append(f"lot_hash = ${len(params)}")
        
        # Date range filter (start_date, end_date)
        date_range = filters.get("date_range")
        if date_range and isinstance(date_range, dict):
            start_date = date_range.get("start")
            end_date = date_range.get("end")
            if start_date:
                params.append(start_date)
                where_clauses.append(f"dispatched_at >= ${len(params)}")
            if end_date:
                params.append(end_date)
                where_clauses.append(f"dispatched_at <= ${len(params)}")
            
    if where_clauses:
        base_query += " WHERE " + " AND ".join(where_clauses)
        
    base_query += " ORDER BY distance ASC LIMIT $" + str(len(params) + 1)
    params.append(top_k)
    
    # 3. Execute
    rows = await conn.fetch(base_query, *params)
    
    logger.info("retrieval_completed", count=len(rows))
    return [dict(row) for row in rows]
