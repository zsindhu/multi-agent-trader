"""
Chat Routes — RAG Chat Agent endpoint for natural language queries.
"""
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.chat_agent import ChatAgent

router = APIRouter()

# In-memory session store: session_id → {"messages": [...], "last_access": float}
_sessions: dict[str, dict] = {}
_SESSION_TTL = 3600  # 1 hour
_MAX_HISTORY = 20

# Singleton chat agent
_agent = ChatAgent()


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    data: Optional[dict] = None
    actions_taken: list = []
    session_id: str
    elapsed_ms: Optional[int] = None


def _cleanup_sessions():
    """Remove sessions older than TTL."""
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s["last_access"] > _SESSION_TTL]
    for sid in expired:
        del _sessions[sid]


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest):
    """Send a message to the RAG Chat Agent."""
    if not _agent.is_enabled:
        raise HTTPException(status_code=503, detail="Chat agent is disabled — no TOGETHER_API_KEY configured")

    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Clean up stale sessions periodically
    _cleanup_sessions()

    # Get or create session
    session_id = body.session_id or str(uuid.uuid4())
    if session_id not in _sessions:
        _sessions[session_id] = {"messages": [], "last_access": time.time()}

    session = _sessions[session_id]
    session["last_access"] = time.time()

    # Add user message to history
    session["messages"].append({"role": "user", "content": body.message})

    # Call chat agent with history
    _started = time.time()
    result = await _agent.chat(
        message=body.message,
        history=session["messages"][:-1],  # Exclude current message (agent receives it directly)
    )
    _elapsed_ms = int((time.time() - _started) * 1000)

    # Add assistant response to history
    session["messages"].append({"role": "assistant", "content": result["response"]})

    # Trim history to max
    if len(session["messages"]) > _MAX_HISTORY:
        session["messages"] = session["messages"][-_MAX_HISTORY:]

    return ChatResponse(
        response=result["response"],
        data=result.get("data"),
        actions_taken=result.get("actions_taken", []),
        session_id=session_id,
        elapsed_ms=_elapsed_ms,
    )


@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Clear a chat session's history."""
    if session_id in _sessions:
        del _sessions[session_id]
    return {"status": "cleared", "session_id": session_id}
