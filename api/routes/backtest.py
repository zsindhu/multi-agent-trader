"""
Backtest Routes — Run backtests, get results, compare strategies.
"""
import asyncio
import json
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel

from api.state import AppState
from services.backtester import BacktestEngine, BacktestResult, compare_backtests

router = APIRouter()


def _get_state(request: Request) -> AppState:
    return request.app.state.app


# In-memory store for backtest jobs (job_id -> result)
_backtest_jobs: dict[str, dict] = {}

RESULTS_DIR = "data/backtest_results"


class BacktestRequest(BaseModel):
    agent_type: str = "worker_csp"
    symbols: list[str] = ["AAPL", "MSFT", "SPY"]
    days: int = 180
    initial_capital: float = 100_000.0
    param_overrides: Optional[dict] = None


class CompareRequest(BaseModel):
    agent_type: str = "worker_csp"
    symbols: list[str] = ["AAPL", "MSFT", "SPY"]
    days: int = 180
    initial_capital: float = 100_000.0
    params_a: dict = {}
    params_b: dict = {}


async def _run_backtest_job(job_id: str, req: BacktestRequest, broker):
    """Background task to run a backtest."""
    _backtest_jobs[job_id]["status"] = "running"
    try:
        engine = BacktestEngine(
            agent_type=req.agent_type,
            symbols=req.symbols,
            days=req.days,
            param_overrides=req.param_overrides or {},
            initial_capital=req.initial_capital,
            real_broker=broker,
        )
        result = await engine.run()

        # Save to file
        os.makedirs(RESULTS_DIR, exist_ok=True)
        result_path = os.path.join(RESULTS_DIR, f"{job_id}.json")
        result.save_json(result_path)

        _backtest_jobs[job_id]["status"] = "completed"
        _backtest_jobs[job_id]["result"] = result.to_dict()

    except Exception as e:
        _backtest_jobs[job_id]["status"] = "failed"
        _backtest_jobs[job_id]["error"] = str(e)


@router.post("/run")
async def run_backtest(
    request: Request,
    body: BacktestRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start a backtest job (runs in background).

    Returns a job_id to poll for results.
    """
    state = _get_state(request)
    job_id = str(uuid.uuid4())[:8]

    _backtest_jobs[job_id] = {
        "status": "queued",
        "request": body.dict(),
        "result": None,
        "error": None,
    }

    background_tasks.add_task(_run_backtest_job, job_id, body, state.broker)

    return {"job_id": job_id, "status": "queued"}


@router.get("/status/{job_id}")
async def get_backtest_status(job_id: str):
    """Check the status of a backtest job."""
    job = _backtest_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": job["status"],
        "error": job.get("error"),
    }


@router.get("/results/{job_id}")
async def get_backtest_results(job_id: str):
    """Get full backtest results for a completed job."""
    job = _backtest_jobs.get(job_id)

    # Check in-memory first
    if job and job.get("result"):
        return job["result"]

    # Check saved file
    result_path = os.path.join(RESULTS_DIR, f"{job_id}.json")
    if os.path.exists(result_path):
        with open(result_path, "r") as f:
            return json.load(f)

    if job:
        if job["status"] == "running":
            return {"status": "running", "message": "Backtest still in progress"}
        elif job["status"] == "failed":
            raise HTTPException(status_code=500, detail=job.get("error", "Unknown error"))

    raise HTTPException(status_code=404, detail="Results not found")


@router.get("/results")
async def list_backtest_results():
    """List all saved backtest results."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    results = []
    for filename in sorted(os.listdir(RESULTS_DIR), reverse=True):
        if filename.endswith(".json"):
            filepath = os.path.join(RESULTS_DIR, filename)
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)
                results.append({
                    "job_id": filename.replace(".json", ""),
                    "agent_type": data.get("agent_type"),
                    "symbols": data.get("symbols", []),
                    "start_date": data.get("start_date"),
                    "end_date": data.get("end_date"),
                    "total_return": data.get("total_return"),
                    "sharpe_ratio": data.get("sharpe_ratio"),
                    "trade_count": data.get("trade_count"),
                })
            except Exception:
                continue

    return {"results": results}


@router.post("/compare")
async def compare(
    request: Request,
    body: CompareRequest,
    background_tasks: BackgroundTasks,
):
    """Run two backtests with different params and compare."""
    state = _get_state(request)
    job_id = f"cmp-{str(uuid.uuid4())[:6]}"

    _backtest_jobs[job_id] = {
        "status": "queued",
        "request": body.dict(),
        "result": None,
        "error": None,
    }

    async def _run_compare():
        _backtest_jobs[job_id]["status"] = "running"
        try:
            result_a, result_b = await compare_backtests(
                agent_type=body.agent_type,
                symbols=body.symbols,
                days=body.days,
                params_a=body.params_a,
                params_b=body.params_b,
                initial_capital=body.initial_capital,
                real_broker=state.broker,
            )

            _backtest_jobs[job_id]["status"] = "completed"
            _backtest_jobs[job_id]["result"] = {
                "params_a": result_a.to_dict(),
                "params_b": result_b.to_dict(),
            }

            # Save
            os.makedirs(RESULTS_DIR, exist_ok=True)
            with open(os.path.join(RESULTS_DIR, f"{job_id}.json"), "w") as f:
                json.dump(_backtest_jobs[job_id]["result"], f, indent=2, default=str)

        except Exception as e:
            _backtest_jobs[job_id]["status"] = "failed"
            _backtest_jobs[job_id]["error"] = str(e)

    background_tasks.add_task(_run_compare)

    return {"job_id": job_id, "status": "queued"}


# ── Active jobs ─────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs():
    """List all backtest jobs (active and completed)."""
    return {
        "jobs": [
            {
                "job_id": jid,
                "status": job["status"],
                "request": job.get("request"),
                "error": job.get("error"),
            }
            for jid, job in _backtest_jobs.items()
        ]
    }
