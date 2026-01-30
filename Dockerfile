# Multi-stage build for optimized image size
# ============================================
# Stage 1: Builder - Install dependencies
# ============================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies (only in builder stage)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /root/.local/bin/poetry /usr/local/bin/poetry

# Configure Poetry
ENV POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install dependencies (production only)
RUN poetry install --only main --no-root

# ============================================
# Stage 2: Runtime - Minimal production image
# ============================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install only runtime dependencies (no build tools)
RUN apt-get update && apt-get install -y \
    netcat-traditional \
    libpq5 \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY ./app /app/app
COPY ./alembic /app/alembic
COPY ./alembic.ini /app/alembic.ini
COPY ./docker-entrypoint.sh /app/docker-entrypoint.sh

# Create non-root user and set permissions
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app && \
    chmod +x /app/docker-entrypoint.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
