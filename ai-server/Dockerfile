FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Explicit cache path — must match docker-compose volume mount
ENV HF_HOME=/app/model_cache

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Install python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir .

# Copy source code and migration files
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Prepare cache directory for mounted model volume
RUN mkdir -p /app/model_cache && chown -R appuser:appuser /app
USER appuser


# Change ownership and switch user
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
