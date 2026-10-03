FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency specification first for better layer caching
COPY pyproject.toml ./

# Install the package in editable mode with all dependencies
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir -e .

# Copy source code
COPY src/ ./src/
COPY config/ ./config/

# Re-install to pick up source
RUN pip install --no-cache-dir -e .

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Default entrypoint — overridden by docker-compose command
CMD ["sentinelops-api"]
