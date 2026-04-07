# Stage 1: Build React UI
FROM node:20-slim AS ui-builder
WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci --ignore-scripts
COPY ui/ ./
RUN npm run build


# Stage 2: Install Python dependencies
FROM python:3.12-slim AS py-builder
WORKDIR /build
RUN pip install --no-cache-dir uv
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt


# Stage 3: Final runtime image
FROM python:3.12-slim
WORKDIR /app

# System deps (git + curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=py-builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=py-builder /usr/local/bin /usr/local/bin

# Copy source code
COPY src/ ./src/
COPY cli/ ./cli/

# Copy React build from ui-builder
COPY --from=ui-builder /ui/build ./ui/build/

# Non-root user
RUN useradd -m -u 1000 orcai \
    && mkdir -p /data /workspace /skills /project \
    && chown -R orcai:orcai /app /data /workspace /skills /project
USER orcai

# Volumes
VOLUME /data
VOLUME /workspace
VOLUME /skills
VOLUME /project

ENV PORT=8100
ENV MCP_AUTH_TOKEN=""
ENV MCP_AUTH_DISABLED=false
ENV IDE_TARGET=claude
ENV MAX_CONCURRENT_AGENTS=3
ENV TASK_QUEUE_SIZE=20
ENV DATA_DIR=/data
ENV WORKSPACE_DIR=/workspace
ENV SKILLS_DIR=/skills
ENV PROJECT_DIR=/project

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8100/health || exit 1

CMD ["python", "-m", "src.main"]
