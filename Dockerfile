FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.10.11
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/data/models \
    ORACLE_DATA_DIR=/data \
    ORACLE_TORCH_THREADS=4
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY oracle ./oracle
RUN uv sync --frozen --no-dev \
    && useradd -u 10001 -m oracle \
    && mkdir -p /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 8787
CMD ["crypto-oracle", "serve", "--host", "0.0.0.0", "--port", "8787"]
