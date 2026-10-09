FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8000 \
    WATCH_FOLDER=/app/watch_folder \
    PROCESSED_FOLDER=/app/processed_folder \
    DATA_DIR=/app/data \
    OAUTH_BIND_ADDR=0.0.0.0 \
    OAUTH_HOST=localhost

WORKDIR /app

# Install system dependencies (curl for healthchecks, ca-certificates for TLS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Create target directories for persistent data and video folders
RUN mkdir -p /app/data /app/watch_folder /app/processed_folder /app/failed_folder

# Expose Web Dashboard (8000) and OAuth callback port (8088)
EXPOSE 8000 8088

# Healthcheck to verify FastAPI web dashboard is healthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/status || exit 1

# Default command starts the web dashboard and folder watcher
CMD ["python", "main.py", "--web", "--host", "0.0.0.0", "--port", "8000"]
