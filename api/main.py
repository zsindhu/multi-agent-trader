"""
Premium Trader — FastAPI Backend.

REST endpoints for portfolio, positions, trades, scanner, agents, and backtest.
WebSocket for live streaming updates.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger

from config.settings import settings as app_settings
from api.state import AppState
from api.routes import portfolio, trades, agents, scanner, backtest, settings, proposals, account, executions, intelligence, diagnostics, research, dashboard


# ── Lifespan ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared services on startup, tear down on shutdown."""
    logger.info("[API] Starting up...")
    state = AppState()
    await state.initialize()
    app.state.app = state
    yield
    logger.info("[API] Shutting down...")


# ── App ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Premium Trader API",
    description="Multi-agent options trading dashboard backend",
    version="1.0.0",
    lifespan=lifespan,
)


class NoCacheAPIMiddleware(BaseHTTPMiddleware):
    """Prevent browsers and proxies from caching any /api/ response."""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["Vary"] = "Accept"
        return response


# Must be added BEFORE CORSMiddleware (Starlette runs middleware LIFO)
app.add_middleware(NoCacheAPIMiddleware)

# CORS — allow the Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
        "http://localhost:5175", "http://127.0.0.1:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Route Registration ──────────────────────────────────────────────

app.include_router(portfolio.router, prefix="/api/portfolio", tags=["Portfolio"])
app.include_router(trades.router, prefix="/api/trades", tags=["Trades"])
app.include_router(agents.router, prefix="/api/agents", tags=["Agents"])
app.include_router(scanner.router, prefix="/api/scanner", tags=["Scanner"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["Backtest"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(proposals.router, prefix="/api/proposals", tags=["Proposals"])
app.include_router(account.router, prefix="/api/account", tags=["Account"])
app.include_router(executions.router, prefix="/api/executions", tags=["Executions"])
app.include_router(intelligence.router, prefix="/api/intelligence", tags=["Intelligence"])
app.include_router(diagnostics.router, prefix="/api/diagnostics", tags=["Diagnostics"])
app.include_router(research.router, tags=["Research"])  # No /api prefix — serves HTML at /research
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])


# ── Health ──────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    from sqlalchemy import text
    from core.database import AsyncSessionLocal
    db_ok = False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        pass
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "trading_mode": app_settings.trading_mode,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── WebSocket ───────────────────────────────────────────────────────

class ConnectionManager:
    """Manages WebSocket connections for live updates."""

    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)
        logger.info(f"[WS] Client connected ({len(self.connections)} total)")

    def disconnect(self, ws: WebSocket):
        self.connections.remove(ws)
        logger.info(f"[WS] Client disconnected ({len(self.connections)} total)")

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)


ws_manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client can send commands
            data = await websocket.receive_text()
            msg = json.loads(data)
            cmd = msg.get("command")

            if cmd == "ping":
                await websocket.send_json({"type": "pong"})

            elif cmd == "subscribe_portfolio":
                # Send current portfolio snapshot
                state: AppState = websocket.app.state.app
                snapshot = await state.get_portfolio_snapshot()
                await websocket.send_json({"type": "portfolio", "data": snapshot})

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"[WS] Error: {e}")
        ws_manager.disconnect(websocket)


# Make ws_manager accessible for broadcasting from background tasks
app.state.ws_manager = ws_manager


# ── Dashboard Static Files (production) ─────────────────────────────
# Must be registered LAST — catch-all would intercept /api routes otherwise.
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_dashboard_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard", "dist")
if os.path.exists(_dashboard_dist):
    _assets_dir = os.path.join(_dashboard_dist, "assets")
    if os.path.exists(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="static-assets")

    def _serve_index():
        """Return index.html with strict no-cache headers."""
        resp = FileResponse(os.path.join(_dashboard_dist, "index.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    @app.get("/{path:path}")
    async def serve_dashboard(path: str):
        file_path = os.path.join(_dashboard_dist, path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        # SPA fallback — never cache index.html since it references hashed bundles
        return _serve_index()
