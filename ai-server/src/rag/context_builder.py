from typing import List, Dict, Any

def build_context(chunks: List[Dict[str, Any]]) -> str:
    """
    Converts chunks into a formatted string for the LLM prompt.
    """
    context_parts = []
    for i, c in enumerate(chunks):
        # Format each chunk for the prompt with metadata
        part = (
            f"[{i+1}] {c['chunk_text']}\n"
            f"(장비ID: {c.get('equipment_id')}, 레시피해시: {c.get('recipe_hash')}, "
            f"수율: {c.get('yield_pct')}%, 불량수: {c.get('fail_count')}, "
            f"시각: {c.get('dispatched_at')})"
        )
        context_parts.append(part)
        
    return "\n\n".join(context_parts)
