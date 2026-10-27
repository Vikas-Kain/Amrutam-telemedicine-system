# Multi-stage Dockerfile for Amrutam Telemedicine Backend API

# ==========================================
# Stage 1: Build stage
# ==========================================
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create virtual environment for clean dependency isolation
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy package manifests and application source to build package wheel
COPY pyproject.toml README.md ./
COPY app ./app

# Install production dependencies
RUN pip install --upgrade pip && \
    pip install .

# ==========================================
# Stage 2: Minimal runtime stage
# ==========================================
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PORT=8000

# Install curl for container health check probes and remove apt cache
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create unprivileged system group and user (non-root runtime)
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/sh -d /home/appuser -m appuser

# Set app directory ownership
RUN chown -R appuser:appgroup /app

# Copy virtual environment from builder stage
COPY --from=builder --chown=appuser:appgroup /opt/venv /opt/venv

# Copy application source code and metadata (excluding secrets via .dockerignore)
COPY --chown=appuser:appgroup app /app/app
COPY --chown=appuser:appgroup pyproject.toml README.md /app/

# Switch to unprivileged user
USER appuser

EXPOSE 8000

# Health check using process liveness endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

# Launch Uvicorn server as PID 1 for clean SIGTERM signal handling
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
