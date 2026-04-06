#!/usr/bin/env python3
"""
Preflight Smoke Test — catches import errors, missing deps, and broken migrations
in 30 seconds before you deploy.

Usage:
    python scripts/preflight.py          # full check (local)
    python scripts/preflight.py --ci     # CI-safe: skips modules that need broker credentials

Exit codes:
    0 = all clear
    1 = something is broken — fix before deploying
"""
import sys
import os
import argparse
import importlib
import traceback

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODULES = [
    # Models
    "models",
    "models.trade",
    "models.position",
    "models.performance",
    "models.opportunity",
    "models.journal_entry",
    "models.wheel_state",
    "models.proposal",
    "models.execution_log",
    "models.regime_snapshot",
    "models.earnings_event",
    "models.performance_insight",
    "models.news_headline",
    "models.playbook_entry",
    "models.strategy_insight",
    "models.worker_state",
    "models.equity_snapshot",
    # Core
    "core.database",
    "core.broker",
    "core.portfolio",
    "core.risk_manager",
    "core.strategy",
    "core.bootstrap",
    # Data
    "data.market_feed",
    "data.options_chain",
    # Services
    "services.alpaca_broker",
    "services.logger_service",
    "services.notifier",
    "services.market_regime",
    "services.vix_service",
    "services.earnings_calendar",
    "services.performance_analyst",
    "services.news_feed",
    "services.llm_service",
    "services.order_reconciler",
    "services.backtester",
    # Agents
    "agents",
    "agents.base_agent",
    "agents.lead_agent",
    "agents.scanner",
    "agents.trade_journal",
    "agents.worker_cc",
    "agents.worker_csp",
    "agents.worker_wheel",
    # API
    "api.state",
    "api.routes.portfolio",
    "api.routes.trades",
    "api.routes.agents",
    "api.routes.scanner",
    "api.routes.backtest",
    "api.routes.settings",
    "api.routes.proposals",
    "api.routes.account",
    "api.routes.executions",
    "api.routes.intelligence",
    "api.routes.diagnostics",
    # Config
    "config.settings",
]


# Modules that instantiate broker clients or make network calls at import.
# Skipped in --ci mode where credentials aren't available.
CI_SKIP = {
    "core.bootstrap",
}


def check_imports(ci_mode=False):
    """Import every module and report failures."""
    print("1/2  Importing all modules...")
    failed = []
    for mod in MODULES:
        if ci_mode and mod in CI_SKIP:
            print(f"  SKIP  {mod}  (--ci mode)")
            continue
        try:
            importlib.import_module(mod)
            print(f"  OK  {mod}")
        except Exception as e:
            print(f"  FAIL  {mod}: {e}")
            failed.append((mod, traceback.format_exc()))
    return failed


def check_migrations():
    """Run alembic upgrade head against an in-memory SQLite to verify migrations."""
    print("\n2/2  Checking Alembic migrations against in-memory SQLite...")
    try:
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", "sqlite:///")
        command.upgrade(alembic_cfg, "head")
        print("  OK  Migrations applied successfully")
        return None
    except Exception:
        return traceback.format_exc()


def main():
    parser = argparse.ArgumentParser(description="Preflight smoke test")
    parser.add_argument("--ci", action="store_true", help="CI mode: skip modules needing credentials")
    args = parser.parse_args()

    print("=" * 60)
    print("Premium Trader — Preflight Smoke Test")
    if args.ci:
        print("  (CI mode — skipping credential-dependent modules)")
    print("=" * 60)
    print()

    import_failures = check_imports(ci_mode=args.ci)
    migration_error = check_migrations()

    print()
    print("=" * 60)

    if import_failures or migration_error:
        print("PREFLIGHT FAILED")
        print("=" * 60)
        if import_failures:
            print(f"\n{len(import_failures)} module(s) failed to import:\n")
            for mod, tb in import_failures:
                print(f"--- {mod} ---")
                print(tb)
        if migration_error:
            print("\nMigration check failed:\n")
            print(migration_error)
        sys.exit(1)
    else:
        print("PREFLIGHT PASSED — safe to deploy")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    main()
