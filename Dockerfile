FROM python:3.14-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Astral uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Configure environment variables
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    GOSMART_MS_HOST=0.0.0.0 \
    GOSMART_MS_PORT=8000 \
    GOSMART_MS_SCP_PORT=11112 \
    PATH="/app/.venv/bin:$PATH"

# Install dependencies with caching before copying application code
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy project files into container
COPY . .

# Finalize project installation
RUN uv sync --frozen && chmod +x /app/start.sh

# Expose HTTP (FastAPI / DICOMweb / MCP SSE) and DICOM SCP ports
EXPOSE 8000 11112

# Launch application via start.sh
CMD ["/app/start.sh"]

