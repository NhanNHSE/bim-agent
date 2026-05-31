# ============================================================
# Stage 1: Builder — install dependencies in a clean layer
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for compilation (ifcopenshell, psycopg2, lxml)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ============================================================
# Stage 2: Runtime — minimal image for production
# ============================================================
FROM python:3.11-slim AS runtime

LABEL maintainer="BIM AI Team"
LABEL description="BIM AI Agent Backend — FastAPI + GraphRAG"

# Non-root user for security
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Runtime-only system deps (no build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY src/ /app/src/
COPY scripts/ /app/scripts/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini
COPY pytest.ini /app/pytest.ini
COPY tests/ /app/tests/

# Create data + cache directories with correct ownership
RUN mkdir -p /app/data/ifc /app/data/pdf /app/data/cache \
    /home/appuser/.cache/huggingface \
    /home/appuser/.cache/fastembed && \
    chown -R appuser:appuser /app /home/appuser/.cache

# Switch to non-root user
USER appuser

# Cache directories for embedding models
ENV HF_HOME=/home/appuser/.cache/huggingface
ENV FASTEMBED_CACHE_PATH=/home/appuser/.cache/fastembed

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Production: no --reload, multiple workers
CMD ["uvicorn", "src.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--timeout-keep-alive", "65", \
     "--access-log"]
