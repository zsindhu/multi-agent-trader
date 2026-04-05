"""WorkerState Model — Persists worker is_active flag across process boundaries."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func

from models import Base


class WorkerState(Base):
    __tablename__ = "worker_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    worker_name = Column(String, nullable=False, unique=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    paused_reason = Column(String, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=datetime.utcnow)
