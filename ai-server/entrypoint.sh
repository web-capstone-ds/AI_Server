#!/bin/bash
set -e

# If the volume mount shadowed the pre-downloaded model, restore it
MODEL_DIR="${HF_HOME:-/app/model_cache}/hub"
if [ ! -d "$MODEL_DIR" ] || [ -z "$(ls -A "$MODEL_DIR" 2>/dev/null)" ]; then
    echo "Embedding model not found in volume — downloading..."
    python -c "
from sentence_transformers import SentenceTransformer
import os
SentenceTransformer(os.environ.get('EMBEDDING_MODEL', 'intfloat/multilingual-e5-small'))
"
fi

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
