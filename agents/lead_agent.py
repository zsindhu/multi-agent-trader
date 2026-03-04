"""
Lead Agent — Portfolio Manager & Orchestrator.
Monitors portfolio health, assigns securities to workers,
enforces risk limits, and coordinates run cycles.
"""
from loguru import logger
from .base_agent import BaseAgent


class LeadAgent:
    def __init__(self, workers: list[BaseAgent], risk_manager=None, performance_logger=None):
        self.workers = {w.name: w for w in workers}
        self.risk_manager = risk_manager
        self.performance_logger = performance_logger

    async def run_cycle(self):
        logger.info("[Lead] Starting orchestration cycle...")
        if self.risk_manager:
            risk_ok = await self.risk_manager.check_portfolio_health()
            if not risk_ok:
                logger.warning("[Lead] Risk limits breached. Pausing.")
                return
        await self._update_assignments()
        results = {}
        for name, worker in self.workers.items():
            if worker.is_active:
                try:
                    results[name] = await worker.run_cycle()
                except Exception as e:
                    logger.error(f"[Lead] Worker {name} failed: {e}")
        if self.performance_logger:
            await self.performance_logger.log_cycle(results)
        await self._evaluate_worker_performance()
        logger.info("[Lead] Cycle complete.")
        return results

    async def _update_assignments(self):
        """Assign securities to workers based on IV rank and strategy fit."""
        logger.info("[Lead] Updating security assignments...")
        # TODO: IV-based screening and assignment logic

    async def _evaluate_worker_performance(self):
        """Review worker metrics and adjust assignments."""
        logger.info("[Lead] Evaluating worker performance...")
        # TODO: Performance-based rotation logic
