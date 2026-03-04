"""
Premium Trader — FastAPI Backend.

REST endpoints for portfolio, positions, trades, scanner, agents, and backtest.
WebSocket for live streaming updates.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from api.state import AppState
from api.routes import portfolio, trades, agents, scanner, backtest


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

# CORS — allow the Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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


# ── Health ──────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


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
