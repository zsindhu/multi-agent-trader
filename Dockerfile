# ── Stage 1: Build the React dashboard ──────────────────────────────
FROM node:20-alpine AS dashboard-build
WORKDIR /app
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

# ── Stage 2: Python backend ──────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

# System deps (gcc for compiled packages)
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source
COPY agents/ agents/
COPY api/ api/
COPY config/ config/
COPY core/ core/
COPY data/ data/
COPY models/ models/
COPY scripts/ scripts/
COPY services/ services/
COPY alembic/ alembic/
COPY alembic.ini main.py ./

# Built dashboard from stage 1
COPY --from=dashboard-build /app/dist dashboard/dist

# Persistent data directories
RUN mkdir -p data/backtest_cache data/backtest_results

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
